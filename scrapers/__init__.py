"""Scraper package exposing available services."""

from .windsurf import WindsurfScraper
from .openrouter import OpenRouterScraper

__all__ = [
    "WindsurfScraper",
    "OpenRouterScraper",
]
