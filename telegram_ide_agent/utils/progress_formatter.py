"""
TEAM_004: Format structured progress data for Telegram messages.

Layout rules:
- Status header: <pre> block only (terminal box) — NO blockquote
- Files: <blockquote> with <pre> table inside (embed look)
- Commands: <blockquote> with <pre> inside (embed look)
- Progress: plain text with bullets — NO blockquote, NO pre
- Final response: <blockquote expandable> (collapsible)

Telegram HTML constraints:
- Supported: <b>, <i>, <code>, <pre>, <a>, <blockquote>, <u>, <s>
- Max 4096 chars per message
- Must escape <, >, & outside tags
"""

import html


def _esc(text: str) -> str:
    """HTML-escape text for Telegram (escape <, >, &)."""
    return html.escape(str(text), quote=False)


def format_status_header(prompt: str, elapsed_s: float, progress: dict | None) -> str:
    """Build the live-updating status message (Message 1).

    Terminal box using <pre> only — no blockquote wrapper.
    """
    mins, secs = divmod(int(elapsed_s), 60)
    time_str = f"{mins}m {secs}s" if mins else f"{secs}s"

    if progress:
        task = progress.get("taskName") or "..."
        status = progress.get("taskStatus") or "..."
        is_gen = progress.get("isGenerating", False)
        state = "GENERATING" if is_gen else "COMPLETE"
        state_icon = "\u26a1" if is_gen else "\u2705"

        return (
            f"\U0001f916 <b>{_esc(prompt[:80])}</b>\n\n"
            f"<pre>"
            f"\u250c\u2500\u2500 Status \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\n"
            f"\u2502 Step:    {_esc(task[:60])}\n"
            f"\u2502 Mode:    {_esc(status)}\n"
            f"\u2502 State:   {state_icon} {state}\n"
            f"\u2502 Elapsed: {time_str}\n"
            f"\u2514\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500"
            f"</pre>"
        )
    else:
        return (
            f"\U0001f916 <b>{_esc(prompt[:80])}</b>\n\n"
            f"<pre>"
            f"\u23f3 Waiting for IDE response...\n"
            f"\u23f1 Elapsed: {time_str}"
            f"</pre>"
        )


def format_activity_log(progress: dict) -> str:
    """Build the activity log message (Message 2).

    - Files: blockquote embed, plain text entries
    - Progress: plain text with bullets
    """
    blocks = []

    # ── Files section — blockquote embed, plain text ──
    files = progress.get("files", [])
    if files:
        lines = []
        lines.append("<blockquote>\U0001f4c2 <b>Files</b>")
        for f in files[-12:]:
            action = f.get("action", "?")
            name = f.get("name", "?")
            added = f.get("added", 0)
            removed = f.get("removed", 0)

            entry = f"{_esc(action)}  {_esc(name)}"
            if added or removed:
                entry += f"  +{added} -{removed}"
            lines.append(entry)
        lines.append("</blockquote>")
        blocks.append("\n".join(lines))

    # ── Progress section — plain text, NO embed ──
    activity = progress.get("activityLogs", [])
    if activity:
        lines = ["\U0001f4ac <b>Progress</b>"]
        for a in activity[-6:]:
            lines.append(f"  \u2022 {_esc(a[:100])}")
        blocks.append("\n".join(lines))

    if not blocks:
        return "\u23f3 <i>Waiting for activity...</i>"

    return "\n\n".join(blocks)


def format_final_response(response_text: str) -> str:
    """Format the final AI response (Message 3).

    The response_text may contain Telegram HTML from html_to_telegram.
    We strip tags and escape so it fits safely inside a blockquote.
    """
    import re

    header = "\U0001f4ac <b>AI Response</b>\n"

    # Strip any HTML tags from the converted response to get clean text
    clean = re.sub(r"<[^>]+>", "", response_text)
    clean = html.unescape(clean)  # Decode &lt; &gt; etc back
    clean = clean.strip()

    max_body = 4096 - len(header) - 100
    body = _esc(clean[:max_body])
    if len(clean) > max_body:
        body += "\n\n<i>... (truncated)</i>"

    return header + f"<blockquote expandable>{body}</blockquote>"


def format_progress(progress: dict) -> str:
    """Quick smoke test helper."""
    return format_activity_log(progress)
