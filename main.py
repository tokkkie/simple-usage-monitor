"""Entry point for the Simple Usage Monitor application."""
from __future__ import annotations

import asyncio
import logging
import os
import signal
import sys
import threading
import time
import tkinter as tk
import webbrowser
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

CONFIG_PATH = Path(__file__).parent / "config.yaml"
PID_FILE = Path("/tmp/simple-usage-monitor.pid")


def _ensure_single_instance() -> None:
    if PID_FILE.exists():
        try:
            pid = int(PID_FILE.read_text().strip())
            os.kill(pid, signal.SIGTERM)
            time.sleep(0.5)
        except (OSError, ValueError):
            pass
    PID_FILE.write_text(str(os.getpid()))


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
        self.service_parent_frames: dict[str, tk.Frame] = {}  # クリック領域
        self.service_status_labels: dict[str, tk.Label] = {}  # ステータステキスト
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
        # ダークテーマ色定義
        BG_DARK = "#1a1a1a"
        BG_SECTION = "#2a2a2a"
        FG_WHITE = "#ffffff"
        FG_GRAY = "#b0b0b0"
        
        self.root.title("Usage Monitor")
        self.root.geometry(self.config.get("window_size", "900x700"))
        self.root.resizable(True, True)
        self.root.minsize(600, 400)
        self.root.maxsize(1920, 1080)
        self.root.config(bg=BG_DARK)
        
        # フォントサイズ
        default_font = ("TkDefaultFont", 16)
        self.root.option_add("*Font", default_font)

        # ヘッダーバー（黒背景）
        header = tk.Frame(self.root, bg=BG_DARK, height=60)
        header.pack(fill="x", side="top")
        header.pack_propagate(False)
        
        title_label = tk.Label(header, text="Usage Monitor", font=("TkDefaultFont", 18, "bold"), 
                              bg=BG_DARK, fg=FG_WHITE, cursor="hand2")
        title_label.pack(side="left", padx=20, pady=10)
        title_label.bind("<Button-1>", lambda e: self.open_settings())
        
        # ボタンを右側に配置
        button_frame = tk.Frame(header, bg=BG_DARK)
        button_frame.pack(side="right", padx=20, pady=10)
        self.refresh_button = tk.Button(button_frame, text="RELOAD", command=self.refresh, 
                                       bg="#444444", fg=FG_WHITE, font=("TkDefaultFont", 12, "bold"),
                                       relief="flat", padx=15, pady=5, state="disabled")
        self.refresh_button.pack(side="left", padx=5)

        # コンテンツエリア
        container = tk.Frame(self.root, bg=BG_DARK)
        container.pack(fill="both", expand=True, padx=10, pady=10)
        
        self.status_var = tk.StringVar(value="")
        self._status_label = tk.Label(container, textvariable=self.status_var, 
                                     bg=BG_DARK, fg=FG_GRAY, font=("TkDefaultFont", 12))
        self._status_label.pack(fill="x", pady=(0, 10))

        for key in self.scrapers.keys():
            if key == "windsurf":
                # Windsurf親フレーム
                parent_frame = tk.Frame(container, bg=BG_SECTION, padx=15, pady=10)
                parent_frame.pack(fill="x", pady=8)
                self.service_parent_frames[key] = parent_frame
                
                title_row = tk.Frame(parent_frame, bg=BG_SECTION)
                title_row.pack(fill="x", pady=(0, 8))
                tk.Label(title_row, text="WindSurf", font=("TkDefaultFont", 16, "bold"),
                        bg=BG_SECTION, fg=FG_WHITE).pack(side="left")
                status_lbl = tk.Label(title_row, text="Not logged in",
                                     font=("TkDefaultFont", 11), bg=BG_SECTION, fg="#666666")
                status_lbl.pack(side="left", padx=(12, 0))
                self.service_status_labels[key] = status_lbl
                self.service_logged_in[key] = False
                
                # Daily/Weekly行
                for quota_type in ["daily", "weekly"]:
                    row_frame = tk.Frame(parent_frame, bg=BG_SECTION)
                    row_frame.pack(fill="x", pady=4)
                    
                    label_text = quota_type.capitalize()
                    label = tk.Label(row_frame, text=label_text, font=("TkDefaultFont", 13),
                                    bg=BG_SECTION, fg=FG_GRAY, width=8, anchor="w")
                    label.pack(side="left")
                    
                    percent_var = tk.StringVar(value="--")
                    reset_var = tk.StringVar(value="--")
                    
                    reset_label = tk.Label(row_frame, textvariable=reset_var, font=("TkDefaultFont", 13),
                                          bg=BG_SECTION, fg=FG_GRAY)
                    reset_label.pack(side="right")

                    data_label = tk.Label(row_frame, textvariable=percent_var, font=("TkDefaultFont", 14, "bold"),
                                         bg=BG_SECTION, fg=FG_WHITE)
                    data_label.pack(side="right", padx=(0, 12))
                    
                    error_var = tk.StringVar(value="")
                    
                    self.service_vars[f"windsurf_{quota_type}"] = {
                        "error": error_var,
                        "percent": percent_var,
                        "reset": reset_var,
                    }
                    self.service_frames[f"windsurf_{quota_type}"] = row_frame
                self._setup_panel_click(key)
            else:
                # OpenRouter親フレーム
                parent_frame = tk.Frame(container, bg=BG_SECTION, padx=15, pady=10)
                parent_frame.pack(fill="x", pady=8)
                self.service_parent_frames[key] = parent_frame
                
                title_row = tk.Frame(parent_frame, bg=BG_SECTION)
                title_row.pack(fill="x", pady=(0, 8))
                tk.Label(title_row, text="OpenRouter", font=("TkDefaultFont", 16, "bold"),
                        bg=BG_SECTION, fg=FG_WHITE).pack(side="left")
                status_lbl = tk.Label(title_row, text="Not logged in",
                                     font=("TkDefaultFont", 11), bg=BG_SECTION, fg="#666666")
                status_lbl.pack(side="left", padx=(12, 0))
                self.service_status_labels[key] = status_lbl
                self.service_logged_in[key] = False
                
                error_var = tk.StringVar(value="")
                
                # Hour/Day メトリクス
                req_1h_var = tk.StringVar(value="--")
                tok_1h_var = tk.StringVar(value="--")
                req_1d_var = tk.StringVar(value="--")
                tok_1d_var = tk.StringVar(value="--")
                
                metrics = [
                    ("Request / h", req_1h_var),
                    ("Token / h", tok_1h_var),
                    ("Request / d", req_1d_var),
                    ("Token / d", tok_1d_var),
                ]
                
                for metric_name, metric_var in metrics:
                    row_frame = tk.Frame(parent_frame, bg=BG_SECTION)
                    row_frame.pack(fill="x", pady=3)
                    
                    label = tk.Label(row_frame, text=metric_name, font=("TkDefaultFont", 13),
                                    bg=BG_SECTION, fg=FG_GRAY, width=15, anchor="w")
                    label.pack(side="left")
                    
                    value_label = tk.Label(row_frame, textvariable=metric_var, font=("TkDefaultFont", 14, "bold"),
                                          bg=BG_SECTION, fg=FG_WHITE)
                    value_label.pack(side="right")
                
                self.service_vars[key] = {
                    "error": error_var,
                    "req_1h": req_1h_var,
                    "tok_1h": tok_1h_var,
                    "req_1d": req_1d_var,
                    "tok_1d": tok_1d_var,
                }
                self.service_frames[key] = parent_frame
                self._setup_panel_click(key)

    def _set_status(self, key: str, text: str, color: str) -> None:
        lbl = self.service_status_labels.get(key)
        if lbl:
            lbl.config(text=text, fg=color)

    def _setup_panel_click(self, key: str) -> None:
        def on_click(e):
            if self.service_logged_in.get(key, False):
                webbrowser.open(self.config["services"][key]["url"])
            else:
                self.login_service(key)
        def bind_recursive(widget):
            try:
                widget.bind("<Button-1>", on_click)
                widget.config(cursor="hand2")
            except Exception:
                pass
            for child in widget.winfo_children():
                bind_recursive(child)
        bind_recursive(self.service_parent_frames[key])

    def login_service(self, key: str) -> None:
        """サービス個別のログイン処理"""
        thread = self._service_threads.get(key)
        if thread and thread.is_alive():
            return
        self._set_status(key, "Connecting...", "#ccaa00")
        self.status_var.set(f"Connecting {key}...")
        thread = threading.Thread(target=lambda: self._service_login_worker(key), daemon=True)
        self._service_threads[key] = thread
        thread.start()

    def _service_login_worker(self, key: str) -> None:
        """サービス個別ログインワーカー（別スレッド）"""
        scraper = self.scrapers[key]
        try:
            # Phase 1: 表のブラウザでログインのみ
            scraper.prompt_login = True
            scraper.headless = False
            self.root.after(0, lambda: self.status_var.set(f"Opening {key} browser..."))
            asyncio.run(scraper.run(login_only=True))
            # Phase 2: ブラウザ閉じた後、ヘッドレスでデータ取得
            scraper.prompt_login = False
            scraper.headless = True
            self.root.after(0, lambda: self.status_var.set(f"Fetching {key} data..."))
            data = asyncio.run(scraper.run())
            self.root.after(0, lambda: self._after_service_login(key, data, None))
        except Exception as exc:
            logging.error(f"[{key}] Login failed: {exc}", exc_info=True)
            self.root.after(0, lambda: self._after_service_login(key, None, str(exc)))
        finally:
            def reset_if_stuck():
                lbl = self.service_status_labels.get(key)
                if lbl and lbl.cget("text") in ("Connecting...", "Fetching..."):
                    self._set_status(key, "Not logged in", "#666666")
            self.root.after(0, reset_if_stuck)

    def _after_service_login(self, key: str, data: Any, error: str | None) -> None:
        """サービス個別ログイン完了後の処理"""
        if error:
            self._set_status(key, "Login failed", "#cc4444")
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
        self._set_status(key, "Active", "#44cc44")
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
                self._set_status(svc_key, "Not logged in", "#666666")
        
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
                self.service_frames["windsurf_daily"].config(bg="#3a3a2a")  # 暗いオレンジ
            else:
                self.service_frames["windsurf_daily"].config(bg="#2a2a2a")  # 通常
        
        if weekly:
            percent = weekly.get("percent", 0)
            reset = weekly.get("reset", "--")
            self.service_vars["windsurf_weekly"]["error"].set("")
            self.service_vars["windsurf_weekly"]["percent"].set(f"{percent}%")
            self.service_vars["windsurf_weekly"]["reset"].set(reset)
            # 閾値チェック
            threshold = self.thresholds.get("windsurf_weekly", 20)
            if percent <= threshold:
                self.service_frames["windsurf_weekly"].config(bg="#3a3a2a")  # 暗いオレンジ
            else:
                self.service_frames["windsurf_weekly"].config(bg="#2a2a2a")  # 通常

    def open_settings(self) -> None:
        """設定ダイアログを開く"""
        BG_DARK = "#1a1a1a"
        BG_SECTION = "#2a2a2a"
        FG_WHITE = "#ffffff"
        FG_GRAY = "#b0b0b0"
        
        dialog = tk.Toplevel(self.root)
        dialog.title("Settings")
        dialog.geometry(self.config.get("settings_size", "540x460"))
        dialog.resizable(True, True)
        dialog.config(bg=BG_DARK)

        def on_dialog_close():
            self.config["settings_size"] = dialog.geometry().split("+")[0]
            with CONFIG_PATH.open("w", encoding="utf-8") as f:
                yaml.dump(self.config, f, default_flow_style=False, allow_unicode=True)
            dialog.destroy()

        dialog.protocol("WM_DELETE_WINDOW", on_dialog_close)
        
        frame = tk.Frame(dialog, bg=BG_DARK, padx=20, pady=20)
        frame.pack(fill="both", expand=True)
        
        # 更新間隔
        label1 = tk.Label(frame, text="Refresh interval (minutes):", font=("TkDefaultFont", 14),
                         bg=BG_DARK, fg=FG_WHITE)
        label1.grid(row=0, column=0, sticky="w", pady=10)
        refresh_var = tk.IntVar(value=self.config.get("refresh_interval", 10))
        entry1 = tk.Entry(frame, textvariable=refresh_var, font=("TkDefaultFont", 14), width=10,
                         bg=BG_SECTION, fg=FG_WHITE, insertbackground=FG_WHITE)
        entry1.grid(row=0, column=1, sticky="w")
        
        # Windsurf Daily 閾値
        label2 = tk.Label(frame, text="Windsurf Daily threshold (%):", font=("TkDefaultFont", 14),
                         bg=BG_DARK, fg=FG_WHITE)
        label2.grid(row=1, column=0, sticky="w", pady=10)
        daily_threshold_var = tk.IntVar(value=self.thresholds.get("windsurf_daily", 30))
        entry2 = tk.Entry(frame, textvariable=daily_threshold_var, font=("TkDefaultFont", 14), width=10,
                         bg=BG_SECTION, fg=FG_WHITE, insertbackground=FG_WHITE)
        entry2.grid(row=1, column=1, sticky="w")
        
        # Windsurf Weekly 閾値
        label3 = tk.Label(frame, text="Windsurf Weekly threshold (%):", font=("TkDefaultFont", 14),
                         bg=BG_DARK, fg=FG_WHITE)
        label3.grid(row=2, column=0, sticky="w", pady=10)
        weekly_threshold_var = tk.IntVar(value=self.thresholds.get("windsurf_weekly", 20))
        entry3 = tk.Entry(frame, textvariable=weekly_threshold_var, font=("TkDefaultFont", 14), width=10,
                         bg=BG_SECTION, fg=FG_WHITE, insertbackground=FG_WHITE)
        entry3.grid(row=2, column=1, sticky="w")
        
        # サービス有効/無効
        label4 = tk.Label(frame, text="Enabled services:", font=("TkDefaultFont", 14),
                         bg=BG_DARK, fg=FG_WHITE)
        label4.grid(row=3, column=0, sticky="w", pady=10, columnspan=2)
        
        service_vars = {}
        services_cfg = self.config.get("services", {})
        row = 4
        for key in ["windsurf", "openrouter"]:
            var = tk.BooleanVar(value=services_cfg.get(key, {}).get("enabled", True))
            cb = tk.Checkbutton(frame, text=key.capitalize(), variable=var,
                               bg=BG_DARK, fg=FG_WHITE, selectcolor=BG_SECTION, activebackground=BG_DARK,
                               activeforeground=FG_WHITE, font=("TkDefaultFont", 12))
            cb.grid(row=row, column=0, sticky="w", padx=20)
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
        button_frame = tk.Frame(frame, bg=BG_DARK)
        button_frame.grid(row=row, column=0, columnspan=2, pady=20)
        save_btn = tk.Button(button_frame, text="Save", command=save_settings,
                            bg="#444444", fg=FG_WHITE, font=("TkDefaultFont", 12),
                            relief="flat", padx=15, pady=5)
        save_btn.pack(side="left", padx=5)
        cancel_btn = tk.Button(button_frame, text="Cancel", command=dialog.destroy,
                              bg="#444444", fg=FG_WHITE, font=("TkDefaultFont", 12),
                              relief="flat", padx=15, pady=5)
        cancel_btn.pack(side="left")


def main() -> None:
    _ensure_single_instance()
    config = load_config(CONFIG_PATH)
    root = tk.Tk()
    UsageMonitorApp(root, config)

    def on_close():
        # ウィンドウサイズを記録（"WxH+x+y" → "WxH" のみ保存）
        config["window_size"] = root.geometry().split("+")[0]
        with CONFIG_PATH.open("w", encoding="utf-8") as f:
            yaml.dump(config, f, default_flow_style=False, allow_unicode=True)
        PID_FILE.unlink(missing_ok=True)
        root.quit()
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", on_close)
    signal.signal(signal.SIGINT, lambda *_: root.after(0, on_close))

    # mainloop()はC実装のためPythonのシグナルをチェックしない
    # 定期的にPythonに制御を戻してSIGINTを処理可能にする
    def _poll():
        root.after(200, _poll)
    root.after(200, _poll)

    try:
        root.mainloop()
    except KeyboardInterrupt:
        on_close()


if __name__ == "__main__":
    main()
