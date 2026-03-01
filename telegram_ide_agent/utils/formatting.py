"""
TEAM_001: Telegram message formatting utilities.
Handles code blocks, output truncation, and MarkdownV2 escaping.
"""

import re

# Telegram message size limits
MAX_MESSAGE_LENGTH = 4096
TRUNCATION_SUFFIX = "\n\n... (truncated)"


def escape_md(text: str) -> str:
    """Escape special characters for Telegram MarkdownV2 format.

    Characters that need escaping: _ * [ ] ( ) ~ ` > # + - = | { } . !
    """
    special_chars = r"_*[]()~`>#+-=|{}.!"
    return re.sub(f"([{re.escape(special_chars)}])", r"\\\1", text)


def code_block(text: str, language: str = "") -> str:
    """Wrap text in a Telegram code block (MarkdownV2).

    Args:
        text: The code/text content.
        language: Optional language hint for syntax highlighting.

    Returns:
        Formatted code block string.
    """
    # Inside code blocks, only ` and \ need escaping
    escaped = text.replace("\\", "\\\\").replace("`", "\\`")
    if language:
        return f"```{language}\n{escaped}\n```"
    return f"```\n{escaped}\n```"


def inline_code(text: str) -> str:
    """Wrap text in inline code formatting."""
    escaped = text.replace("\\", "\\\\").replace("`", "\\`")
    return f"`{escaped}`"


def truncate(text: str, max_length: int = MAX_MESSAGE_LENGTH) -> str:
    """Truncate text to fit within Telegram's message limit.

    Preserves complete lines where possible.
    """
    if len(text) <= max_length:
        return text

    cutoff = max_length - len(TRUNCATION_SUFFIX)
    # Try to break at a newline
    last_newline = text.rfind("\n", 0, cutoff)
    if last_newline > cutoff // 2:
        return text[:last_newline] + TRUNCATION_SUFFIX
    return text[:cutoff] + TRUNCATION_SUFFIX


def format_file_list(entries: list[dict]) -> str:
    """Format a list of file/directory entries for display.

    Each entry: {"name": str, "is_dir": bool, "size": int | None}
    """
    if not entries:
        return "📂 Empty directory"

    lines = []
    # Directories first, then files, alphabetically
    dirs = sorted([e for e in entries if e["is_dir"]], key=lambda e: e["name"])
    files = sorted([e for e in entries if not e["is_dir"]], key=lambda e: e["name"])

    for entry in dirs:
        lines.append(f"📁 {escape_md(entry['name'])}/")

    for entry in files:
        size = _human_size(entry.get("size", 0) or 0)
        lines.append(f"📄 {escape_md(entry['name'])}  _{escape_md(size)}_")

    return "\n".join(lines)


def format_tree(tree_lines: list[str]) -> str:
    """Format a directory tree for Telegram display."""
    text = "\n".join(tree_lines)
    return code_block(text)


def _human_size(size_bytes: int) -> str:
    """Convert bytes to human-readable size string."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
    else:
        return f"{size_bytes / (1024 * 1024 * 1024):.1f} GB"
