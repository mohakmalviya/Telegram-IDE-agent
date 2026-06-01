"""
TEAM_001: Configuration loader for Telegram IDE Agent.
Loads environment variables and exposes a typed config object.
"""

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


@dataclass(frozen=True)
class Config:
    """Immutable application configuration loaded from environment."""

    bot_token: str
    allowed_user_ids: set[int]
    workspace_root: Path
    command_timeout: int

    # CDP (Chrome DevTools Protocol) settings
    cdp_port: int | None  # None = auto-scan default ports
    ide_profile: str  # antigravity, cursor, vscode, windsurf
    response_timeout: int  # seconds to wait for AI response


def load_config(env_path: str | None = None) -> Config:
    """Load configuration from .env file and environment variables.

    Args:
        env_path: Optional path to .env file. Defaults to project root.

    Returns:
        A frozen Config dataclass.

    Raises:
        ValueError: If required config is missing.
    """
    if env_path:
        load_dotenv(env_path)
    else:
        project_root = Path(__file__).resolve().parent.parent
        load_dotenv(project_root / ".env")

    bot_token = os.getenv("BOT_TOKEN", "").strip()
    if not bot_token:
        raise ValueError("BOT_TOKEN is required. Set it in .env or environment.")

    raw_ids = os.getenv("ALLOWED_USER_IDS", "").strip()
    if not raw_ids:
        raise ValueError("ALLOWED_USER_IDS is required. Set at least one Telegram user ID.")
    try:
        allowed_user_ids = {int(uid.strip()) for uid in raw_ids.split(",") if uid.strip()}
    except ValueError as exc:
        raise ValueError(
            "ALLOWED_USER_IDS must be a comma-separated list of numeric Telegram user IDs."
        ) from exc

    workspace_root = Path(os.getenv("WORKSPACE_ROOT", "/home/user/projects")).resolve()

    cdp_port_str = os.getenv("CDP_PORT", "").strip()
    try:
        cdp_port = int(cdp_port_str) if cdp_port_str else None
    except ValueError as exc:
        raise ValueError("CDP_PORT must be empty or a numeric TCP port.") from exc

    return Config(
        bot_token=bot_token,
        allowed_user_ids=allowed_user_ids,
        workspace_root=workspace_root,
        command_timeout=int(os.getenv("COMMAND_TIMEOUT", "60")),
        cdp_port=cdp_port,
        ide_profile=os.getenv("IDE_PROFILE", "antigravity").strip().lower(),
        response_timeout=int(os.getenv("RESPONSE_TIMEOUT", "120")),
    )
