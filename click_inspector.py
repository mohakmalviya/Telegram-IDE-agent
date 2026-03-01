"""
TEAM_003: CDP Click Inspector — Debug utility.

Connects to the IDE via Chrome DevTools Protocol and injects a click listener
into the chat side panel. Every click logs the full DOM ancestry, CSS classes,
attributes, dimensions, and inner text of the clicked element.

Results are saved to `click_log.jsonl` (one JSON object per line) and also
printed to the terminal in a human-readable tree format.

Usage:
    python click_inspector.py [--port 9223] [--output click_log.jsonl]
"""

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime

import aiohttp


# ── JS injected into the IDE page ────────────────────────────────────────────
# Registers a click listener on the document. On each click it walks up the
# DOM tree from the clicked element to <body>, collecting structure info.
# Results are stored in window.__clickLog (array) for periodic polling.

INJECT_CLICK_LISTENER = r"""(() => {
    if (window.__clickInspectorActive) return 'already_active';

    window.__clickLog = [];
    window.__clickInspectorActive = true;

    document.addEventListener('click', (e) => {
        const entry = {
            timestamp: new Date().toISOString(),
            target: null,
            ancestors: [],
            panelContext: null
        };

        // ── Collect clicked element info ──
        const describeNode = (el) => {
            if (!el || el.nodeType !== 1) return null;
            const rect = el.getBoundingClientRect();
            return {
                tag: el.tagName.toLowerCase(),
                id: el.id || null,
                classes: [...el.classList],
                attributes: Array.from(el.attributes).reduce((acc, a) => {
                    if (!['class', 'id', 'style'].includes(a.name)) {
                        acc[a.name] = a.value.slice(0, 200);
                    }
                    return acc;
                }, {}),
                text: (el.textContent || '').trim().slice(0, 300),
                innerHtmlLength: (el.innerHTML || '').length,
                childElementCount: el.children.length,
                rect: {
                    x: Math.round(rect.x),
                    y: Math.round(rect.y),
                    width: Math.round(rect.width),
                    height: Math.round(rect.height)
                },
                computedDisplay: getComputedStyle(el).display,
                computedPosition: getComputedStyle(el).position,
                role: el.getAttribute('role'),
                ariaLabel: el.getAttribute('aria-label'),
                dataAttributes: Array.from(el.attributes)
                    .filter(a => a.name.startsWith('data-'))
                    .reduce((acc, a) => { acc[a.name] = a.value.slice(0, 200); return acc; }, {})
            };
        };

        // ── Walk up from target to body ──
        let current = e.target;
        entry.target = describeNode(current);

        while (current && current !== document.body && current !== document.documentElement) {
            current = current.parentElement;
            if (current) {
                entry.ancestors.push(describeNode(current));
            }
        }

        // ── Check if click was inside the chat panel ──
        const panel = document.querySelector('.antigravity-agent-side-panel');
        if (panel && panel.contains(e.target)) {
            entry.panelContext = 'inside_chat_panel';
        } else if (panel) {
            entry.panelContext = 'outside_chat_panel';
        } else {
            entry.panelContext = 'no_panel_found';
        }

        // ── Sibling context: what's around the clicked element ──
        const parent = e.target.parentElement;
        if (parent) {
            entry.siblingContext = {
                parentTag: parent.tagName.toLowerCase(),
                parentClasses: [...parent.classList],
                totalSiblings: parent.children.length,
                siblingTags: Array.from(parent.children).map(c => ({
                    tag: c.tagName.toLowerCase(),
                    classes: [...c.classList].slice(0, 5),
                    textPreview: (c.textContent || '').trim().slice(0, 80)
                })).slice(0, 10)
            };
        }

        window.__clickLog.push(entry);
    }, true);  // useCapture = true to catch everything

    return 'listener_installed';
})()"""


# ── Poll script: drain the click log ──────────────────────────────────────────

POLL_CLICKS = r"""(() => {
    if (!window.__clickLog) return [];
    const items = window.__clickLog.splice(0);
    return items;
})()"""


# ── Cleanup script ───────────────────────────────────────────────────────────

REMOVE_LISTENER = r"""(() => {
    window.__clickInspectorActive = false;
    window.__clickLog = [];
    return 'cleaned_up';
})()"""


# ── CDP connection (minimal, standalone — no dependency on cdp_manager.py) ───

class CdpInspector:
    """Lightweight CDP client for the click inspector."""

    def __init__(self, port: int) -> None:
        self._port = port
        self._ws = None
        self._session = None
        self._msg_id = 0
        self._pending: dict[int, asyncio.Future] = {}
        self._listener_task = None

    async def connect(self) -> str:
        self._session = aiohttp.ClientSession()

        async with self._session.get(
            f"http://127.0.0.1:{self._port}/json",
            timeout=aiohttp.ClientTimeout(total=5),
        ) as resp:
            targets = await resp.json()

        # Find the IDE page target
        target = None
        for t in targets:
            if t.get("type") != "page" or "webSocketDebuggerUrl" not in t:
                continue
            url = t.get("url", "")
            if any(skip in url for skip in ["chrome://", "devtools://", "about:blank"]):
                continue
            target = t
            # Prefer workbench or antigravity targets
            title = t.get("title", "").lower()
            if "workbench" in url.lower() or "antigravity" in title:
                break

        if not target:
            raise ConnectionError(f"No IDE target found on port {self._port}")

        ws_url = target["webSocketDebuggerUrl"]
        title = target.get("title", "Unknown")

        self._ws = await self._session.ws_connect(ws_url)
        self._listener_task = asyncio.create_task(self._listen())
        return title

    async def _listen(self) -> None:
        try:
            async for msg in self._ws:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    data = json.loads(msg.data)
                    msg_id = data.get("id")
                    if msg_id is not None and msg_id in self._pending:
                        self._pending[msg_id].set_result(data)
                elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                    break
        except Exception:
            pass

    async def evaluate(self, expression: str):
        self._msg_id += 1
        mid = self._msg_id
        future = asyncio.get_event_loop().create_future()
        self._pending[mid] = future
        await self._ws.send_json({
            "id": mid,
            "method": "Runtime.evaluate",
            "params": {"expression": expression, "returnByValue": True},
        })
        result = await asyncio.wait_for(future, timeout=15)
        js_result = result.get("result", {}).get("result", {})
        return js_result.get("value")

    async def close(self) -> None:
        if self._listener_task:
            self._listener_task.cancel()
        if self._ws and not self._ws.closed:
            await self._ws.close()
        if self._session:
            await self._session.close()


# ── Pretty terminal output ───────────────────────────────────────────────────

def format_node(node: dict, indent: int = 0) -> str:
    """Format a single node description for terminal output."""
    if not node:
        return ""
    pad = "  " * indent
    tag = node.get("tag", "?")
    nid = node.get("id")
    classes = node.get("classes", [])
    role = node.get("role")
    aria = node.get("ariaLabel")
    rect = node.get("rect", {})
    text = node.get("text", "")

    # Build the selector-like representation
    selector = f"<{tag}>"
    if nid:
        selector = f"<{tag}#{nid}>"
    if classes:
        selector += "." + ".".join(classes[:5])
    if role:
        selector += f'  [role="{role}"]'
    if aria:
        selector += f'  [aria-label="{aria[:40]}"]'

    # Size info
    size = f"{rect.get('width', '?')}x{rect.get('height', '?')}"

    # Text preview (first line only, truncated)
    text_preview = ""
    if text:
        first_line = text.split("\n")[0].strip()[:60]
        if first_line:
            text_preview = f'  → "{first_line}"'

    line = f"{pad}├─ {selector}  ({size}){text_preview}"
    return line


def print_click_entry(entry: dict, click_num: int) -> None:
    """Print a formatted click entry to the terminal."""
    ts = entry.get("timestamp", "?")
    ctx = entry.get("panelContext", "?")
    target = entry.get("target", {})
    ancestors = entry.get("ancestors", [])
    sibling_ctx = entry.get("siblingContext", {})

    panel_icon = "🟢" if ctx == "inside_chat_panel" else "🔴"

    print(f"\n{'═' * 72}")
    print(f"  Click #{click_num}  |  {ts}  |  {panel_icon} {ctx}")
    print(f"{'─' * 72}")

    # Print ancestor chain (top-down: reverse the list)
    print("  DOM Path (root → target):")
    for i, ancestor in enumerate(reversed(ancestors)):
        print(format_node(ancestor, indent=i + 1))

    # Print the target itself (highlighted)
    depth = len(ancestors) + 1
    pad = "  " * depth
    if target:
        tag = target.get("tag", "?")
        nid = target.get("id")
        classes = target.get("classes", [])
        selector = f"<{tag}>"
        if nid:
            selector = f"<{tag}#{nid}>"
        if classes:
            selector += "." + ".".join(classes[:5])
        text = (target.get("text", "") or "").split("\n")[0].strip()[:80]
        children = target.get("childElementCount", 0)
        html_len = target.get("innerHtmlLength", 0)
        print(f"{pad}╰─ ★ {selector}  children={children}  html={html_len}b")
        if text:
            print(f"{pad}     text: \"{text}\"")
        # Data attributes
        data_attrs = target.get("dataAttributes", {})
        if data_attrs:
            for k, v in data_attrs.items():
                print(f"{pad}     {k}={v[:60]}")

    # Sibling context
    if sibling_ctx:
        print(f"\n  Siblings of target ({sibling_ctx.get('totalSiblings', '?')} total):")
        for sib in sibling_ctx.get("siblingTags", []):
            stag = sib.get("tag", "?")
            scls = ".".join(sib.get("classes", [])[:3])
            stxt = sib.get("textPreview", "")[:50]
            suffix = f".{scls}" if scls else ""
            txt_part = f'  "{stxt}"' if stxt else ""
            print(f"    • <{stag}{suffix}>{txt_part}")

    print(f"{'═' * 72}")


# ── Main loop ────────────────────────────────────────────────────────────────

async def main(port: int, output_file: str) -> None:
    cdp = CdpInspector(port)

    print(f"\n🔍 Click Inspector — Connecting to CDP on port {port}...")
    try:
        title = await cdp.connect()
    except Exception as e:
        print(f"❌ Failed to connect: {e}")
        print(f"   Make sure the IDE is running with --remote-debugging-port={port}")
        return

    print(f"✅ Connected to: {title}")

    # Inject the click listener
    result = await cdp.evaluate(INJECT_CLICK_LISTENER)
    if result == "already_active":
        print("⚠️  Click listener was already active (reusing)")
    else:
        print("✅ Click listener injected into the page")

    print(f"📝 Logging clicks to: {output_file}")
    print(f"   Press Ctrl+C to stop\n")
    print("   Now click on elements in the IDE chat window...")
    print(f"{'─' * 72}")

    click_count = 0

    try:
        while True:
            await asyncio.sleep(1)

            # Poll for new clicks
            clicks = await cdp.evaluate(POLL_CLICKS)
            if not clicks:
                continue

            for entry in clicks:
                click_count += 1

                # Print to terminal
                print_click_entry(entry, click_count)

                # Append to JSONL file
                with open(output_file, "a", encoding="utf-8") as f:
                    f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    except KeyboardInterrupt:
        print(f"\n\n🛑 Stopped. {click_count} clicks logged to {output_file}")
    except Exception as e:
        print(f"\n❌ Error: {e}")
    finally:
        try:
            await cdp.evaluate(REMOVE_LISTENER)
        except Exception:
            pass
        await cdp.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="CDP Click Inspector for IDE chat panel")
    parser.add_argument("--port", type=int, default=int(os.getenv("CDP_PORT", "9223")),
                        help="CDP port (default: from CDP_PORT env or 9223)")
    parser.add_argument("--output", type=str, default="click_log.jsonl",
                        help="Output file path (default: click_log.jsonl)")
    args = parser.parse_args()

    asyncio.run(main(args.port, args.output))
