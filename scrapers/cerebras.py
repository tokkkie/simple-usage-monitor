"""Cerebras 利用状況スクレイパー。"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from playwright.async_api import Page

from .base import BaseScraper, ScraperConfig


class CerebrasScraper(BaseScraper):
    """Cerebras の Total requests/tokens/input/output を取得するスクレイパー。"""

    def __init__(self, session_dir: Path, headless: bool = False, prompt_login: bool = False) -> None:
        """セッションディレクトリと起動オプションを受け取り初期化する。"""
        super().__init__(
            ScraperConfig(
                name="Cerebras",
                url="https://cloud.cerebras.ai/",
                session_dir=session_dir,
                headless=headless,
            ),
            prompt_login=prompt_login,
        )
        self._org_id: str | None = None

    async def _is_authenticated(self, page: Page) -> bool:
        """ログイン後のダッシュボードにリダイレクトされたかで判定する。"""
        try:
            url = page.url
            # /platform/{org_id}/ パスにリダイレクトされていれば認証済み
            if "/platform/" in url:
                org_match = re.search(r"/platform/(org_[a-z0-9]+)/", url)
                if org_match:
                    self._org_id = org_match.group(1)
                return True
            content = await page.inner_text("body")
            return "Total requests" in content or "Analytics" in content
        except Exception:
            return False

    async def scrape(self, page: Page) -> Any:
        """analytics/usage ページに遷移してメトリクスをパースして返す。"""
        # org_id を取得（URLから）
        if not self._org_id:
            org_match = re.search(r"/platform/(org_[a-z0-9]+)/", page.url)
            if org_match:
                self._org_id = org_match.group(1)

        if not self._org_id:
            raise RuntimeError(
                f"[{self.config.name}] Organization ID が取得できません。"
                "ログイン後のURLに /platform/org_xxx/ が含まれていることを確認してください。"
            )

        # analytics/usage ページに遷移
        usage_url = f"https://cloud.cerebras.ai/platform/{self._org_id}/analytics/usage"
        await page.goto(usage_url, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(5000)  # SPA描画待ち

        content = await page.inner_text("body")
        return self._parse_usage(content)

    def _parse_usage(self, content: str) -> dict[str, Any]:
        """ページテキストから Total requests/tokens/input/output を抽出して返す。"""
        lines = content.split("\n")
        metrics = {}

        target_labels = [
            ("total_requests", "Total requests"),
            ("total_tokens", "Total tokens"),
            ("input_tokens", "Input tokens"),
            ("output_tokens", "Output tokens"),
        ]

        for key, label in target_labels:
            value = self._extract_metric_value(lines, label)
            metrics[key] = value

        return metrics

    def _extract_metric_value(self, lines: list[str], label: str) -> int | None:
        """指定ラベルの直後にある (数値) 形式の値を抽出して返す。"""
        for i, line in enumerate(lines):
            if label in line:
                # 次の行に (数値) がある
                for j in range(i + 1, min(i + 5, len(lines))):
                    match = re.search(r"\(([0-9,]+)\)", lines[j])
                    if match:
                        return int(match.group(1).replace(",", ""))
                # 同じ行に (数値) がある場合
                match = re.search(r"\(([0-9,]+)\)", line)
                if match:
                    return int(match.group(1).replace(",", ""))
                break
        return None
