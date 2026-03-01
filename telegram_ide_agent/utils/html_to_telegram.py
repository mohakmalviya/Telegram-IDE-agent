"""
HTML-to-Telegram converter.

TEAM_002: Rewritten to output Telegram HTML format instead of raw markdown.
Telegram's HTML parser supports: <b>, <i>, <code>, <pre>, <a>.

Converts Antigravity's innerHTML response to clean Telegram HTML
that displays correctly with parse_mode="HTML".
"""

import re


def html_to_telegram(html: str) -> str:
    """Convert Antigravity HTML response to Telegram HTML format.

    Supported conversions:
    - <style>/<script> → removed entirely
    - <pre><code> → <pre>...</pre> (code blocks)
    - <code> → <code>...</code> (inline code)
    - <h1>-<h3> → <b>HEADING</b> with newlines
    - <strong>/<b> → <b>...</b>
    - <em>/<i> → <i>...</i>
    - <br> → newline
    - <p> → text with double newline
    - <li> → • item
    - <a href> → <a href>text</a>
    - All other tags → stripped, text preserved
    """
    if not html:
        return ""

    result = html

    # ── Remove <style> and <script> blocks entirely ──
    result = re.sub(
        r"<(style|script)[^>]*>[\s\S]*?</\1>", "", result, flags=re.IGNORECASE
    )

    # ── Line breaks & rules ──
    result = re.sub(r"<br\s*/?>", "\n", result, flags=re.IGNORECASE)
    result = re.sub(r"<hr\s*/?>", "\n───\n", result, flags=re.IGNORECASE)

    # ── Headings h1-h3 → bold text ──
    for level in range(1, 4):
        result = re.sub(
            rf"<h{level}[^>]*>([\s\S]*?)</h{level}>",
            lambda m: f"\n<b>{_strip_tags(m.group(1)).strip()}</b>\n",
            result,
            flags=re.IGNORECASE,
        )

    # ── Code blocks <pre><code class="language-xxx"> → <pre> ──
    result = re.sub(
        r'<pre[^>]*>\s*<code(?:\s+class="language-([^"]*)")?[^>]*>([\s\S]*?)</code>\s*</pre>',
        lambda m: f'\n<pre>{_escape_html(_decode_entities(m.group(2)))}</pre>\n',
        result,
        flags=re.IGNORECASE,
    )

    # ── Standalone <pre> without <code> ──
    result = re.sub(
        r"<pre[^>]*>([\s\S]*?)</pre>",
        lambda m: f'\n<pre>{_escape_html(_decode_entities(_strip_tags(m.group(1))))}</pre>\n',
        result,
        flags=re.IGNORECASE,
    )

    # ── Inline code ──
    result = re.sub(
        r"<code[^>]*>([\s\S]*?)</code>",
        lambda m: f"<code>{_escape_html(_decode_entities(m.group(1)))}</code>",
        result,
        flags=re.IGNORECASE,
    )

    # ── Bold / Italic ──
    result = re.sub(
        r"<(?:strong|b)(?:\s[^>]*)?>(.+?)</(?:strong|b)>",
        r"<b>\1</b>",
        result,
        flags=re.IGNORECASE,
    )
    result = re.sub(
        r"<(?:em|i)(?:\s[^>]*)?>(.+?)</(?:em|i)>",
        r"<i>\1</i>",
        result,
        flags=re.IGNORECASE,
    )

    # ── Links ──
    result = re.sub(
        r'<a\s+[^>]*href="([^"]*)"[^>]*>([\s\S]*?)</a>',
        lambda m: f'<a href="{m.group(1)}">{_strip_tags(m.group(2))}</a>',
        result,
        flags=re.IGNORECASE,
    )

    # ── Paragraphs & divs ──
    result = re.sub(
        r"<p[^>]*>([\s\S]*?)</p>", r"\1\n\n", result, flags=re.IGNORECASE
    )
    result = re.sub(
        r"<div[^>]*>([\s\S]*?)</div>", r"\1\n", result, flags=re.IGNORECASE
    )

    # ── Lists ──
    result = re.sub(
        r"<li[^>]*>([\s\S]*?)</li>",
        lambda m: f"• {_strip_tags(m.group(1)).strip()}\n",
        result,
        flags=re.IGNORECASE,
    )
    result = re.sub(r"</?(?:ul|ol)[^>]*>", "", result, flags=re.IGNORECASE)

    # ── Strip all remaining tags (except Telegram-supported ones) ──
    result = _strip_unsupported_tags(result)

    # ── Decode HTML entities in non-tag text ──
    result = _decode_entities(result)

    # ── Clean excessive whitespace ──
    result = re.sub(r"\n{3,}", "\n\n", result)
    result = result.strip()

    return result


def _strip_tags(html: str) -> str:
    """Remove all HTML tags from a string."""
    return re.sub(r"<[^>]+>", "", html)


def _strip_unsupported_tags(html: str) -> str:
    """Remove all HTML tags EXCEPT Telegram-supported ones.
    
    Telegram HTML supports: <b>, <i>, <code>, <pre>, <a>, <s>, <u>.
    """
    # Keep only these tags
    return re.sub(
        r"<(?!/?(b|i|code|pre|a|s|u)(?:\s|>|/))[^>]+>",
        "",
        html,
        flags=re.IGNORECASE,
    )


def _escape_html(text: str) -> str:
    """Escape HTML special chars for use inside <pre>/<code> blocks."""
    text = text.replace("&", "&amp;")
    text = text.replace("<", "&lt;")
    text = text.replace(">", "&gt;")
    return text


def _decode_entities(text: str) -> str:
    """Decode common HTML entities."""
    text = text.replace("&lt;", "<")
    text = text.replace("&gt;", ">")
    text = text.replace("&amp;", "&")
    text = text.replace("&quot;", '"')
    text = text.replace("&#39;", "'")
    text = text.replace("&#x27;", "'")
    text = text.replace("&nbsp;", " ")
    # Generic numeric entities
    text = re.sub(
        r"&#x([0-9a-fA-F]+);",
        lambda m: chr(int(m.group(1), 16)),
        text,
    )
    text = re.sub(
        r"&#(\d+);",
        lambda m: chr(int(m.group(1))),
        text,
    )
    return text
