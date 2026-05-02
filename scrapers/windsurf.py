"""Windsurf 利用状況スクレイパー。"""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Any

from playwright.async_api import Page

from .base import BaseScraper, ScraperConfig


MONTH_MAP = {
    "January": 1,
    "February": 2,
    "March": 3,
    "April": 4,
    "May": 5,
    "June": 6,
    "July": 7,
    "August": 8,
    "September": 9,
    "October": 10,
    "November": 11,
    "December": 12,
}


class WindsurfScraper(BaseScraper):
    """Windsurf の daily/weekly クォータ使用率とリセット時刻を取得するスクレイパー。"""

    def __init__(self, session_dir: Path, headless: bool = False, prompt_login: bool = False) -> None:
        """セッションディレクトリと起動オプションを受け取り初期化する。"""
        super().__init__(
            ScraperConfig(
                name="Windsurf",
                url="https://windsurf.com/subscription/usage",
                session_dir=session_dir,
                headless=headless,
            ),
            prompt_login=prompt_login,
        )

    async def scrape(self, page: Page) -> Any:
        """ページ本文を取得し、daily/weekly クォータデータを解析して返す。"""
        await page.wait_for_timeout(1000)
        content = await page.inner_text("body")
        return self._parse_usage_data(content)

    async def _is_authenticated(self, page: Page) -> bool:
        """使用ページにクォータ情報が表示されているかを確認する。"""
        try:
            url = page.url
            if "subscription/usage" in url:
                content = await page.inner_text("body")
                return "daily quota" in content or "weekly quota" in content
            return False
        except Exception:
            return False

    def _parse_usage_data(self, content: str) -> dict[str, Any]:
        """ページ本文から daily/weekly クォータデータを抽出して返す。"""
        daily = self._extract_quota_with_reset(content, "Your daily quota")
        weekly = self._extract_quota_with_reset(content, "Your weekly quota")
        return {"daily": daily, "weekly": weekly}

    def _extract_quota_with_reset(self, content: str, section_name: str) -> dict[str, Any] | None:
        """指定セクションから残量％とリセット時刻を抽出して返す。"""
        lines = content.split("\n")
        start_idx = self._find_line_index(lines, section_name)
        if start_idx is None:
            return None

        # 次のセクションまでの範囲を限定（他セクションのデータを拾わない）
        end_idx = len(lines)
        for i in range(start_idx + 1, len(lines)):
            if "Your" in lines[i] and "quota" in lines[i] and i != start_idx:
                end_idx = i
                break

        percent = None
        for i in range(start_idx + 1, min(end_idx, start_idx + 15)):
            if "%" in lines[i] and "remaining" in lines[i]:
                match = re.search(r"(\d+(?:\.\d+)?)%", lines[i])
                if match:
                    percent = int(float(match.group(1)))
                    break

        reset = "--"
        reset_match = self._extract_nearby(
            lines,
            start_idx + 1,
            min(15, end_idx - start_idx),
            r"Resets\s+(\w+)\s+(\d+),\s+(\d+:\d+\s*(?:AM|PM))",
        )
        if reset_match and isinstance(reset_match, tuple) and len(reset_match) == 3:
            reset = self._format_relative_time(*reset_match)

        if percent is not None:
            return {"percent": percent, "reset": reset}
        return None

    def _format_relative_time(self, month_str: str, day_str: str, time_str: str) -> str:
        """リセット日時を「resets in Xd Yh」形式の文字列に変換する。"""
        try:
            month = MONTH_MAP.get(month_str, 0)
            day = int(day_str)
            time_match = re.match(r"(\d+):(\d+)\s*(AM|PM)", time_str, re.IGNORECASE)
            if time_match:
                hour = int(time_match.group(1))
                minute = int(time_match.group(2))
                ampm = time_match.group(3).upper()
                if ampm == "PM" and hour != 12:
                    hour += 12
                elif ampm == "AM" and hour == 12:
                    hour = 0
            else:
                hour = minute = 0

            now = datetime.now()
            year = now.year
            reset_dt = datetime(year, month, day, hour, minute)
            if reset_dt < now:
                reset_dt = datetime(year + 1, month, day, hour, minute)

            diff = reset_dt - now
            hours = int(diff.total_seconds() // 3600)
            days = hours // 24
            remaining_hours = hours % 24
            if days > 0:
                return f"resets in {days}d {remaining_hours}h"
            return f"resets in {hours}h"
        except Exception:
            return "--"

    def _find_line_index(self, lines: list[str], pattern: str) -> int | None:
        """行リストから指定文字列を含む行のインデックスを返す。"""
        for idx, line in enumerate(lines):
            if pattern in line:
                return idx
        return None

    def _extract_nearby(self, lines: list[str], start_idx: int, max_offset: int, pattern: str):
        """指定範囲内の行を正規表現で検索し、2グループ以上ならタプル、単一なら文字列で返す。"""
        for i in range(start_idx, min(start_idx + max_offset, len(lines))):
            match = re.search(pattern, lines[i])
            if match:
                groups = match.groups()
                if groups:
                    return groups if len(groups) > 1 else groups[0]
                return match.group(0)
        return None
