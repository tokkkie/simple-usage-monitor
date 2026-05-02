"""OpenRouter 利用状況スクレイパー。"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from playwright.async_api import Page

from .base import BaseScraper, ScraperConfig


class OpenRouterScraper(BaseScraper):
    """OpenRouter の requests/tokens メトリクス（1h/1d）を取得するスクレイパー。"""

    def __init__(self, session_dir: Path, headless: bool = False, prompt_login: bool = False) -> None:
        """セッションディレクトリと起動オプションを受け取り初期化する。"""
        super().__init__(
            ScraperConfig(
                name="OpenRouter",
                url="https://openrouter.ai/activity",
                session_dir=session_dir,
                headless=headless,
            ),
            prompt_login=prompt_login,
        )

    async def scrape(self, page: Page) -> Any:
        """期間ドロップダウンを操作して1h/1d の requests/tokens を取得して返す。"""
        # ページは既に _ensure_login() で読み込み済み
        await page.wait_for_timeout(2000)  # SPAの描画待ち
        
        # 現在のドロップダウンボタンのテキストを取得
        current_period = await self._get_current_period(page)
        if not current_period:
            # デバッグ用: 全ボタンのテキストを出力
            buttons = await page.query_selector_all("button")
            button_texts = []
            for btn in buttons:
                try:
                    text = (await btn.inner_text()).strip()
                    if text:
                        button_texts.append(text)
                except Exception:
                    pass
            raise RuntimeError(
                f"[{self.config.name}] ドロップダウンボタンが見つかりません。"
                f"検出されたボタン: {', '.join(button_texts[:10])}"
            )
        
        # 1 Hour データを取得（現在の期間から切り替え）
        if current_period != "1 Hour":
            content_1h = await self._capture_period(page, "1 Hour", current_period)
            current_period = "1 Hour"
        else:
            content_1h = await page.inner_text("body")
        
        # 1 Day データを取得
        if current_period != "1 Day":
            content_1d = await self._capture_period(page, "1 Day", current_period)
        else:
            content_1d = await page.inner_text("body")
        
        return {
            "1h": self._parse_metrics(content_1h),
            "1d": self._parse_metrics(content_1d),
        }

    async def _is_authenticated(self, page: Page) -> bool:
        """使用量ダッシュボードのテキストが存在するかでログイン済みを判定する。"""
        return "Your usage across models" in (await page.inner_text("body"))

    async def _capture_period(self, page: Page, target: str, current: str) -> str:
        """ドロップダウンで期間を target に切り替え、更新後のページ本文を返す。"""
        dropdown_button = await self._find_dropdown_button(page, current)
        if dropdown_button is None:
            raise RuntimeError(f"[{self.config.name}] Failed to find dropdown button: {current}")
        await dropdown_button.click()
        await page.wait_for_timeout(500)

        menu_item_selectors = [
            f'text="{target}"',
            f"button:has-text(\"{target}\")",
            f"[role='option']:has-text(\"{target}\")",
        ]
        clicked = False
        for selector in menu_item_selectors:
            try:
                await page.click(selector, timeout=3000)
                clicked = True
                break
            except Exception:
                continue
        if not clicked:
            raise RuntimeError(f"[{self.config.name}] Failed to select menu item: {target}")
        await page.wait_for_timeout(1000)
        return await page.inner_text("body")

    async def _get_current_period(self, page: Page) -> str | None:
        """現在ドロップダウンで選択されている期間ラベルを返す。"""
        buttons = await page.query_selector_all("button")
        period_candidates = ["1 Hour", "1 Day", "1 Week", "1 Month", "All Time"]
        for btn in buttons:
            try:
                text = (await btn.inner_text()).strip()
            except Exception:
                continue
            if text in period_candidates:
                return text
        return None

    async def _find_dropdown_button(self, page: Page, current: str):
        """ページ内のボタンから指定ラベルのドロップダウンボタンを探して返す。"""
        buttons = await page.query_selector_all("button")
        for btn in buttons:
            try:
                text = (await btn.inner_text()).strip()
            except Exception:
                continue
            if text == current:
                return btn
        return None

    def _parse_metrics(self, content: str) -> dict[str, Any | None]:
        """ページ本文から requests/tokens の値を抽出して返す。"""
        lines = content.split("\n")
        return {
            "requests": self._extract_metric(lines, "Requests"),
            "tokens": self._extract_metric(lines, "Tokens"),
        }

    def _extract_metric(self, lines: list[str], name: str) -> str | None:
        """メトリクス名の次の行から数値（K/M小数記法対応）を抽出して返す。"""
        idx = self._find_line_index(lines, name)
        if idx is None or idx + 1 >= len(lines):
            return None
        match = re.search(r"([\d.]+)([KM]?)", lines[idx + 1])
        return match.group(0) if match else None

    def _find_line_index(self, lines: list[str], pattern: str) -> int | None:
        """行リストから指定文字列を含む行のインデックスを返す。"""
        for i, line in enumerate(lines):
            if pattern in line:
                return i
        return None
