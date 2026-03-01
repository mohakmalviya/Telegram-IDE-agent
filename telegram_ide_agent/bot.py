"""
TEAM_001: Bot entry point.
Initializes the Telegram bot, connects to the IDE via CDP, and starts polling.
"""

import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties

from telegram_ide_agent.config import load_config
from telegram_ide_agent.middleware.auth import AuthMiddleware
from telegram_ide_agent.services.file_manager import FileManager
from telegram_ide_agent.services.executor import Executor
from telegram_ide_agent.services.cdp_manager import CdpManager
from telegram_ide_agent.services.ide_bridge import IdeBridge
from telegram_ide_agent.services.ai_client import AIClient
from telegram_ide_agent.handlers import navigation, files, terminal, ai_assistant

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


async def main() -> None:
    """Initialize and start the bot."""
    logger.info("Loading configuration...")
    config = load_config()

    # ─── Initialize services ─────────────────────────────────────
    file_manager = FileManager(config.workspace_root)
    executor = Executor(timeout=config.command_timeout)

    # CDP → IDE Bridge → AI Client chain
    cdp = CdpManager(port=config.cdp_port)
    ide_bridge = IdeBridge(
        cdp=cdp,
        profile_name=config.ide_profile,
        response_timeout=config.response_timeout,
    )
    # Per-user working directory state
    user_cwd: dict[int, object] = {}
    ai_client = AIClient(ide_bridge)

    # ─── Initialize bot and dispatcher ───────────────────────────
    bot = Bot(
        token=config.bot_token,
        default=DefaultBotProperties(parse_mode=None),
    )
    dp = Dispatcher()

    # ─── Register middleware ─────────────────────────────────────
    dp.message.middleware(AuthMiddleware(config.allowed_user_ids))
    dp.callback_query.middleware(AuthMiddleware(config.allowed_user_ids))

    # ─── Dependency injection via dispatcher kwargs ──────────────
    dp["file_manager"] = file_manager
    dp["executor"] = executor
    dp["ai_client"] = ai_client
    dp["user_cwd"] = user_cwd

    # ─── Register routers ────────────────────────────────────────
    dp.include_router(navigation.router)
    dp.include_router(files.router)
    dp.include_router(terminal.router)
    dp.include_router(ai_assistant.router)

    # ─── Startup info ────────────────────────────────────────────
    me = await bot.get_me()
    logger.info("Bot started: @%s (%s)", me.username, me.full_name)
    logger.info("Workspace: %s", config.workspace_root)
    logger.info("Allowed users: %s", config.allowed_user_ids)
    logger.info("IDE profile: %s", config.ide_profile)
    logger.info("CDP port: %s", config.cdp_port or "auto-scan")

    # ─── Start polling ───────────────────────────────────────────
    logger.info("Polling for updates...")
    try:
        await dp.start_polling(bot)
    finally:
        await ai_client.disconnect()
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user.")
        sys.exit(0)
