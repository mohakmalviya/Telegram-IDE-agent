"""
TEAM_001: File operation command handlers.
Handles /files, /cat, /edit, /touch, /mkdir, /rm, /download, /upload, /search, /tree.
"""

import io
from pathlib import Path

from aiogram import Router, F
from aiogram.types import (
    Message,
    CallbackQuery,
    FSInputFile,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from aiogram.filters import Command

from telegram_ide_agent.services.file_manager import FileManager, PathSecurityError
from telegram_ide_agent.utils.formatting import (
    escape_md,
    code_block,
    truncate,
    format_file_list,
    format_tree,
)
from telegram_ide_agent.utils.pagination import Paginator

router = Router(name="files")

# Temporary state for edit flow: user_id -> {file, step, start, end}
_edit_state: dict[int, dict] = {}


# ─── /files (or /ls) ──────────────────────────────────────────────

@router.message(Command("files", "ls"))
async def cmd_files(message: Message, file_manager: FileManager, user_cwd: dict) -> None:
    """List files in the current directory."""
    user_id = message.from_user.id
    cwd = user_cwd.get(user_id, file_manager.workspace_root)

    try:
        entries = await file_manager.list_dir(cwd)
    except PermissionError:
        await message.answer("⛔ Permission denied\\.", parse_mode="MarkdownV2")
        return
    except FileNotFoundError:
        await message.answer("❌ Directory not found\\. Use /cd to navigate\\.", parse_mode="MarkdownV2")
        user_cwd[user_id] = file_manager.workspace_root
        return

    if not entries:
        await message.answer("📂 Empty directory", parse_mode="MarkdownV2")
        return

    # Format entries as display lines
    formatted_lines = []
    dirs = sorted([e for e in entries if e["is_dir"]], key=lambda e: e["name"])
    files = sorted([e for e in entries if not e["is_dir"]], key=lambda e: e["name"])

    for entry in dirs:
        formatted_lines.append(f"📁 {escape_md(entry['name'])}/")
    for entry in files:
        size = _human_size(entry.get("size", 0) or 0)
        formatted_lines.append(f"📄 {escape_md(entry['name'])}  _{escape_md(size)}_")

    paginator = Paginator(formatted_lines, items_per_page=25)
    page = paginator.get_page(1)

    try:
        rel = cwd.relative_to(file_manager.workspace_root)
        title = f"/{rel}" if str(rel) != "." else "/"
    except ValueError:
        title = str(cwd)

    header = f"📂 *{escape_md(title)}*\n\n"
    keyboard = paginator.build_keyboard(page.page_number, page.total_pages, "ls")

    await message.answer(
        header + page.content, parse_mode="MarkdownV2", reply_markup=keyboard
    )


@router.callback_query(F.data.startswith("ls:page:"))
async def cb_files_page(
    callback: CallbackQuery, file_manager: FileManager, user_cwd: dict
) -> None:
    """Handle pagination for /files."""
    page_num = int(callback.data.split(":")[-1])
    user_id = callback.from_user.id
    cwd = user_cwd.get(user_id, file_manager.workspace_root)

    entries = await file_manager.list_dir(cwd)
    formatted_lines = []
    dirs = sorted([e for e in entries if e["is_dir"]], key=lambda e: e["name"])
    files = sorted([e for e in entries if not e["is_dir"]], key=lambda e: e["name"])
    for entry in dirs:
        formatted_lines.append(f"📁 {escape_md(entry['name'])}/")
    for entry in files:
        size = _human_size(entry.get("size", 0) or 0)
        formatted_lines.append(f"📄 {escape_md(entry['name'])}  _{escape_md(size)}_")

    paginator = Paginator(formatted_lines, items_per_page=25)
    page = paginator.get_page(page_num)

    try:
        rel = cwd.relative_to(file_manager.workspace_root)
        title = f"/{rel}" if str(rel) != "." else "/"
    except ValueError:
        title = str(cwd)

    header = f"📂 *{escape_md(title)}*\n\n"
    keyboard = paginator.build_keyboard(page.page_number, page.total_pages, "ls")

    await callback.message.edit_text(
        header + page.content, parse_mode="MarkdownV2", reply_markup=keyboard
    )
    await callback.answer()


# ─── /cat ──────────────────────────────────────────────────────────

@router.message(Command("cat"))
async def cmd_cat(message: Message, file_manager: FileManager, user_cwd: dict) -> None:
    """Read and display file content."""
    user_id = message.from_user.id
    cwd = user_cwd.get(user_id, file_manager.workspace_root)
    args = (message.text or "").split(maxsplit=2)

    if len(args) < 2:
        await message.answer("Usage: `/cat <file>` or `/cat <file> 10\\-25`", parse_mode="MarkdownV2")
        return

    filename = args[1]
    start_line = end_line = None

    # Parse optional line range
    if len(args) >= 3:
        try:
            parts = args[2].split("-")
            start_line = int(parts[0])
            end_line = int(parts[1]) if len(parts) > 1 else start_line
        except (ValueError, IndexError):
            await message.answer("Invalid line range\\. Use: `/cat file 10\\-25`", parse_mode="MarkdownV2")
            return

    try:
        filepath = file_manager.resolve(filename, cwd)
    except PathSecurityError:
        await message.answer("⛔ Access denied: path is outside the workspace\\.", parse_mode="MarkdownV2")
        return

    if not filepath.exists():
        await message.answer(f"❌ File not found: `{escape_md(filename)}`", parse_mode="MarkdownV2")
        return

    if filepath.is_dir():
        await message.answer("❌ That's a directory\\. Use /files to list it\\.", parse_mode="MarkdownV2")
        return

    if file_manager.is_binary(filepath):
        await message.answer("❌ Binary file — use /download instead\\.", parse_mode="MarkdownV2")
        return

    try:
        content = await file_manager.read_file(filepath, start_line, end_line)
    except Exception as e:
        await message.answer(f"❌ Error reading file: {escape_md(str(e))}", parse_mode="MarkdownV2")
        return

    # Determine language for syntax highlighting
    ext = filepath.suffix.lstrip(".")
    lang_map = {
        "py": "python", "js": "javascript", "ts": "typescript", "jsx": "jsx",
        "tsx": "tsx", "rs": "rust", "go": "go", "java": "java", "rb": "ruby",
        "cpp": "cpp", "c": "c", "h": "c", "cs": "csharp", "php": "php",
        "sh": "bash", "bash": "bash", "zsh": "bash", "yml": "yaml", "yaml": "yaml",
        "json": "json", "xml": "xml", "html": "html", "css": "css", "sql": "sql",
        "md": "markdown", "toml": "toml", "ini": "ini", "cfg": "ini",
        "dockerfile": "dockerfile", "tf": "hcl",
    }
    lang = lang_map.get(ext, "")

    header = f"📄 *{escape_md(filename)}*"
    if start_line:
        header += f" \\(lines {start_line}\\-{end_line}\\)"
    header += "\n"

    formatted = code_block(content, lang)
    full = header + formatted

    # If too long, send as document
    if len(full) > 4000:
        # Send first part as message, rest as file
        short_content = truncate(content, 3500)
        await message.answer(header + code_block(short_content, lang), parse_mode="MarkdownV2")
        # Also send full file as document
        buf = io.BytesIO(content.encode("utf-8"))
        buf.name = filepath.name
        from aiogram.types import BufferedInputFile
        doc = BufferedInputFile(content.encode("utf-8"), filename=filepath.name)
        await message.answer_document(doc, caption="📎 Full file content")
    else:
        await message.answer(full, parse_mode="MarkdownV2")


# ─── /edit ─────────────────────────────────────────────────────────

@router.message(Command("edit"))
async def cmd_edit(message: Message, file_manager: FileManager, user_cwd: dict) -> None:
    """Start the file edit flow."""
    user_id = message.from_user.id
    cwd = user_cwd.get(user_id, file_manager.workspace_root)
    args = (message.text or "").split(maxsplit=1)

    if len(args) < 2:
        await message.answer(
            "Usage: `/edit <file>`\n\n"
            "This starts an interactive edit flow:\n"
            "1\\. Bot shows file content\n"
            "2\\. You specify the line range to edit\n"
            "3\\. You send the replacement content\n"
            "4\\. Bot applies the edit",
            parse_mode="MarkdownV2",
        )
        return

    filename = args[1]

    try:
        filepath = file_manager.resolve(filename, cwd)
    except PathSecurityError:
        await message.answer("⛔ Access denied\\.", parse_mode="MarkdownV2")
        return

    if not filepath.exists():
        # Offer to create it
        _edit_state[user_id] = {"file": filepath, "step": "create_new", "filename": filename}
        await message.answer(
            f"📝 File `{escape_md(filename)}` doesn't exist\\.\n"
            "Send the file content to create it, or /cancel to abort\\.",
            parse_mode="MarkdownV2",
        )
        return

    if file_manager.is_binary(filepath):
        await message.answer("❌ Cannot edit binary files\\.", parse_mode="MarkdownV2")
        return

    content = await file_manager.read_file(filepath, start_line=1, end_line=None)
    line_count = len(content.split("\n"))

    _edit_state[user_id] = {"file": filepath, "step": "line_range", "filename": filename}

    ext = filepath.suffix.lstrip(".")
    header = f"📝 *Editing:* `{escape_md(filename)}` \\({line_count} lines\\)\n\n"
    short = truncate(content, 3000)
    await message.answer(
        header + code_block(short) + "\n\n"
        "Send the line range to replace \\(e\\.g\\. `5\\-10`\\)\n"
        "Or send `all` to replace entire file\\.\n"
        "Send /cancel to abort\\.",
        parse_mode="MarkdownV2",
    )


@router.message(Command("cancel"))
async def cmd_cancel(message: Message) -> None:
    """Cancel any in-progress edit."""
    user_id = message.from_user.id
    if user_id in _edit_state:
        del _edit_state[user_id]
        await message.answer("✅ Cancelled\\.", parse_mode="MarkdownV2")
    else:
        await message.answer("Nothing to cancel\\.", parse_mode="MarkdownV2")


# ─── /touch ────────────────────────────────────────────────────────

@router.message(Command("touch"))
async def cmd_touch(message: Message, file_manager: FileManager, user_cwd: dict) -> None:
    """Create an empty file."""
    user_id = message.from_user.id
    cwd = user_cwd.get(user_id, file_manager.workspace_root)
    args = (message.text or "").split(maxsplit=1)

    if len(args) < 2:
        await message.answer("Usage: `/touch <file>`", parse_mode="MarkdownV2")
        return

    try:
        filepath = file_manager.resolve(args[1], cwd)
        await file_manager.create_file(filepath)
        await message.answer(f"✅ Created: `{escape_md(args[1])}`", parse_mode="MarkdownV2")
    except PathSecurityError:
        await message.answer("⛔ Access denied\\.", parse_mode="MarkdownV2")


# ─── /mkdir ────────────────────────────────────────────────────────

@router.message(Command("mkdir"))
async def cmd_mkdir(message: Message, file_manager: FileManager, user_cwd: dict) -> None:
    """Create a directory."""
    user_id = message.from_user.id
    cwd = user_cwd.get(user_id, file_manager.workspace_root)
    args = (message.text or "").split(maxsplit=1)

    if len(args) < 2:
        await message.answer("Usage: `/mkdir <dir>`", parse_mode="MarkdownV2")
        return

    try:
        dirpath = file_manager.resolve(args[1], cwd)
        await file_manager.create_dir(dirpath)
        await message.answer(f"✅ Created directory: `{escape_md(args[1])}`", parse_mode="MarkdownV2")
    except PathSecurityError:
        await message.answer("⛔ Access denied\\.", parse_mode="MarkdownV2")


# ─── /rm ───────────────────────────────────────────────────────────

@router.message(Command("rm"))
async def cmd_rm(message: Message, file_manager: FileManager, user_cwd: dict) -> None:
    """Delete a file or directory (with confirmation)."""
    user_id = message.from_user.id
    cwd = user_cwd.get(user_id, file_manager.workspace_root)
    args = (message.text or "").split(maxsplit=1)

    if len(args) < 2:
        await message.answer("Usage: `/rm <path>`", parse_mode="MarkdownV2")
        return

    target = args[1]

    try:
        filepath = file_manager.resolve(target, cwd)
    except PathSecurityError:
        await message.answer("⛔ Access denied\\.", parse_mode="MarkdownV2")
        return

    if not filepath.exists():
        await message.answer(f"❌ Not found: `{escape_md(target)}`", parse_mode="MarkdownV2")
        return

    kind = "directory" if filepath.is_dir() else "file"
    keyboard = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🗑️ Yes, delete", callback_data=f"rm:confirm:{target}"),
        InlineKeyboardButton(text="❌ Cancel", callback_data="rm:cancel"),
    ]])

    await message.answer(
        f"⚠️ Delete {kind}: `{escape_md(target)}`?",
        parse_mode="MarkdownV2",
        reply_markup=keyboard,
    )


@router.callback_query(F.data.startswith("rm:confirm:"))
async def cb_rm_confirm(
    callback: CallbackQuery, file_manager: FileManager, user_cwd: dict
) -> None:
    """Confirm file deletion."""
    target = callback.data.replace("rm:confirm:", "")
    user_id = callback.from_user.id
    cwd = user_cwd.get(user_id, file_manager.workspace_root)

    try:
        filepath = file_manager.resolve(target, cwd)
        await file_manager.delete(filepath)
        await callback.message.edit_text(f"🗑️ Deleted: `{escape_md(target)}`", parse_mode="MarkdownV2")
    except Exception as e:
        await callback.message.edit_text(f"❌ Error: {escape_md(str(e))}", parse_mode="MarkdownV2")
    await callback.answer()


@router.callback_query(F.data == "rm:cancel")
async def cb_rm_cancel(callback: CallbackQuery) -> None:
    """Cancel file deletion."""
    await callback.message.edit_text("✅ Deletion cancelled\\.", parse_mode="MarkdownV2")
    await callback.answer()


# ─── /download ─────────────────────────────────────────────────────

@router.message(Command("download"))
async def cmd_download(message: Message, file_manager: FileManager, user_cwd: dict) -> None:
    """Send a file as a Telegram document."""
    user_id = message.from_user.id
    cwd = user_cwd.get(user_id, file_manager.workspace_root)
    args = (message.text or "").split(maxsplit=1)

    if len(args) < 2:
        await message.answer("Usage: `/download <file>`", parse_mode="MarkdownV2")
        return

    try:
        filepath = file_manager.resolve(args[1], cwd)
    except PathSecurityError:
        await message.answer("⛔ Access denied\\.", parse_mode="MarkdownV2")
        return

    if not filepath.exists() or filepath.is_dir():
        await message.answer(f"❌ File not found: `{escape_md(args[1])}`", parse_mode="MarkdownV2")
        return

    doc = FSInputFile(filepath)
    await message.answer_document(doc, caption=f"📎 {filepath.name}")


# ─── /upload ───────────────────────────────────────────────────────

@router.message(Command("upload"))
async def cmd_upload(message: Message) -> None:
    """Show upload instructions."""
    await message.answer(
        "📤 To upload a file:\n"
        "Send any file as a document to this chat\\.\n"
        "It will be saved to your current directory\\.",
        parse_mode="MarkdownV2",
    )


@router.message(F.document)
async def handle_document_upload(
    message: Message, file_manager: FileManager, user_cwd: dict
) -> None:
    """Handle incoming document uploads."""
    user_id = message.from_user.id
    cwd = user_cwd.get(user_id, file_manager.workspace_root)
    doc = message.document

    if not doc or not doc.file_name:
        await message.answer("❌ Could not read the uploaded file\\.", parse_mode="MarkdownV2")
        return

    filepath = cwd / doc.file_name

    try:
        # Security check
        file_manager.resolve(doc.file_name, cwd)
    except PathSecurityError:
        await message.answer("⛔ Access denied\\.", parse_mode="MarkdownV2")
        return

    file = await message.bot.download(doc)
    if file:
        filepath.parent.mkdir(parents=True, exist_ok=True)
        with open(filepath, "wb") as f:
            f.write(file.read())
        await message.answer(f"✅ Saved: `{escape_md(doc.file_name)}`", parse_mode="MarkdownV2")
    else:
        await message.answer("❌ Download failed\\.", parse_mode="MarkdownV2")


# ─── /search ───────────────────────────────────────────────────────

@router.message(Command("search"))
async def cmd_search(message: Message, file_manager: FileManager, user_cwd: dict) -> None:
    """Search for text in files."""
    user_id = message.from_user.id
    cwd = user_cwd.get(user_id, file_manager.workspace_root)
    args = (message.text or "").split(maxsplit=1)

    if len(args) < 2:
        await message.answer("Usage: `/search <query>`", parse_mode="MarkdownV2")
        return

    query = args[1]
    await message.answer(f"🔍 Searching for `{escape_md(query)}`\\.\\.\\.", parse_mode="MarkdownV2")

    results = await file_manager.search(cwd, query)

    if not results:
        await message.answer("No matches found\\.", parse_mode="MarkdownV2")
        return

    lines = []
    for r in results[:30]:
        lines.append(f"📄 `{escape_md(r['file'])}` L{r['line']}")
        lines.append(f"   {escape_md(r['content'][:80])}")

    text = "\n".join(lines)
    count_msg = f"Found {len(results)} matches"
    if len(results) >= 50:
        count_msg += " \\(capped at 50\\)"

    await message.answer(
        f"🔍 *Search:* `{escape_md(query)}`\n{escape_md(count_msg)}\n\n{text}",
        parse_mode="MarkdownV2",
    )


# ─── /tree ─────────────────────────────────────────────────────────

@router.message(Command("tree"))
async def cmd_tree(message: Message, file_manager: FileManager, user_cwd: dict) -> None:
    """Show directory tree."""
    user_id = message.from_user.id
    cwd = user_cwd.get(user_id, file_manager.workspace_root)

    try:
        rel = cwd.relative_to(file_manager.workspace_root)
        title = f"/{rel}" if str(rel) != "." else "/"
    except ValueError:
        title = str(cwd)

    tree_lines = [f"📂 {title}"] + file_manager.tree(cwd)

    text = format_tree(tree_lines)
    if len(text) > 4000:
        text = truncate(text, 4000)

    await message.answer(text, parse_mode="MarkdownV2")


# ─── Edit flow message handler ────────────────────────────────────

@router.message(F.text & ~F.text.startswith("/"))
async def handle_edit_flow(message: Message, file_manager: FileManager) -> None:
    """Handle edit flow continuation for users in edit mode."""
    user_id = message.from_user.id

    if user_id not in _edit_state:
        return  # Not in edit mode, ignore

    state = _edit_state[user_id]
    step = state["step"]

    if step == "create_new":
        # User sent content for a new file
        content = message.text
        try:
            await file_manager.write_file(state["file"], content)
            await message.answer(
                f"✅ Created `{escape_md(state['filename'])}` with your content\\.",
                parse_mode="MarkdownV2",
            )
        except Exception as e:
            await message.answer(f"❌ Error: {escape_md(str(e))}", parse_mode="MarkdownV2")
        del _edit_state[user_id]

    elif step == "line_range":
        # User sent line range
        text = message.text.strip().lower()
        if text == "all":
            state["start"] = None
            state["end"] = None
            state["step"] = "content"
            await message.answer(
                "Send the full replacement content\\.\n"
                "Send /cancel to abort\\.",
                parse_mode="MarkdownV2",
            )
        else:
            try:
                parts = text.split("-")
                state["start"] = int(parts[0])
                state["end"] = int(parts[1]) if len(parts) > 1 else int(parts[0])
                state["step"] = "content"
                await message.answer(
                    f"Lines {state['start']}\\-{state['end']} selected\\.\n"
                    "Send the replacement content\\.\n"
                    "Send /cancel to abort\\.",
                    parse_mode="MarkdownV2",
                )
            except (ValueError, IndexError):
                await message.answer(
                    "Invalid range\\. Send like `5\\-10` or `all`\\.",
                    parse_mode="MarkdownV2",
                )

    elif step == "content":
        # User sent replacement content
        content = message.text
        filepath = state["file"]

        try:
            if state.get("start") is None:
                # Replace entire file
                await file_manager.write_file(filepath, content)
            else:
                await file_manager.edit_lines(
                    filepath, state["start"], state["end"], content
                )

            await message.answer(
                f"✅ Updated `{escape_md(state['filename'])}`\\!",
                parse_mode="MarkdownV2",
            )
        except Exception as e:
            await message.answer(f"❌ Error: {escape_md(str(e))}", parse_mode="MarkdownV2")

        del _edit_state[user_id]


# ─── Helpers ───────────────────────────────────────────────────────

def _human_size(size_bytes: int) -> str:
    """Convert bytes to human-readable size string."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
    return f"{size_bytes / (1024 * 1024 * 1024):.1f} GB"
