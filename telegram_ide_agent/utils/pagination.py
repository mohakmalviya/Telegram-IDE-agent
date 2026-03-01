"""
TEAM_001: Pagination utility for long content.
Provides inline keyboard navigation for paginated content.
"""

import math
from dataclasses import dataclass

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


@dataclass
class Page:
    """A single page of paginated content."""

    content: str
    page_number: int
    total_pages: int


class Paginator:
    """Split content into pages and generate navigation keyboards."""

    def __init__(self, items: list[str], items_per_page: int = 20) -> None:
        self.items = items
        self.items_per_page = items_per_page
        self.total_pages = max(1, math.ceil(len(items) / items_per_page))

    def get_page(self, page: int) -> Page:
        """Get a specific page (1-indexed).

        Args:
            page: Page number, clamped to valid range.

        Returns:
            A Page with content and metadata.
        """
        page = max(1, min(page, self.total_pages))
        start = (page - 1) * self.items_per_page
        end = start + self.items_per_page
        content = "\n".join(self.items[start:end])
        return Page(content=content, page_number=page, total_pages=self.total_pages)

    @staticmethod
    def build_keyboard(
        page: int,
        total_pages: int,
        callback_prefix: str,
    ) -> InlineKeyboardMarkup | None:
        """Build pagination inline keyboard.

        Args:
            page: Current page number (1-indexed).
            total_pages: Total number of pages.
            callback_prefix: Prefix for callback data (e.g., "ls").

        Returns:
            InlineKeyboardMarkup or None if only 1 page.
        """
        if total_pages <= 1:
            return None

        buttons: list[InlineKeyboardButton] = []

        if page > 1:
            buttons.append(
                InlineKeyboardButton(
                    text="⬅️ Prev",
                    callback_data=f"{callback_prefix}:page:{page - 1}",
                )
            )

        buttons.append(
            InlineKeyboardButton(
                text=f"📄 {page}/{total_pages}",
                callback_data="noop",
            )
        )

        if page < total_pages:
            buttons.append(
                InlineKeyboardButton(
                    text="Next ➡️",
                    callback_data=f"{callback_prefix}:page:{page + 1}",
                )
            )

        return InlineKeyboardMarkup(inline_keyboard=[buttons])
