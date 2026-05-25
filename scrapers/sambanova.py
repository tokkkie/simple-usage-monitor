"""SambaNova 利用状況スクレイパー。"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from playwright.async_api import Page

from .base import BaseScraper, ScraperConfig


class SambaNovaScraper(BaseScraper):
    """SambaNova の Input/Output Tokens（直近30日）を取得するスクレイパー。"""

    def __init__(self, session_dir: Path, headless: bool = False, prompt_login: bool = False) -> None:
        """セッションディレクトリと起動オプションを受け取り初期化する。"""
        super().__init__(
            ScraperConfig(
                name="SambaNova",
                url="https://cloud.sambanova.ai/plans/usage",
                session_dir=session_dir,
                headless=headless,
            ),
            prompt_login=prompt_login,
        )

    async def _is_authenticated(self, page: Page) -> bool:
        """ダッシュボードのナビゲーションが表示されているかでログイン済みを判定する。"""
        try:
            url = page.url
            content = await page.inner_text("body")
            # ログインページでなく、ナビゲーションが表示されている
            if "sign in" in content.lower() or "log in" in content.lower():
                return False
            return "cloud.sambanova.ai" in url and ("Usage" in content or "Dashboard" in content)
        except Exception:
            return False

    async def scrape(self, page: Page) -> Any:
        """Usage ページから Input/Output Tokens を取得して返す。

        innerText にはグラフ数値が含まれないため、
        SVG テキスト要素や page.evaluate() で抽出を試みる。
        """
        await page.goto(self.config.url, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(5000)  # SPA描画待ち

        # 方法1: SVG内のテキスト要素からトークン数を取得
        data = await self._extract_from_svg(page)
        if data and (data.get("input_tokens") is not None or data.get("output_tokens") is not None):
            return data

        # 方法2: aria-label やツールチップからデータを取得
        data = await self._extract_from_aria(page)
        if data and (data.get("input_tokens") is not None or data.get("output_tokens") is not None):
            return data

        # 方法3: ページ内の全テキストコンテンツを取得（innerText では取れない部分含む）
        data = await self._extract_from_evaluate(page)
        if data and (data.get("input_tokens") is not None or data.get("output_tokens") is not None):
            return data

        return {"input_tokens": None, "output_tokens": None}

    async def _extract_from_svg(self, page: Page) -> dict[str, int | None]:
        """SVG 内のテキスト要素からトークン数を抽出する。"""
        try:
            result = await page.evaluate("""() => {
                const texts = document.querySelectorAll('svg text, svg tspan');
                const values = [];
                texts.forEach(el => {
                    const text = el.textContent.trim();
                    if (text) values.push(text);
                });
                return values;
            }""")

            input_tokens = None
            output_tokens = None

            if result:
                # "Input Tokens" ラベルの近くにある最大数値を探す
                input_tokens = self._find_token_value(result, "Input Tokens")
                output_tokens = self._find_token_value(result, "Output Tokens")

            return {"input_tokens": input_tokens, "output_tokens": output_tokens}
        except Exception:
            return {"input_tokens": None, "output_tokens": None}

    async def _extract_from_aria(self, page: Page) -> dict[str, int | None]:
        """aria-label 属性からトークン数を抽出する。"""
        try:
            result = await page.evaluate("""() => {
                const elements = document.querySelectorAll('[aria-label]');
                const labels = [];
                elements.forEach(el => labels.push(el.getAttribute('aria-label')));
                return labels;
            }""")

            input_tokens = None
            output_tokens = None

            if result:
                for label in result:
                    if not label:
                        continue
                    label_lower = label.lower()
                    if "input" in label_lower and "token" in label_lower:
                        val = self._parse_number_from_text(label)
                        if val is not None:
                            input_tokens = val
                    elif "output" in label_lower and "token" in label_lower:
                        val = self._parse_number_from_text(label)
                        if val is not None:
                            output_tokens = val

            return {"input_tokens": input_tokens, "output_tokens": output_tokens}
        except Exception:
            return {"input_tokens": None, "output_tokens": None}

    async def _extract_from_evaluate(self, page: Page) -> dict[str, int | None]:
        """textContent を使って全テキストを取得し、トークン数を抽出する。"""
        try:
            result = await page.evaluate("""() => {
                // innerText では取得できない要素も含めて全テキストを取得
                const walker = document.createTreeWalker(
                    document.body,
                    NodeFilter.SHOW_TEXT,
                    null,
                    false
                );
                const texts = [];
                let node;
                while (node = walker.nextNode()) {
                    const text = node.textContent.trim();
                    if (text) texts.push(text);
                }
                return texts;
            }""")

            input_tokens = None
            output_tokens = None

            if result:
                input_tokens = self._find_token_value(result, "Input Tokens")
                output_tokens = self._find_token_value(result, "Output Tokens")

            return {"input_tokens": input_tokens, "output_tokens": output_tokens}
        except Exception:
            return {"input_tokens": None, "output_tokens": None}

    def _find_token_value(self, texts: list[str], label: str) -> int | None:
        """テキストリストから指定ラベルに対応する数値を探して返す。"""
        # ラベルのインデックスを探す
        label_indices = []
        for i, text in enumerate(texts):
            if label.lower() in text.lower():
                label_indices.append(i)

        if not label_indices:
            return None

        # 各ラベルの前後から最大の数値を探す
        max_value = None
        for idx in label_indices:
            # ラベルの前後10要素を検索
            for j in range(max(0, idx - 10), min(len(texts), idx + 10)):
                val = self._parse_number_from_text(texts[j])
                if val is not None and val > 0:
                    if max_value is None or val > max_value:
                        max_value = val

        return max_value

    def _parse_number_from_text(self, text: str) -> int | None:
        """テキストからカンマ区切り数値を抽出して int で返す。"""
        import re
        # "191,423" や "8,713" のようなカンマ区切り数値
        match = re.search(r"([\d,]+)", text)
        if match:
            try:
                value = int(match.group(1).replace(",", ""))
                # 年号（2026等）やタイムスタンプを除外
                if value > 100 or value == 0:
                    return value
            except ValueError:
                pass
        return None
