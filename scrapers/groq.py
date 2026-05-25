"""Groq 利用状況スクレイパー。"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from playwright.async_api import Page

from .base import BaseScraper, ScraperConfig


class GroqScraper(BaseScraper):
    """Groq の月間 requests/tokens メトリクス（API Key 別集計）を取得するスクレイパー。"""

    def __init__(self, session_dir: Path, headless: bool = False, prompt_login: bool = False) -> None:
        """セッションディレクトリと起動オプションを受け取り初期化する。"""
        super().__init__(
            ScraperConfig(
                name="Groq",
                url="https://console.groq.com/dashboard/usage?tab=activity",
                session_dir=session_dir,
                headless=headless,
            ),
            prompt_login=prompt_login,
        )

    async def _is_authenticated(self, page: Page) -> bool:
        """使用量ダッシュボードのテキストが存在するかでログイン済みを判定する。"""
        try:
            url = page.url
            # ログインページでないことを確認
            if "login" in url.lower() or "auth" in url.lower():
                return False
            content = await page.inner_text("body")
            # Groq コンソールの特徴的なテキストで判定
            return ("console.groq.com" in url and 
                    ("Dashboard" in content or "Usage" in content or "API Keys" in content))
        except Exception:
            return False

    async def scrape(self, page: Page) -> Any:
        """Activity タブの Request Count セクションをパースして返す。"""
        # Activity タブに遷移
        await page.goto(self.config.url, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(5000)  # SPA描画待ち

        content = await page.inner_text("body")
        return self._parse_usage(content)

    def _parse_usage(self, content: str) -> dict[str, Any]:
        """ページテキストから API Key 別の requests/tokens を抽出して返す。"""
        lines = content.split("\n")

        # Request Count セクションを探す
        request_count_idx = None
        for i, line in enumerate(lines):
            if "Request Count" in line:
                request_count_idx = i
                break

        api_keys: list[dict[str, Any]] = []
        total_requests = 0
        total_tokens = 0

        if request_count_idx is not None:
            # "API Key" ヘッダーを探す
            api_key_idx = None
            for i in range(request_count_idx, min(request_count_idx + 20, len(lines))):
                if lines[i].strip() == "API Key":
                    api_key_idx = i
                    break

            if api_key_idx is not None:
                # API Key 行をパース（"key_name: request_count" 形式）
                i = api_key_idx + 1
                while i < len(lines):
                    line = lines[i].strip()
                    if not line:
                        i += 1
                        continue
                    # "key_name: count" パターン
                    match = re.match(r"^(.+?):\s*(\d+)$", line)
                    if match:
                        key_name = match.group(1).strip()
                        requests = int(match.group(2))
                        # 次の行がトークン数
                        tokens = 0
                        if i + 1 < len(lines):
                            token_line = lines[i + 1].strip()
                            token_match = re.match(r"^[\d,]+$", token_line)
                            if token_match:
                                tokens = int(token_line.replace(",", ""))
                                i += 1
                        api_keys.append({
                            "name": key_name,
                            "requests": requests,
                            "tokens": tokens,
                        })
                        total_requests += requests
                        total_tokens += tokens
                    else:
                        break
                    i += 1

        return {
            "total_requests": total_requests,
            "total_tokens": total_tokens,
            "api_keys": api_keys,
        }
