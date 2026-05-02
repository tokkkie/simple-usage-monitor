"""Base scraper utilities for Playwright-based usage fetchers."""
from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from playwright.async_api import BrowserContext, Page, async_playwright


@dataclass
class ScraperConfig:
    name: str
    url: str
    session_dir: Path
    headless: bool = False


class BaseScraper(ABC):
    """Common Playwright handling shared by all scrapers."""

    def __init__(self, config: ScraperConfig, prompt_login: bool = False) -> None:
        self.config = config
        self.prompt_login = prompt_login
        self.headless = config.headless  # configとは独立して管理

    async def _launch_context(self, playwright) -> BrowserContext:
        return await playwright.chromium.launch_persistent_context(
            user_data_dir=str(self.config.session_dir),
            headless=self.headless,  # self.headlessで制御
            args=[
                "--disable-blink-features=AutomationControlled",
                "--disable-web-security",
                "--disable-dev-shm-usage",
                "--no-sandbox",
            ],
            ignore_default_args=["--enable-automation"],
            ignore_https_errors=True,  # SSL証明書エラーを無視
            user_agent=(
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
        )

    async def _get_page(self, context: BrowserContext) -> Page:
        return context.pages[0] if context.pages else await context.new_page()

    async def _ensure_login(self, context: BrowserContext, page: Page) -> None:
        await page.goto(self.config.url, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(3000)  # SPAの描画完了を待つ
        
        try:
            already_auth = await self._is_authenticated(page)
        except Exception:
            already_auth = False
        if already_auth:
            return
        if not self.prompt_login:
            raise RuntimeError(
                f"[{self.config.name}] Session expired. Please click 'Login' button again."
            )
        
        # ログイン完了を自動検出（最大120秒待機）
        print(f"[{self.config.name}] Waiting for login... (browser window opened)")
        max_wait = 120
        for i in range(max_wait):
            await asyncio.sleep(1)
            try:
                # 最新のページを取得（新しいタブが開かれた場合に対応）
                current_page = context.pages[-1] if context.pages else page
                # 5秒でタイムアウトするように制限
                authenticated = await asyncio.wait_for(
                    self._is_authenticated(current_page),
                    timeout=5.0,
                )
                if authenticated:
                    print(f"[{self.config.name}] Login detected!")
                    # ページ遷移完了を待つ
                    await asyncio.sleep(1)
                    return
            except asyncio.TimeoutError:
                pass  # 認証チェックがタイムアウト→次のループへ
            except Exception as e:
                # ページ遷移中などの一時的エラーをログ出力
                if i % 10 == 0:  # 10秒ごとにログ出力
                    print(f"[{self.config.name}] Waiting... ({i}s)")
        
        raise RuntimeError(f"[{self.config.name}] Login timeout. Please try again.")

    async def run(self) -> Any:
        async with async_playwright() as playwright:
            context = await self._launch_context(playwright)
            try:
                page = await self._get_page(context)
                await self._ensure_login(context, page)
                active_page = context.pages[-1] if context.pages else page
                data = await self.scrape(active_page)
            finally:
                await context.close()
        return data

    @abstractmethod
    async def _is_authenticated(self, page: Page) -> bool:
        """Return True if the target dashboard appears without manual login."""
        raise NotImplementedError

    @abstractmethod
    async def scrape(self, page: Page) -> Any:
        """Return structured data extracted from the page."""
        raise NotImplementedError
