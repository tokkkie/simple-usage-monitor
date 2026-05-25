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

from scrapers import (
    CerebrasScraper,
    GroqScraper,
    OpenRouterScraper,
    SambaNovaScraper,
    WindsurfScraper,
)

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
    "groq": GroqScraper,
    "cerebras": CerebrasScraper,
    "sambanova": SambaNovaScraper,
}

BG_DARK = "#1a1a1a"
BG_SECTION = "#2a2a2a"
BG_WARN = "#3a3a2a"
FG_WHITE = "#ffffff"
FG_GRAY = "#b0b0b0"


DEFAULT_CONFIG: dict[str, Any] = {
    "headless": False,
    "refresh_interval": 10,
    "window_size": "500x520",
    "settings_size": "504x359",
    "services": {
        "windsurf": {"enabled": True, "url": "https://windsurf.com/subscription/usage"},
        "openrouter": {"enabled": True, "url": "https://openrouter.ai/activity"},
        "groq": {"enabled": True, "url": "https://console.groq.com/dashboard/usage?tab=activity"},
        "cerebras": {"enabled": True, "url": "https://cloud.cerebras.ai/"},
        "sambanova": {"enabled": True, "url": "https://cloud.sambanova.ai/plans/usage"},
    },
    "thresholds": {"windsurf_daily": 30, "windsurf_weekly": 20},
}


def load_config(path: Path) -> dict[str, Any]:
    if not path.exists():
        with path.open("w", encoding="utf-8") as f:
            yaml.dump(DEFAULT_CONFIG, f, default_flow_style=False, allow_unicode=True)
        return dict(DEFAULT_CONFIG)
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def save_config(config: dict[str, Any]) -> None:
    with CONFIG_PATH.open("w", encoding="utf-8") as f:
        yaml.dump(config, f, default_flow_style=False, allow_unicode=True)


class UsageMonitorApp:
    def __init__(self, root: tk.Tk, config: dict[str, Any]) -> None:
        """アプリの初期化：スクレイパー・UI・設定を構築する"""
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
        """config.yaml の services 設定を元にスクレイパーを生成する"""
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
        """メインウィンドウ全体のUIを構築する"""
        self.root.title("Usage Monitor")
        self.root.geometry(self.config.get("window_size", "500x520"))
        self.root.resizable(True, True)
        self.root.minsize(200, 200)
        self.root.config(bg=BG_DARK)
        self.root.option_add("*Font", ("TkDefaultFont", 16))

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
        tk.Label(container, textvariable=self.status_var,
                 bg=BG_DARK, fg=FG_GRAY, font=("TkDefaultFont", 12)).pack(fill="x", pady=(0, 10))
        ttk.Sizegrip(self.root).place(relx=1.0, rely=1.0, anchor="se")

        for key in self.scrapers:
            if key == "windsurf":
                self._build_windsurf_panel(container)
            elif key == "openrouter":
                self._build_openrouter_panel(key, container)
            elif key == "groq":
                self._build_groq_panel(container)
            elif key == "cerebras":
                self._build_cerebras_panel(container)
            elif key == "sambanova":
                self._build_sambanova_panel(container)

    def _build_windsurf_panel(self, container: tk.Frame) -> None:
        """Windsurf 用パネル（daily/weekly クォータ表示）を構築する"""
        key = "windsurf"
        parent = tk.Frame(container, bg=BG_SECTION, padx=15, pady=10)
        parent.pack(fill="x", pady=8)
        self.service_parent_frames[key] = parent

        title_row = tk.Frame(parent, bg=BG_SECTION)
        title_row.pack(fill="x", pady=(0, 8))
        tk.Label(title_row, text="WindSurf", font=("TkDefaultFont", 16, "bold"),
                 bg=BG_SECTION, fg=FG_WHITE).pack(side="left")
        status_lbl = tk.Label(title_row, text="Not logged in",
                              font=("TkDefaultFont", 11), bg=BG_SECTION, fg="#666666")
        status_lbl.pack(side="left", padx=(12, 0))
        self.service_status_labels[key] = status_lbl
        self.service_logged_in[key] = False

        for quota_type in ("daily", "weekly"):
            row = tk.Frame(parent, bg=BG_SECTION)
            row.pack(fill="x", pady=4)
            tk.Label(row, text=quota_type.capitalize(), font=("TkDefaultFont", 13),
                     bg=BG_SECTION, fg=FG_GRAY, width=8, anchor="w").pack(side="left")
            percent_var = tk.StringVar(value="--")
            reset_var = tk.StringVar(value="--")
            tk.Label(row, textvariable=reset_var, font=("TkDefaultFont", 13),
                     bg=BG_SECTION, fg=FG_GRAY).pack(side="right")
            tk.Label(row, textvariable=percent_var, font=("TkDefaultFont", 14, "bold"),
                     bg=BG_SECTION, fg=FG_WHITE).pack(side="right", padx=(0, 12))
            self.service_vars[f"windsurf_{quota_type}"] = {
                "error": tk.StringVar(value=""), "percent": percent_var, "reset": reset_var,
            }
            self.service_frames[f"windsurf_{quota_type}"] = row
        self._setup_panel_click(key)

    def _build_openrouter_panel(self, key: str, container: tk.Frame) -> None:
        """OpenRouter 用パネル（requests/tokens メトリクス表示）を構築する"""
        parent = tk.Frame(container, bg=BG_SECTION, padx=15, pady=10)
        parent.pack(fill="x", pady=8)
        self.service_parent_frames[key] = parent

        title_row = tk.Frame(parent, bg=BG_SECTION)
        title_row.pack(fill="x", pady=(0, 8))
        tk.Label(title_row, text="OpenRouter", font=("TkDefaultFont", 16, "bold"),
                 bg=BG_SECTION, fg=FG_WHITE).pack(side="left")
        status_lbl = tk.Label(title_row, text="Not logged in",
                              font=("TkDefaultFont", 11), bg=BG_SECTION, fg="#666666")
        status_lbl.pack(side="left", padx=(12, 0))
        self.service_status_labels[key] = status_lbl
        self.service_logged_in[key] = False

        metric_vars: dict[str, tk.StringVar] = {}
        for label_text, var_key in (
            ("Request / h", "req_1h"), ("Token / h", "tok_1h"),
            ("Request / d", "req_1d"), ("Token / d", "tok_1d"),
        ):
            var = tk.StringVar(value="--")
            row = tk.Frame(parent, bg=BG_SECTION)
            row.pack(fill="x", pady=3)
            tk.Label(row, text=label_text, font=("TkDefaultFont", 13),
                     bg=BG_SECTION, fg=FG_GRAY, width=15, anchor="w").pack(side="left")
            tk.Label(row, textvariable=var, font=("TkDefaultFont", 14, "bold"),
                     bg=BG_SECTION, fg=FG_WHITE).pack(side="right")
            metric_vars[var_key] = var
        self.service_vars[key] = {"error": tk.StringVar(value=""), **metric_vars}
        self.service_frames[key] = parent
        self._setup_panel_click(key)

    def _build_groq_panel(self, container: tk.Frame) -> None:
        """Groq 用パネル（Requests / Tokens 表示）を構築する"""
        key = "groq"
        parent = tk.Frame(container, bg=BG_SECTION, padx=15, pady=10)
        parent.pack(fill="x", pady=8)
        self.service_parent_frames[key] = parent

        title_row = tk.Frame(parent, bg=BG_SECTION)
        title_row.pack(fill="x", pady=(0, 8))
        tk.Label(title_row, text="Groq", font=("TkDefaultFont", 16, "bold"),
                 bg=BG_SECTION, fg=FG_WHITE).pack(side="left")
        status_lbl = tk.Label(title_row, text="Not logged in",
                              font=("TkDefaultFont", 11), bg=BG_SECTION, fg="#666666")
        status_lbl.pack(side="left", padx=(12, 0))
        self.service_status_labels[key] = status_lbl
        self.service_logged_in[key] = False

        metric_vars: dict[str, tk.StringVar] = {}
        for label_text, var_key in (
            ("Requests", "requests"), ("Tokens", "tokens"),
        ):
            var = tk.StringVar(value="--")
            row = tk.Frame(parent, bg=BG_SECTION)
            row.pack(fill="x", pady=3)
            tk.Label(row, text=label_text, font=("TkDefaultFont", 13),
                     bg=BG_SECTION, fg=FG_GRAY, width=15, anchor="w").pack(side="left")
            tk.Label(row, textvariable=var, font=("TkDefaultFont", 14, "bold"),
                     bg=BG_SECTION, fg=FG_WHITE).pack(side="right")
            metric_vars[var_key] = var
        self.service_vars[key] = {"error": tk.StringVar(value=""), **metric_vars}
        self.service_frames[key] = parent
        self._setup_panel_click(key)

    def _build_cerebras_panel(self, container: tk.Frame) -> None:
        """Cerebras 用パネル（Total requests/tokens/input/output 表示）を構築する"""
        key = "cerebras"
        parent = tk.Frame(container, bg=BG_SECTION, padx=15, pady=10)
        parent.pack(fill="x", pady=8)
        self.service_parent_frames[key] = parent

        title_row = tk.Frame(parent, bg=BG_SECTION)
        title_row.pack(fill="x", pady=(0, 8))
        tk.Label(title_row, text="Cerebras", font=("TkDefaultFont", 16, "bold"),
                 bg=BG_SECTION, fg=FG_WHITE).pack(side="left")
        status_lbl = tk.Label(title_row, text="Not logged in",
                              font=("TkDefaultFont", 11), bg=BG_SECTION, fg="#666666")
        status_lbl.pack(side="left", padx=(12, 0))
        self.service_status_labels[key] = status_lbl
        self.service_logged_in[key] = False

        metric_vars: dict[str, tk.StringVar] = {}
        for label_text, var_key in (
            ("Total Requests", "total_requests"),
            ("Total Tokens", "total_tokens"),
            ("Input Tokens", "input_tokens"),
            ("Output Tokens", "output_tokens"),
        ):
            var = tk.StringVar(value="--")
            row = tk.Frame(parent, bg=BG_SECTION)
            row.pack(fill="x", pady=3)
            tk.Label(row, text=label_text, font=("TkDefaultFont", 13),
                     bg=BG_SECTION, fg=FG_GRAY, width=15, anchor="w").pack(side="left")
            tk.Label(row, textvariable=var, font=("TkDefaultFont", 14, "bold"),
                     bg=BG_SECTION, fg=FG_WHITE).pack(side="right")
            metric_vars[var_key] = var
        self.service_vars[key] = {"error": tk.StringVar(value=""), **metric_vars}
        self.service_frames[key] = parent
        self._setup_panel_click(key)

    def _build_sambanova_panel(self, container: tk.Frame) -> None:
        """SambaNova 用パネル（Input/Output Tokens 表示）を構築する"""
        key = "sambanova"
        parent = tk.Frame(container, bg=BG_SECTION, padx=15, pady=10)
        parent.pack(fill="x", pady=8)
        self.service_parent_frames[key] = parent

        title_row = tk.Frame(parent, bg=BG_SECTION)
        title_row.pack(fill="x", pady=(0, 8))
        tk.Label(title_row, text="SambaNova", font=("TkDefaultFont", 16, "bold"),
                 bg=BG_SECTION, fg=FG_WHITE).pack(side="left")
        status_lbl = tk.Label(title_row, text="Not logged in",
                              font=("TkDefaultFont", 11), bg=BG_SECTION, fg="#666666")
        status_lbl.pack(side="left", padx=(12, 0))
        self.service_status_labels[key] = status_lbl
        self.service_logged_in[key] = False

        metric_vars: dict[str, tk.StringVar] = {}
        for label_text, var_key in (
            ("Input Tokens (30d)", "input_tokens"),
            ("Output Tokens (30d)", "output_tokens"),
        ):
            var = tk.StringVar(value="--")
            row = tk.Frame(parent, bg=BG_SECTION)
            row.pack(fill="x", pady=3)
            tk.Label(row, text=label_text, font=("TkDefaultFont", 13),
                     bg=BG_SECTION, fg=FG_GRAY, width=15, anchor="w").pack(side="left")
            tk.Label(row, textvariable=var, font=("TkDefaultFont", 14, "bold"),
                     bg=BG_SECTION, fg=FG_WHITE).pack(side="right")
            metric_vars[var_key] = var
        self.service_vars[key] = {"error": tk.StringVar(value=""), **metric_vars}
        self.service_frames[key] = parent
        self._setup_panel_click(key)

    def _set_status(self, key: str, text: str, color: str) -> None:
        """サービスパネルのステータスラベルのテキストと色を更新する"""
        lbl = self.service_status_labels.get(key)
        if lbl:
            lbl.config(text=text, fg=color)

    def _setup_panel_click(self, key: str) -> None:
        """パネルクリック時の動作を設定する（未ログイン→ログイン、ログイン済み→ブラウザ表示）"""
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
        error_msg = None
        data = None
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
        except Exception as exc:
            logging.error(f"[{key}] Login failed: {exc}", exc_info=True)
            error_msg = str(exc)
        finally:
            # 成功・失敗に関わらず、必ず _after_service_login を呼び出す
            self.root.after(0, lambda: self._after_service_login(key, data, error_msg))

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
            if data:
                self._dispatch_display_update(key, data)
        except Exception as exc:
            logging.error(f"[{key}] Display update failed: {exc}", exc_info=True)

    def refresh(self) -> None:
        """全ログイン済みサービスのデータを手動または自動で更新する"""
        if self._refresh_thread and self._refresh_thread.is_alive():
            return
        self.status_var.set("Refreshing...")
        for vars_dict in self.service_vars.values():
            if "error" in vars_dict:
                vars_dict["error"].set("")
        self._refresh_thread = threading.Thread(target=self._refresh_worker, daemon=True)
        self._refresh_thread.start()

    def _refresh_worker(self) -> None:
        """別スレッドでスクレイピングを実行し、結果をUIスレッドに渡す"""
        try:
            results, errors = asyncio.run(self._fetch_all())
        except Exception as exc:  # pragma: no cover
            logging.error(f"Refresh failed: {exc}", exc_info=True)
            results = {}
            errors = {"_global": str(exc)}
        self.root.after(0, lambda: self._apply_results(results, errors))

    async def _fetch_all(self) -> tuple[dict[str, Any], dict[str, str]]:
        """ログイン済みの全サービスを並列スクレイピングし、結果とエラーを返す"""
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
        """スクレイピング結果をUIに反映し、次回自動更新をスケジュールする"""
        # セッション切れエラーをサービス別にチェック
        for svc_key, err in errors.items():
            if "Session expired" in str(err):
                self.service_logged_in[svc_key] = False
                self._set_status(svc_key, "Not logged in", "#666666")
        
        # ログイン中のサービスが1つもなければ Refresh 無効化
        if not any(self.service_logged_in.values()):
            self.refresh_button.config(state="disabled")
            self.status_var.set("Session expired - please login again")
            return
        self.refresh_button.config(state="normal")
        
        if errors:
            self.status_var.set("Error occurred")
        else:
            self.status_var.set("Updated successfully")

        # エラーのあるサービスのエラー表示
        for svc_key, err in errors.items():
            if svc_key.startswith("windsurf_") or svc_key == "_global":
                continue
            vars_dict = self.service_vars.get(svc_key)
            if vars_dict:
                vars_dict["error"].set(f"Error: {err[:40]}")

        # 成功したサービスのデータ反映
        for svc_key, data in results.items():
            if data:
                self._dispatch_display_update(svc_key, data)

        # ログイン済みのサービスがある場合のみ自動更新を継続
        if any(self.service_logged_in.values()):
            self.root.after(self.refresh_interval * 1000, self.refresh)

    def _dispatch_display_update(self, key: str, data: Any) -> None:
        """サービスに応じた表示更新メソッドにディスパッチする"""
        if key == "windsurf":
            self._update_windsurf_display(data)
        elif key == "openrouter":
            self._update_openrouter_display(key, data, self.service_vars[key])
        elif key == "groq":
            self._update_groq_display(data)
        elif key == "cerebras":
            self._update_cerebras_display(data)
        elif key == "sambanova":
            self._update_sambanova_display(data)

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

    def _update_windsurf_quota(self, quota_type: str, data: dict) -> None:
        """Windsurf の daily/weekly 各クォータ行を更新し、閾値で背景色を変える"""
        percent = data.get("percent", 0)
        vars_ = self.service_vars[f"windsurf_{quota_type}"]
        vars_["error"].set("")
        vars_["percent"].set(f"{percent}%")
        vars_["reset"].set(data.get("reset", "--"))
        threshold = self.thresholds.get(f"windsurf_{quota_type}", 30)
        self.service_frames[f"windsurf_{quota_type}"].config(
            bg=BG_WARN if percent <= threshold else BG_SECTION
        )

    def _update_windsurf_display(self, data: dict[str, Any]) -> None:
        """Windsurf の全クォータ（daily/weekly）表示を更新する"""
        for quota_type in ("daily", "weekly"):
            if quota_data := data.get(quota_type):
                self._update_windsurf_quota(quota_type, quota_data)

    def _update_groq_display(self, data: dict[str, Any]) -> None:
        """Groq の Requests/Tokens 表示を更新する"""
        vars_dict = self.service_vars.get("groq", {})
        if not data:
            vars_dict.get("requests", tk.StringVar()).set("No data")
            vars_dict.get("tokens", tk.StringVar()).set("No data")
            return
        total_req = data.get("total_requests", 0)
        total_tok = data.get("total_tokens", 0)
        vars_dict.get("requests", tk.StringVar()).set(f"{total_req:,}")
        vars_dict.get("tokens", tk.StringVar()).set(f"{total_tok:,}")

    def _update_cerebras_display(self, data: dict[str, Any]) -> None:
        """Cerebras の Total requests/tokens/input/output 表示を更新する"""
        vars_dict = self.service_vars.get("cerebras", {})
        if not data:
            for vk in ("total_requests", "total_tokens", "input_tokens", "output_tokens"):
                vars_dict.get(vk, tk.StringVar()).set("No data")
            return
        for vk in ("total_requests", "total_tokens", "input_tokens", "output_tokens"):
            val = data.get(vk)
            if val is not None:
                vars_dict.get(vk, tk.StringVar()).set(f"{val:,}")
            else:
                vars_dict.get(vk, tk.StringVar()).set("--")

    def _update_sambanova_display(self, data: dict[str, Any]) -> None:
        """SambaNova の Input/Output Tokens 表示を更新する"""
        vars_dict = self.service_vars.get("sambanova", {})
        if not data:
            vars_dict.get("input_tokens", tk.StringVar()).set("No data")
            vars_dict.get("output_tokens", tk.StringVar()).set("No data")
            return
        for vk in ("input_tokens", "output_tokens"):
            val = data.get(vk)
            if val is not None:
                vars_dict.get(vk, tk.StringVar()).set(f"{val:,}")
            else:
                vars_dict.get(vk, tk.StringVar()).set("--")

    def open_settings(self) -> None:
        """設定ダイアログを開く"""
        dialog = tk.Toplevel(self.root)
        dialog.title("Settings")
        dialog.geometry(self.config.get("settings_size", "540x460"))
        dialog.resizable(True, True)
        dialog.config(bg=BG_DARK)

        def on_dialog_close():
            self.config["settings_size"] = dialog.geometry().split("+")[0]
            save_config(self.config)
            dialog.destroy()

        dialog.protocol("WM_DELETE_WINDOW", on_dialog_close)
        
        grip = ttk.Sizegrip(dialog)
        grip.place(relx=1.0, rely=1.0, anchor="se")

        frame = tk.Frame(dialog, bg=BG_DARK, padx=20, pady=20)
        frame.pack(fill="both", expand=True)
        frame.columnconfigure(0, weight=1)
        frame.columnconfigure(1, weight=1)
        
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
        for key in ["windsurf", "openrouter", "groq", "cerebras", "sambanova"]:
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
            self.config["settings_size"] = dialog.geometry().split("+")[0]
            
            for key, var in service_vars.items():
                if key not in self.config["services"]:
                    # 新規プロバイダーの場合、デフォルト設定を追加
                    default_urls = {
                        "windsurf": "https://windsurf.com/subscription/usage",
                        "openrouter": "https://openrouter.ai/activity",
                        "groq": "https://console.groq.com/dashboard/usage?tab=activity",
                        "cerebras": "https://cloud.cerebras.ai/",
                        "sambanova": "https://cloud.sambanova.ai/plans/usage",
                    }
                    self.config["services"][key] = {"enabled": True, "url": default_urls.get(key, "")}
                self.config["services"][key]["enabled"] = var.get()
            
            save_config(self.config)
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
        config["window_size"] = root.geometry().split("+")[0]
        save_config(config)
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
