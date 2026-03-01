"""
TEAM_001: Terminal command handlers.
Handles /run, /git, /pip, /npm.
"""

from aiogram import Router
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command

from telegram_ide_agent.services.executor import Executor
from telegram_ide_agent.services.file_manager import FileManager
from telegram_ide_agent.utils.formatting import escape_md, code_block, truncate

router = Router(name="terminal")

# Store pending dangerous commands: user_id -> command string
_pending_commands: dict[int, str] = {}


@router.message(Command("run"))
async def cmd_run(
    message: Message, executor: Executor, file_manager: FileManager, user_cwd: dict
) -> None:
    """Execute a shell command."""
    args = (message.text or "").split(maxsplit=1)
    if len(args) < 2:
        await message.answer("Usage: `/run <command>`", parse_mode="MarkdownV2")
        return

    command = args[1]
    user_id = message.from_user.id
    cwd = user_cwd.get(user_id, file_manager.workspace_root)

    # Safety check
    if executor.is_dangerous(command):
        _pending_commands[user_id] = command
        keyboard = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="⚠️ Run anyway", callback_data="run:confirm"),
            InlineKeyboardButton(text="❌ Cancel", callback_data="run:cancel"),
        ]])
        await message.answer(
            f"⚠️ *Dangerous command detected:*\n`{escape_md(command)}`\n\nAre you sure?",
            parse_mode="MarkdownV2",
            reply_markup=keyboard,
        )
        return

    await _execute_and_reply(message, executor, command, cwd)


@router.callback_query(lambda c: c.data == "run:confirm")
async def cb_run_confirm(
    callback: CallbackQuery, executor: Executor, file_manager: FileManager, user_cwd: dict
) -> None:
    """Execute a previously confirmed dangerous command."""
    user_id = callback.from_user.id
    command = _pending_commands.pop(user_id, None)

    if not command:
        await callback.message.edit_text("❌ No pending command\\.", parse_mode="MarkdownV2")
        await callback.answer()
        return

    cwd = user_cwd.get(user_id, file_manager.workspace_root)
    await callback.message.edit_text(f"⏳ Running: `{escape_md(command)}`", parse_mode="MarkdownV2")
    result = await executor.run(command, cwd)

    status = "✅" if result.success else "❌"
    output = truncate(result.output, 3500)
    await callback.message.edit_text(
        f"{status} `{escape_md(command)}`\n\n{code_block(output)}",
        parse_mode="MarkdownV2",
    )
    await callback.answer()


@router.callback_query(lambda c: c.data == "run:cancel")
async def cb_run_cancel(callback: CallbackQuery) -> None:
    """Cancel a dangerous command."""
    user_id = callback.from_user.id
    _pending_commands.pop(user_id, None)
    await callback.message.edit_text("✅ Command cancelled\\.", parse_mode="MarkdownV2")
    await callback.answer()


@router.message(Command("git"))
async def cmd_git(
    message: Message, executor: Executor, file_manager: FileManager, user_cwd: dict
) -> None:
    """Git shortcut."""
    args = (message.text or "").split(maxsplit=1)
    git_args = args[1] if len(args) > 1 else "status"
    command = f"git {git_args}"

    user_id = message.from_user.id
    cwd = user_cwd.get(user_id, file_manager.workspace_root)
    await _execute_and_reply(message, executor, command, cwd)


@router.message(Command("pip"))
async def cmd_pip(
    message: Message, executor: Executor, file_manager: FileManager, user_cwd: dict
) -> None:
    """Pip shortcut."""
    args = (message.text or "").split(maxsplit=1)
    if len(args) < 2:
        await message.answer("Usage: `/pip <args>`", parse_mode="MarkdownV2")
        return

    command = f"pip {args[1]}"
    user_id = message.from_user.id
    cwd = user_cwd.get(user_id, file_manager.workspace_root)
    await _execute_and_reply(message, executor, command, cwd)


@router.message(Command("npm"))
async def cmd_npm(
    message: Message, executor: Executor, file_manager: FileManager, user_cwd: dict
) -> None:
    """NPM shortcut."""
    args = (message.text or "").split(maxsplit=1)
    if len(args) < 2:
        await message.answer("Usage: `/npm <args>`", parse_mode="MarkdownV2")
        return

    command = f"npm {args[1]}"
    user_id = message.from_user.id
    cwd = user_cwd.get(user_id, file_manager.workspace_root)
    await _execute_and_reply(message, executor, command, cwd)


async def _execute_and_reply(message: Message, executor: Executor, command: str, cwd) -> None:
    """Execute a command and send the result."""
    status_msg = await message.answer(f"⏳ Running: `{escape_md(command)}`", parse_mode="MarkdownV2")

    result = await executor.run(command, cwd)

    status = "✅" if result.success else "❌"
    output = truncate(result.output, 3500)

    try:
        await status_msg.edit_text(
            f"{status} `{escape_md(command)}`\n\n{code_block(output)}",
            parse_mode="MarkdownV2",
        )
    except Exception:
        # Fallback without markdown if formatting fails
        await status_msg.edit_text(
            f"{status} {command}\n\n{truncate(result.output, 3800)}"
        )
