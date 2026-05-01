"""Entry point for the Simple Usage Monitor application."""
from __future__ import annotations

import asyncio
import logging
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import ttk
from typing import Any

import yaml

from scrapers import OpenRouterScraper, WindsurfScraper

# ログ設定
DEBUG_MODE = "--debug" in sys.argv
if DEBUG_MODE:
    logging.basicConfig(level=logging.DEBUG, format="%(asctime)s [%(levelname)s] %(message)s")
else:
    logging.basicConfig(
        level=logging.ERROR,
        format="%(asctime)s [%(levelname)s] %(message)s",
        filename="error.log",
    )

CONFIG_PATH = Path(__file__).with_name("config.yaml")


SCRAPER_FACTORIES = {
    "windsurf": WindsurfScraper,
    "openrouter": OpenRouterScraper,
}


def load_config(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


class UsageMonitorApp:
    def __init__(self, root: tk.Tk, config: dict[str, Any]) -> None:
        self.root = root
        self.config = config
        self.headless = bool(config.get("headless", False))
        self.refresh_interval = int(config.get("refresh_interval", 10)) * 60  # 分→秒
        self.scrapers = self._build_scrapers()
        self.service_vars: dict[str, dict[str, tk.StringVar]] = {}
        self.service_frames: dict[str, tk.Widget] = {}  # 背景色変更用
        self.service_login_btns: dict[str, ttk.Button] = {}  # サービス別ログインボタン
        self.service_logged_in: dict[str, bool] = {}  # サービス別ログイン状態
        self._service_threads: dict[str, threading.Thread] = {}  # サービス別スレッド
        self._refresh_thread: threading.Thread | None = None
        self.thresholds = config.get("thresholds", {"windsurf_daily": 30, "windsurf_weekly": 20})
        self._build_ui()
        # 起動時は自動refreshしない（ログイン後に開始）

    def _build_scrapers(self) -> dict[str, Any]:
        services_cfg = self.config.get("services", {})
        scrapers = {}
        
        # セッションディレクトリを ./sessions/ 配下に統一
        base_session_dir = Path(__file__).parent / "sessions"
        base_session_dir.mkdir(parents=True, exist_ok=True)
        
        for key, svc_cfg in services_cfg.items():
            if not svc_cfg.get("enabled", True):
                continue
            factory = SCRAPER_FACTORIES.get(key)
            if not factory:
                continue
            
            # サービスごとのプロファイルディレクトリ
            session_dir = base_session_dir / key
            session_dir.mkdir(parents=True, exist_ok=True)
            
            scraper = factory(
                session_dir=session_dir,
                headless=self.headless,
                prompt_login=True,
            )
            scrapers[key] = scraper
        return scrapers

    def _build_ui(self) -> None:
        self.root.title("Simple Usage Monitor")
        self.root.geometry("900x700")  # より大きいデフォルトサイズ
        
        # リサイズを有効化（最小・最大サイズを設定）
        self.root.resizable(True, True)
        self.root.minsize(600, 400)  # 最小サイズ
        self.root.maxsize(1920, 1080)  # 最大サイズ

        # フォントサイズを1.8倍に設定
        default_font = ("TkDefaultFont", 16)  # 約9pt * 1.8
        self.root.option_add("*Font", default_font)

        container = ttk.Frame(self.root, padding=22)  # 12 * 1.8
        container.pack(fill="both", expand=True)

        self.status_var = tk.StringVar(value="Please login")
        status_row = ttk.Frame(container)
        status_row.pack(fill="x", pady=(0, 14))  # 8 * 1.8
        ttk.Label(status_row, textvariable=self.status_var, font=("TkDefaultFont", 16)).pack(side="left")
        
        # ボタンを右側に配置（Loginはサービス別なのでここにはない）
        button_frame = ttk.Frame(status_row)
        button_frame.pack(side="right")
        self.refresh_button = ttk.Button(button_frame, text="Refresh", command=self.refresh, state="disabled")
        self.refresh_button.pack(side="left", padx=5)
        ttk.Button(button_frame, text="Settings", command=self.open_settings).pack(side="left")

        for key in self.scrapers.keys():
            if key == "windsurf":
                # Windsurf親フレーム
                parent_frame = tk.Frame(container, relief="groove", borderwidth=2, padx=10, pady=10)
                parent_frame.pack(fill="x", pady=9)
                title_row_ws = tk.Frame(parent_frame)
                title_row_ws.pack(fill="x", pady=(0, 5))
                ttk.Label(title_row_ws, text="Windsurf", font=("TkDefaultFont", 18, "bold")).pack(side="left")
                login_btn = ttk.Button(title_row_ws, text="Login", command=lambda k=key: self.login_service(k))
                login_btn.pack(side="right")
                self.service_login_btns[key] = login_btn
                self.service_logged_in[key] = False
                
                # Daily/Weekly子フレーム
                for quota_type in ["daily", "weekly"]:
                    child_frame = tk.Frame(parent_frame, padx=15)
                    child_frame.pack(fill="x", pady=5)
                    
                    # タイトル行
                    title_row = tk.Frame(child_frame)
                    title_row.pack(fill="x")
                    ttk.Label(title_row, text=quota_type.capitalize(), font=("TkDefaultFont", 18, "bold")).pack(side="left")
                    
                    # エラー表示用（通常は非表示）
                    error_var = tk.StringVar(value="")
                    error_label = ttk.Label(title_row, textvariable=error_var, font=("TkDefaultFont", 14), foreground="red")
                    error_label.pack(side="left", padx=10)
                    
                    # データ行（2カラム）
                    data_frame = tk.Frame(child_frame)
                    data_frame.pack(fill="x", pady=(5, 0))
                    
                    percent_var = tk.StringVar(value="--")
                    reset_var = tk.StringVar(value="--")
                    
                    # 左カラム: Remaining
                    left_col = tk.Frame(data_frame)
                    left_col.pack(side="left", fill="x", expand=True)
                    ttk.Label(left_col, text="Remaining:", font=("TkDefaultFont", 14)).pack(anchor="w")
                    ttk.Label(left_col, textvariable=percent_var, font=("TkDefaultFont", 22, "bold")).pack(anchor="w")
                    
                    # 右カラム: Reset
                    right_col = tk.Frame(data_frame)
                    right_col.pack(side="left", fill="x", expand=True)
                    ttk.Label(right_col, text="Reset in", font=("TkDefaultFont", 14)).pack(anchor="w")
                    ttk.Label(right_col, textvariable=reset_var, font=("TkDefaultFont", 22, "bold")).pack(anchor="w")
                    
                    self.service_vars[f"windsurf_{quota_type}"] = {
                        "error": error_var,
                        "percent": percent_var,
                        "reset": reset_var,
                    }
                    self.service_frames[f"windsurf_{quota_type}"] = child_frame
            else:
                # OpenRouter親フレーム
                parent_frame = tk.Frame(container, relief="groove", borderwidth=2, padx=10, pady=10)
                parent_frame.pack(fill="x", pady=9)
                
                # タイトル行
                title_row = tk.Frame(parent_frame)
                title_row.pack(fill="x", pady=(0, 5))
                ttk.Label(title_row, text=key.capitalize(), font=("TkDefaultFont", 18, "bold")).pack(side="left")
                login_btn = ttk.Button(title_row, text="Login", command=lambda k=key: self.login_service(k))
                login_btn.pack(side="right")
                self.service_login_btns[key] = login_btn
                self.service_logged_in[key] = False
                
                # エラー表示用
                error_var = tk.StringVar(value="")
                error_label = ttk.Label(title_row, textvariable=error_var, font=("TkDefaultFont", 14), foreground="red")
                error_label.pack(side="left", padx=10)
                
                # Hour 子フレーム
                hour_frame = tk.Frame(parent_frame, padx=15)
                hour_frame.pack(fill="x", pady=5)
                ttk.Label(hour_frame, text="Hour", font=("TkDefaultFont", 18, "bold")).pack(anchor="w")
                
                hour_data_frame = tk.Frame(hour_frame, padx=15)
                hour_data_frame.pack(fill="x", pady=(5, 0))
                
                req_1h_var = tk.StringVar(value="--")
                tok_1h_var = tk.StringVar(value="--")
                
                # Requests列
                req_col = tk.Frame(hour_data_frame)
                req_col.pack(side="left", fill="x", expand=True)
                ttk.Label(req_col, text="Requests:", font=("TkDefaultFont", 14)).pack(anchor="w")
                ttk.Label(req_col, textvariable=req_1h_var, font=("TkDefaultFont", 22, "bold")).pack(anchor="w")
                
                # Tokens列
                tok_col = tk.Frame(hour_data_frame)
                tok_col.pack(side="left", fill="x", expand=True)
                ttk.Label(tok_col, text="Tokens:", font=("TkDefaultFont", 14)).pack(anchor="w")
                ttk.Label(tok_col, textvariable=tok_1h_var, font=("TkDefaultFont", 22, "bold")).pack(anchor="w")
                
                # Day 子フレーム
                day_frame = tk.Frame(parent_frame, padx=15)
                day_frame.pack(fill="x", pady=5)
                ttk.Label(day_frame, text="Day", font=("TkDefaultFont", 18, "bold")).pack(anchor="w")
                
                day_data_frame = tk.Frame(day_frame, padx=15)
                day_data_frame.pack(fill="x", pady=(5, 0))
                
                req_1d_var = tk.StringVar(value="--")
                tok_1d_var = tk.StringVar(value="--")
                
                # Requests列
                req_col_d = tk.Frame(day_data_frame)
                req_col_d.pack(side="left", fill="x", expand=True)
                ttk.Label(req_col_d, text="Requests:", font=("TkDefaultFont", 14)).pack(anchor="w")
                ttk.Label(req_col_d, textvariable=req_1d_var, font=("TkDefaultFont", 22, "bold")).pack(anchor="w")
                
                # Tokens列
                tok_col_d = tk.Frame(day_data_frame)
                tok_col_d.pack(side="left", fill="x", expand=True)
                ttk.Label(tok_col_d, text="Tokens:", font=("TkDefaultFont", 14)).pack(anchor="w")
                ttk.Label(tok_col_d, textvariable=tok_1d_var, font=("TkDefaultFont", 22, "bold")).pack(anchor="w")
                
                self.service_vars[key] = {
                    "error": error_var,
                    "req_1h": req_1h_var,
                    "tok_1h": tok_1h_var,
                    "req_1d": req_1d_var,
                    "tok_1d": tok_1d_var,
                }
                self.service_frames[key] = parent_frame

    def login_service(self, key: str) -> None:
        """サービス個別のログイン処理"""
        thread = self._service_threads.get(key)
        if thread and thread.is_alive():
            return
        self.service_login_btns[key].config(state="disabled", text="...")
        self.status_var.set(f"Connecting {key}...")
        thread = threading.Thread(target=lambda: self._service_login_worker(key), daemon=True)
        self._service_threads[key] = thread
        thread.start()

    def _service_login_worker(self, key: str) -> None:
        """サービス個別ログインワーカー（別スレッド）"""
        scraper = self.scrapers[key]
        
        # ブラウザを開いてログイン（セッションありなら即完了して閉じる）
        scraper.prompt_login = True
        scraper.headless = False
        self.root.after(0, lambda: self.status_var.set(f"Opening {key} browser..."))
        try:
            data = asyncio.run(scraper.run())
            self.root.after(0, lambda: self._after_service_login(key, data, None))
        except Exception as exc:
            logging.error(f"[{key}] Login failed: {exc}", exc_info=True)
            self.root.after(0, lambda: self._after_service_login(key, None, str(exc)))

    def _after_service_login(self, key: str, data: Any, error: str | None) -> None:
        """サービス個別ログイン完了後の処理"""
        if error:
            self.service_login_btns[key].config(state="normal", text="Login")
            self.status_var.set(f"{key} login failed")
            if key == "windsurf":
                for qtype in ["daily", "weekly"]:
                    v = self.service_vars.get(f"windsurf_{qtype}", {}).get("error")
                    if v:
                        v.set(f"Error: {error[:40]}")
            else:
                v = self.service_vars.get(key, {}).get("error")
                if v:
                    v.set(f"Error: {error[:40]}")
            return
        
        # ログイン成功 - まず状態とボタンを更新
        self.service_logged_in[key] = True
        self.service_login_btns[key].pack_forget()
        scraper = self.scrapers[key]
        scraper.prompt_login = False
        scraper.headless = True

        # Refreshボタンを先に有効化（データ表示エラーがあっても押せるように）
        self.refresh_button.config(state="normal")
        if all(self.service_logged_in.values()):
            self.status_var.set("All services logged in")
            self.root.after(self.refresh_interval * 1000, self.refresh)
        else:
            self.status_var.set(f"{key} logged in")
        
        # データを反映（失敗しても続行）
        try:
            if key == "windsurf" and data:
                self._update_windsurf_display(data)
            elif data:
                self._update_openrouter_display(key, data, self.service_vars[key])
        except Exception as exc:
            logging.error(f"[{key}] Display update failed: {exc}", exc_info=True)

    def refresh(self) -> None:
        if self._refresh_thread and self._refresh_thread.is_alive():
            return
        self.status_var.set("Refreshing...")
        for vars_dict in self.service_vars.values():
            if "error" in vars_dict:
                vars_dict["error"].set("")
        self._refresh_thread = threading.Thread(target=self._refresh_worker, daemon=True)
        self._refresh_thread.start()

    def _refresh_worker(self) -> None:
        try:
            results, errors = asyncio.run(self._fetch_all())
        except Exception as exc:  # pragma: no cover
            logging.error(f"Refresh failed: {exc}", exc_info=True)
            results = {}
            errors = {"_global": str(exc)}
        self.root.after(0, lambda: self._apply_results(results, errors))

    async def _fetch_all(self) -> tuple[dict[str, Any], dict[str, str]]:
        async def run_scraper(name: str, scraper: Any):
            try:
                data = await scraper.run()
                return name, data, None
            except Exception as exc:  # pragma: no cover
                return name, None, str(exc)

        # ログイン済みのサービスのみ実行
        tasks = [
            run_scraper(name, scraper)
            for name, scraper in self.scrapers.items()
            if self.service_logged_in.get(name, False)
        ]
        gathered = await asyncio.gather(*tasks)
        results: dict[str, Any] = {}
        errors: dict[str, str] = {}
        for name, data, error in gathered:
            if error:
                errors[name] = error
            else:
                results[name] = data
        return results, errors

    def _apply_results(self, results: dict[str, Any], errors: dict[str, str]) -> None:
        # セッション切れエラーをサービス別にチェック
        for svc_key, err in errors.items():
            if "Session expired" in str(err):
                self.service_logged_in[svc_key] = False
                # そのサービスのLoginボタンを再表示
                btn = self.service_login_btns.get(svc_key)
                if btn:
                    btn.config(state="normal", text="Login")
                    btn.pack(side="right")
        
        # ログイン中のサービスが1つもなければ Refresh 無効化
        if not any(self.service_logged_in.values()):
            self.refresh_button.config(state="disabled")
            self.status_var.set("Session expired - please login again")
            return
        # ログイン中のサービスがあれば Refresh は常に有効
        self.refresh_button.config(state="normal")
        
        if errors:
            self.status_var.set("Error occurred")
        else:
            self.status_var.set("Updated successfully")

        for name, vars_dict in self.service_vars.items():
            # Windsurf は個別処理
            if name.startswith("windsurf_"):
                continue
            
            if name in errors:
                vars_dict["error"].set(f"Error: {errors[name]}")
                vars_dict["req_1h"].set("--")
                vars_dict["tok_1h"].set("--")
                vars_dict["req_1d"].set("--")
                vars_dict["tok_1d"].set("--")
            else:
                vars_dict["error"].set("")
                self._update_openrouter_display(name, results.get(name), vars_dict)
        
        # Windsurf データを個別に処理
        if "windsurf" in results:
            self._update_windsurf_display(results["windsurf"])

        # ログイン済みのサービスがある場合のみ自動更新を継続
        if any(self.service_logged_in.values()):
            self.root.after(self.refresh_interval * 1000, self.refresh)

    def _update_openrouter_display(self, name: str, data: Any, vars_dict: dict) -> None:
        """OpenRouter専用の表示更新"""
        if not data:
            vars_dict["req_1h"].set("No data")
            vars_dict["tok_1h"].set("No data")
            vars_dict["req_1d"].set("No data")
            vars_dict["tok_1d"].set("No data")
            return
        
        one_h = data.get("1h", {})
        one_d = data.get("1d", {})
        
        # 1h データ
        vars_dict["req_1h"].set(str(one_h.get("requests", "--")))
        vars_dict["tok_1h"].set(str(one_h.get("tokens", "--")))
        
        # 1d データ
        vars_dict["req_1d"].set(str(one_d.get("requests", "--")))
        vars_dict["tok_1d"].set(str(one_d.get("tokens", "--")))

    def _update_windsurf_display(self, data: dict[str, Any]) -> None:
        """Windsurf専用の表示更新（daily/weeklyを個別に処理）"""
        daily = data.get("daily")
        weekly = data.get("weekly")
        
        if daily:
            percent = daily.get("percent", 0)
            reset = daily.get("reset", "--")
            self.service_vars["windsurf_daily"]["error"].set("")
            self.service_vars["windsurf_daily"]["percent"].set(f"{percent}%")
            self.service_vars["windsurf_daily"]["reset"].set(reset)
            # 閾値チェック
            threshold = self.thresholds.get("windsurf_daily", 30)
            if percent <= threshold:
                self.service_frames["windsurf_daily"].config(bg="#FF8C00")  # オレンジ
            else:
                self.service_frames["windsurf_daily"].config(bg="#D3D3D3")  # ライトグレー
        
        if weekly:
            percent = weekly.get("percent", 0)
            reset = weekly.get("reset", "--")
            self.service_vars["windsurf_weekly"]["error"].set("")
            self.service_vars["windsurf_weekly"]["percent"].set(f"{percent}%")
            self.service_vars["windsurf_weekly"]["reset"].set(reset)
            # 閾値チェック
            threshold = self.thresholds.get("windsurf_weekly", 20)
            if percent <= threshold:
                self.service_frames["windsurf_weekly"].config(bg="#FF8C00")  # オレンジ
            else:
                self.service_frames["windsurf_weekly"].config(bg="#D3D3D3")  # ライトグレー

    def open_settings(self) -> None:
        """設定ダイアログを開く"""
        dialog = tk.Toplevel(self.root)
        dialog.title("Settings")
        dialog.geometry("540x400")  # 300x220 * 1.8
        dialog.resizable(False, False)
        
        frame = ttk.Frame(dialog, padding=20)
        frame.pack(fill="both", expand=True)
        
        # 更新間隔
        ttk.Label(frame, text="Refresh interval (minutes):", font=("TkDefaultFont", 14)).grid(row=0, column=0, sticky="w", pady=10)
        refresh_var = tk.IntVar(value=self.config.get("refresh_interval", 10))
        ttk.Entry(frame, textvariable=refresh_var, font=("TkDefaultFont", 14), width=10).grid(row=0, column=1, sticky="w")
        
        # Windsurf Daily 閾値
        ttk.Label(frame, text="Windsurf Daily threshold (%):", font=("TkDefaultFont", 14)).grid(row=1, column=0, sticky="w", pady=10)
        daily_threshold_var = tk.IntVar(value=self.thresholds.get("windsurf_daily", 30))
        ttk.Entry(frame, textvariable=daily_threshold_var, font=("TkDefaultFont", 14), width=10).grid(row=1, column=1, sticky="w")
        
        # Windsurf Weekly 閾値
        ttk.Label(frame, text="Windsurf Weekly threshold (%):", font=("TkDefaultFont", 14)).grid(row=2, column=0, sticky="w", pady=10)
        weekly_threshold_var = tk.IntVar(value=self.thresholds.get("windsurf_weekly", 20))
        ttk.Entry(frame, textvariable=weekly_threshold_var, font=("TkDefaultFont", 14), width=10).grid(row=2, column=1, sticky="w")
        
        # サービス有効/無効
        ttk.Label(frame, text="Enabled services:", font=("TkDefaultFont", 14)).grid(row=3, column=0, sticky="w", pady=10, columnspan=2)
        
        service_vars = {}
        services_cfg = self.config.get("services", {})
        row = 4
        for key in ["windsurf", "openrouter"]:
            var = tk.BooleanVar(value=services_cfg.get(key, {}).get("enabled", True))
            ttk.Checkbutton(frame, text=key.capitalize(), variable=var, style="TCheckbutton").grid(row=row, column=0, sticky="w", padx=20)
            service_vars[key] = var
            row += 1
        
        def save_settings():
            # 設定を更新
            self.config["refresh_interval"] = refresh_var.get()
            self.refresh_interval = refresh_var.get() * 60
            self.thresholds["windsurf_daily"] = daily_threshold_var.get()
            self.thresholds["windsurf_weekly"] = weekly_threshold_var.get()
            self.config["thresholds"] = self.thresholds
            
            for key, var in service_vars.items():
                if key in self.config["services"]:
                    self.config["services"][key]["enabled"] = var.get()
            
            # config.yamlに保存
            with CONFIG_PATH.open("w", encoding="utf-8") as f:
                yaml.dump(self.config, f, default_flow_style=False, allow_unicode=True)
            
            dialog.destroy()
            self.status_var.set("Settings saved")
        
        # ボタン
        button_frame = ttk.Frame(frame)
        button_frame.grid(row=row, column=0, columnspan=2, pady=20)
        ttk.Button(button_frame, text="Save", command=save_settings).pack(side="left", padx=5)
        ttk.Button(button_frame, text="Cancel", command=dialog.destroy).pack(side="left")


def main() -> None:
    config = load_config(CONFIG_PATH)
    root = tk.Tk()
    UsageMonitorApp(root, config)
    root.mainloop()


if __name__ == "__main__":
    main()
