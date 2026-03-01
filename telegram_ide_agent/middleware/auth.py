"""
TEAM_001: Authentication middleware.
Blocks all messages from users not in the whitelist.
"""

import logging
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import Message, CallbackQuery, TelegramObject

logger = logging.getLogger(__name__)


class AuthMiddleware(BaseMiddleware):
    """Reject messages from unauthorized Telegram users."""

    def __init__(self, allowed_user_ids: set[int]) -> None:
        self.allowed_user_ids = allowed_user_ids

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        # Extract user ID from the event
        user_id: int | None = None
        if isinstance(event, Message) and event.from_user:
            user_id = event.from_user.id
        elif isinstance(event, CallbackQuery) and event.from_user:
            user_id = event.from_user.id

        if user_id is None:
            logger.warning("Received event with no user context — blocking.")
            return None

        if user_id not in self.allowed_user_ids:
            logger.warning(
                "Unauthorized access attempt from user_id=%d", user_id
            )
            if isinstance(event, Message):
                await event.answer(
                    "⛔ Access denied. You are not authorized to use this bot."
                )
            elif isinstance(event, CallbackQuery):
                await event.answer(
                    "⛔ Access denied.", show_alert=True
                )
            return None

        return await handler(event, data)
