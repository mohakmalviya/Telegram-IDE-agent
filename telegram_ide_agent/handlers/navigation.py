"""
TEAM_001: Navigation and general command handlers.
Handles /start, /help, /cd, /pwd.
"""

from pathlib import Path

from aiogram import Router, F
from aiogram.types import Message
from aiogram.filters import Command, CommandStart

from telegram_ide_agent.services.file_manager import FileManager, PathSecurityError
from telegram_ide_agent.utils.formatting import escape_md, inline_code

router = Router(name="navigation")

WELCOME_MESSAGE = """
🚀 *Telegram IDE Agent*

Your remote IDE, right in Telegram\\.
Controls your IDE via Chrome DevTools Protocol — no API keys needed\\.

*📂 File Operations*
/files — List files in current directory
/cat `<file>` — Read file content
/edit `<file>` — Edit a file
/touch `<file>` — Create empty file
/mkdir `<dir>` — Create directory
/rm `<path>` — Delete file/directory
/download `<file>` — Download a file
/upload — Upload a file \\(send as document\\)
/search `<query>` — Search in files
/tree — Show directory tree

*🧭 Navigation*
/cd `<path>` — Change directory
/pwd — Print working directory

*💻 Terminal*
/run `<command>` — Execute a shell command
/git `<args>` — Git shortcut
/pip `<args>` — Pip shortcut
/npm `<args>` — NPM shortcut

*🤖 AI Assistant \\(via IDE\\)*
/ai `<prompt>` — Send prompt to IDE's AI
/ai\\_edit `<file>` `<prompt>` — AI edits a file
/ai\\_explain `<file>` — AI explains a file
/model `<name>` — Change AI model (e\\.g\\. claude\\-3\\-5)
/stop — Stop current AI generation

*🔌 IDE Control*
/ide\\_status — Connection status \\& diagnostics
/ide\\_connect — Connect/reconnect to IDE
/ide\\_profile — Show available IDE profiles
/screenshot — Capture IDE screenshot

Type /help for more details\\.
"""

HELP_MESSAGE = """
📖 *Command Reference*

*File Operations:*
• `/files` — List current directory
• `/cat file\\.py` — Show full file
• `/cat file\\.py 10\\-25` — Show lines 10\\-25
• `/edit file\\.py` — Start editing \\(follow prompts\\)
• `/touch newfile\\.py` — Create empty file
• `/mkdir src/utils` — Create directory
• `/rm old\\.py` — Delete \\(asks confirmation\\)
• `/download file\\.py` — Get file as document
• `/upload` — Reply to a document to save it
• `/search TODO` — Find text in files
• `/tree` — Directory tree \\(3 levels deep\\)

*Navigation:*
• `/cd src` — Enter subdirectory
• `/cd \\.\\. ` — Go up one level
• `/cd /absolute/path` — Go to absolute path
• `/pwd` — Show current directory

*Terminal:*
• `/run echo hello` — Run any command
• `/run python main\\.py` — Run scripts
• `/git status` — Git shortcut
• `/git commit \\-m "msg"` — Git commit
• `/pip install flask` — Pip shortcut
• `/npm install` — NPM shortcut

*AI Assistant \\(via IDE\\):*
• `/ai write a Flask hello world` — Sends prompt to your IDE's AI
• `/ai\\_edit app\\.py add error handling` — AI edits file
• `/ai\\_explain utils\\.py` — AI explains code
• `/model gpt\\-4o` — Switch active model
• `/stop` — Stop current generation

*IDE Control:*
• `/ide\\_status` — Check IDE connection \\& chat element detection
• `/ide\\_connect` — Connect or reconnect to IDE
• `/ide\\_profile` — List supported IDEs
• `/screenshot` — Capture IDE window

*How it works:*
💡 Your IDE must be running with `\\-\\-remote\\-debugging\\-port=9222`
💡 The bot connects via Chrome DevTools Protocol \\(CDP\\)
💡 AI responses come from the IDE's own model — zero API cost
💡 Supports: Antigravity, Cursor, VS Code, Windsurf
"""


@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    """Handle /start command."""
    await message.answer(WELCOME_MESSAGE, parse_mode="MarkdownV2")


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    """Handle /help command."""
    await message.answer(HELP_MESSAGE, parse_mode="MarkdownV2")


@router.message(Command("cd"))
async def cmd_cd(message: Message, file_manager: FileManager, user_cwd: dict) -> None:
    """Change working directory."""
    args = (message.text or "").split(maxsplit=1)
    if len(args) < 2:
        await message.answer("Usage: `/cd <path>`", parse_mode="MarkdownV2")
        return

    target = args[1].strip()
    user_id = message.from_user.id

    try:
        current = user_cwd.get(user_id, file_manager.workspace_root)
        new_path = file_manager.resolve(target, current)

        if not new_path.is_dir():
            await message.answer(f"❌ Not a directory: `{escape_md(str(target))}`", parse_mode="MarkdownV2")
            return

        user_cwd[user_id] = new_path
        rel = new_path.relative_to(file_manager.workspace_root)
        display = f"/{rel}" if str(rel) != "." else "/"
        await message.answer(f"📂 Changed to: `{escape_md(display)}`", parse_mode="MarkdownV2")

    except PathSecurityError:
        await message.answer("⛔ Access denied: path is outside the workspace\\.", parse_mode="MarkdownV2")


@router.message(Command("pwd"))
async def cmd_pwd(message: Message, file_manager: FileManager, user_cwd: dict) -> None:
    """Print working directory."""
    user_id = message.from_user.id
    current = user_cwd.get(user_id, file_manager.workspace_root)

    try:
        rel = current.relative_to(file_manager.workspace_root)
        display = f"/{rel}" if str(rel) != "." else "/"
    except ValueError:
        display = str(current)

    await message.answer(f"📂 Current directory: `{escape_md(display)}`", parse_mode="MarkdownV2")
