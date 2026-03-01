"""
TEAM_001: IDE bridge service.
High-level interface for interacting with IDEs via Chrome DevTools Protocol.
Supports multiple IDEs through configurable DOM selector profiles.
"""

import asyncio
import logging
import time
from dataclasses import dataclass

from telegram_ide_agent.services.cdp_manager import CdpManager, CdpConnectionError
from telegram_ide_agent.services.cdp_scripts import STRUCTURED_PROGRESS_SCRIPT
from telegram_ide_agent.utils.html_to_telegram import html_to_telegram

logger = logging.getLogger(__name__)


# ─── LazyGravity-ported CDP scripts ──────────────────────────────
# TEAM_002: Ported from LazyGravity responseMonitor.ts + assistantDomExtractor.ts

# TEAM_002: Ported from LazyGravity responseMonitor.ts + assistantDomExtractor.ts

# TEAM_002: Structured chat extraction — returns JSON with processLogs + response.
# Ported from LazyGravity's PROCESS_LOGS + RESPONSE_TEXT dual extraction.
# processLogs = activity messages as plain text
# response = innerHTML of the latest response (cleaned by html_to_telegram later)
FULL_CHAT_SCRIPT = """(() => {
    const panel = document.querySelector('.antigravity-agent-side-panel');
    const scopes = [panel, document].filter(Boolean);

    const selectors = [
        '.rendered-markdown',
        '.leading-relaxed.select-text',
        '.flex.flex-col.gap-y-3',
        '[data-message-author-role="assistant"]',
        '[data-message-role="assistant"]',
        '[class*="assistant-message"]',
        '[class*="message-content"]',
        '[class*="markdown-body"]',
        '.prose',
    ];

    const looksLikeActivityLog = (text) => {
        const n = (text || '').trim().toLowerCase();
        if (!n) return false;
        const pat = /^(?:analy[sz]ing|reading|writing|running|searching|planning|thinking|processing|loading|executing|testing|debugging|fetching|connecting|creating|updating|deleting|installing|building|compiling|deploying|checking|scanning|parsing|resolving|downloading|uploading|analyzed|read|wrote|ran|created|updated|deleted|fetched|built|compiled|installed|resolved|downloaded|connected|prioritiz|refin|focusing|initiating|viewing|editing|modifying|removing|adding|fixing|implementing|configuring|setting|preparing|formatting|cleaning|reviewing|comparing|merging|committing|pushing|pulling|cloning)\\b/i;
        if (pat.test(n) && n.length <= 300) return true;
        if (/^initiating\\s/i.test(n) && n.length <= 500) return true;
        if (/^thought for\\s/i.test(n) && n.length <= 500) return true;
        return false;
    };

    const looksLikeToolOutput = (text) => {
        const lines = (text || '').trim().split(String.fromCharCode(10));
        const first = lines[0] || '';
        if (/^[a-z0-9._-]+\\s*\\\\/\\s*[a-z0-9._-]+$/i.test(first)) return true;
        if (/^full output written to\\b/i.test(first)) return true;
        return false;
    };

    const looksLikeFeedback = (text) => {
        const n = (text || '').trim().toLowerCase().replace(/\\s+/g, ' ');
        return n === 'good bad' || n === 'good' || n === 'bad';
    };

    const isExcluded = (node) => {
        if (node.closest('details')) return true;
        if (node.closest('[class*="feedback"], footer')) return true;
        if (node.closest('.notify-user-container')) return true;
        if (node.closest('[role="dialog"]')) return true;
        return false;
    };

    const combinedSelector = selectors.join(', ');
    const result = { processLogs: [], responseHtml: null };
    const seen = new Set();

    // Pass 1: Collect process logs (activity messages) as plain text
    for (const scope of scopes) {
        const nodes = scope.querySelectorAll(combinedSelector);
        for (let i = 0; i < nodes.length; i++) {
            const node = nodes[i];
            if (!node || seen.has(node)) continue;
            seen.add(node);
            if (isExcluded(node)) continue;
            const text = (node.innerText || node.textContent || '').replace(/\\r/g, '').trim();
            if (!text || text.length < 4) continue;
            if (looksLikeActivityLog(text) || looksLikeToolOutput(text)) {
                result.processLogs.push(text.slice(0, 300));
            }
        }
    }

    // Pass 2: Get latest response as innerHTML (clone + strip style/script/svg)
    // Same approach as the working RESPONSE_TEXT_SCRIPT
    const seen2 = new Set();
    for (const scope of scopes) {
        const nodes = scope.querySelectorAll(combinedSelector);
        for (let i = nodes.length - 1; i >= 0; i--) {
            const node = nodes[i];
            if (!node || seen2.has(node)) continue;
            seen2.add(node);
            if (isExcluded(node)) continue;
            const text = (node.innerText || node.textContent || '').replace(/\\r/g, '').trim();
            if (!text || text.length < 2) continue;
            if (looksLikeActivityLog(text)) continue;
            if (looksLikeFeedback(text)) continue;
            if (looksLikeToolOutput(text)) continue;
            // Clone and strip non-content elements before getting innerHTML
            const clone = node.cloneNode(true);
            clone.querySelectorAll('style, script, svg').forEach(el => el.remove());
            result.responseHtml = clone.innerHTML || '';
            break;
        }
    }

    return result;
})()"""



# Extracts the actual assistant response, skipping thought blocks, activity logs,
# feedback buttons, tool output, and content inside excluded containers.
RESPONSE_TEXT_SCRIPT = """(() => {
    const panel = document.querySelector('.antigravity-agent-side-panel');
    const scopes = [panel, document].filter(Boolean);

    const selectors = [
        '.rendered-markdown',
        '.leading-relaxed.select-text',
        '.flex.flex-col.gap-y-3',
        '[data-message-author-role="assistant"]',
        '[data-message-role="assistant"]',
        '[class*="assistant-message"]',
        '[class*="message-content"]',
        '[class*="markdown-body"]',
        '.prose',
    ];

    const looksLikeActivityLog = (text) => {
        const normalized = (text || '').trim().toLowerCase();
        if (!normalized) return false;
        const actPat = /^(?:analy[sz]ing|reading|writing|running|searching|planning|thinking|processing|loading|executing|testing|debugging|fetching|connecting|creating|updating|deleting|installing|building|compiling|deploying|checking|scanning|parsing|resolving|downloading|uploading|analyzed|read|wrote|ran|created|updated|deleted|fetched|built|compiled|installed|resolved|downloaded|connected|prioritiz|refin|focusing|initiating)\\b/i;
        if (actPat.test(normalized) && normalized.length <= 220) return true;
        if (/^initiating\\s/i.test(normalized) && normalized.length <= 500) return true;
        if (/^thought for\\s/i.test(normalized) && normalized.length <= 500) return true;
        return false;
    };

    const looksLikeFeedback = (text) => {
        const n = (text || '').trim().toLowerCase().replace(/\\s+/g, ' ');
        return n === 'good bad' || n === 'good' || n === 'bad';
    };

    const isExcluded = (node) => {
        if (node.closest('details')) return true;
        if (node.closest('[class*="feedback"], footer')) return true;
        if (node.closest('.notify-user-container')) return true;
        if (node.closest('[role="dialog"]')) return true;
        return false;
    };

    const looksLikeToolOutput = (text) => {
        const first = (text || '').trim().split('\\n')[0] || '';
        if (/^[a-z0-9._-]+\\s*\\/\\s*[a-z0-9._-]+$/i.test(first)) return true;
        if (/^full output written to\\b/i.test(first)) return true;
        return false;
    };

    const combinedSelector = selectors.join(', ');
    const seen = new Set();

    for (const scope of scopes) {
        const nodes = scope.querySelectorAll(combinedSelector);
        for (let i = nodes.length - 1; i >= 0; i--) {
            const node = nodes[i];
            if (!node || seen.has(node)) continue;
            seen.add(node);
            if (isExcluded(node)) continue;
            const text = (node.innerText || node.textContent || '').replace(/\\r/g, '').trim();
            if (!text || text.length < 2) continue;
            if (looksLikeActivityLog(text)) continue;
            if (looksLikeFeedback(text)) continue;
            if (looksLikeToolOutput(text)) continue;
            // Clone and strip style/script tags
            const clone = node.cloneNode(true);
            clone.querySelectorAll('style, script').forEach(el => el.remove());
            return clone.innerHTML || '';
        }
    }
    return null;
})()"""

# Detects if the stop/cancel button is present (= AI is still generating)
STOP_BUTTON_SCRIPT = """(() => {
    const panel = document.querySelector('.antigravity-agent-side-panel');
    const scopes = [panel, document].filter(Boolean);
    for (const scope of scopes) {
        const el = scope.querySelector('[data-tooltip-id="input-send-button-cancel-tooltip"]');
        if (el) return { isGenerating: true };
    }
    const STOP_PATS = [/^stop$/i, /^stop generating$/i, /^stop response$/i];
    for (const scope of scopes) {
        for (const btn of scope.querySelectorAll('button, [role="button"]')) {
            const labels = [
                (btn.textContent || '').trim(),
                (btn.getAttribute('aria-label') || '').trim(),
                (btn.getAttribute('title') || '').trim(),
            ];
            if (labels.some(l => STOP_PATS.some(p => p.test(l)))) return { isGenerating: true };
        }
    }
    return { isGenerating: false };
})()"""

# TEAM_002: Auto-clicks approval prompts ONLY inside the chat panel.
# Scoped to .antigravity-agent-side-panel to avoid clicking random IDE buttons.
APPROVAL_CLICK_SCRIPT = """(() => {
    // Only look inside the chat side panel
    const panel = document.querySelector('.antigravity-agent-side-panel');
    if (!panel) return null;

    const isVisible = (el) => {
        if (!el) return false;
        const rect = el.getBoundingClientRect();
        return el.offsetParent !== null && rect.width > 0 && rect.height > 0;
    };
    
    const isDisabled = (el) => {
        return el.disabled || el.hasAttribute('disabled') || 
               el.getAttribute('aria-disabled') === 'true';
    };

    const allButtons = Array.from(panel.querySelectorAll('button'))
        .filter(btn => isVisible(btn) && !isDisabled(btn));

    // Simulate a real click
    const realClick = (btn) => {
        const rect = btn.getBoundingClientRect();
        const x = rect.x + rect.width / 2;
        const y = rect.y + rect.height / 2;
        ['pointerdown','mousedown','pointerup','mouseup','click'].forEach(type => {
            btn.dispatchEvent(new MouseEvent(type, {
                bubbles: true, cancelable: true, view: window,
                clientX: x, clientY: y, button: 0,
            }));
        });
    };

    // Buttons we must NEVER click
    const blacklist = ['reject', 'deny', 'cancel', 'review', 'ask every time',
                       'thought for', 'thinking', 'planning', 'fast',
                       'record voice', 'scroll to', 'send'];

    // Approval button text patterns (substring match, in priority order)
    // Monitor logs show button text is "runalt+⏎" (no space!) so we need both variants
    const approvalPatterns = [
        'runalt',          // "RunAlt+⏎" (NO space — from monitor logs!)
        'run alt',         // "Run Alt+↵" (with space variant)
        'runctrl',         // "RunCtrl+⏎" (NO space)
        'run ctrl',        // "Run Ctrl+⏎" (with space)
        'run command',     // "Run command"
        'accept changes',  // File change approval
        'accept',          // Generic accept
        'allow once',      // Permission grant
        'always allow',    // Permission grant
        'allow',           // Permission grant
        'relocate',        // File move approval
        'apply',           // Apply changes
        'confirm',         // Confirm action
        'continue',        // Continue operation
        'submit',          // Submit (notify_user)
    ];

    for (const btn of allButtons) {
        const t = (btn.textContent || '').toLowerCase().trim();
        if (!t || t.length > 60) continue;
        // Skip blacklisted
        if (blacklist.some(b => t.includes(b))) continue;
        // Match approval patterns
        if (approvalPatterns.some(p => t.includes(p))) {
            realClick(btn);
            return 'clicked: ' + t.slice(0, 40);
        }
    }

    return null;
})()"""

# TEAM_002: Detects active approval prompts inside the side panel and returns
# structured data about them (header, command, available buttons).
# Used to send inline keyboards to Telegram.
DETECT_PROMPT_SCRIPT = """(() => {
    const panel = document.querySelector('.antigravity-agent-side-panel');
    if (!panel) return null;

    // Find approval prompt containers:
    // Structure from monitor logs: div.flex.flex-col.gap-2 contains:
    //   - div.mb-1 (header like "Run command?")
    //   - pre (command text)
    //   - div with buttons (Ask every time, Reject, RunAlt+⏎)
    const prompts = [];
    
    // Look for all button groups that have Run/Accept/Relocate buttons
    const allButtons = Array.from(panel.querySelectorAll('button'));
    const approvalKeywords = ['runalt', 'run alt', 'runctrl', 'run ctrl',
        'run command', 'accept changes', 'accept', 'allow once', 'always allow',
        'allow', 'apply', 'confirm', 'continue', 'submit'];
    
    const isVisible = (el) => {
        if (!el) return false;
        const rect = el.getBoundingClientRect();
        return el.offsetParent !== null && rect.width > 0 && rect.height > 0;
    };

    const seen = new Set();
    
    for (const btn of allButtons) {
        if (!isVisible(btn) || btn.disabled) continue;
        const btnText = (btn.textContent || '').toLowerCase().trim();
        if (!approvalKeywords.some(k => btnText.includes(k))) continue;
        
        // Walk up to find the prompt container
        const container = btn.closest('div.flex.flex-col.gap-2') || 
                          btn.closest('div.flex.flex-col') ||
                          btn.parentElement?.parentElement;
        if (!container || seen.has(container)) continue;
        seen.add(container);
        
        // Extract header text (e.g., "Run command?")
        const headerEl = container.querySelector('div.mb-1') || 
                         container.querySelector('[class*="border-b"]');
        const header = headerEl ? headerEl.textContent.trim().slice(0, 100) : '';
        
        // Extract command/preview text
        const preEl = container.querySelector('pre');
        const preview = preEl ? preEl.textContent.trim().slice(0, 500) : '';
        
        // Collect all visible buttons in this container
        const containerButtons = Array.from(container.querySelectorAll('button'))
            .filter(b => isVisible(b) && !b.disabled)
            .map(b => ({
                text: b.textContent.trim().slice(0, 50),
                lower: b.textContent.trim().toLowerCase().slice(0, 50),
            }))
            .filter(b => b.text && b.text.length < 50 && 
                         !b.lower.includes('ask every time') &&
                         !b.lower.includes('thought for') &&
                         !b.lower.includes('relocate'));
        
        if (containerButtons.length > 0) {
            prompts.push({
                header: header,
                preview: preview,
                buttons: containerButtons.map(b => b.text),
            });
        }
    }
    
    return prompts.length > 0 ? prompts : null;
})()"""

# TEAM_002: Generates a JS script that clicks a button matching the target text.
def _make_click_button_script(target_text: str) -> str:
    """Build JS to click a specific button by text inside the side panel."""
    safe = target_text.replace("'", "\\'").replace("\\", "\\\\").lower()
    return (
        "(() => {"
        "const panel = document.querySelector('.antigravity-agent-side-panel');"
        "if (!panel) return null;"
        f"const target = '{safe}';"
        "const isVisible = (el) => {"
        "  if (!el) return false;"
        "  const rect = el.getBoundingClientRect();"
        "  return el.offsetParent !== null && rect.width > 0 && rect.height > 0;"
        "};"
        "const allButtons = Array.from(panel.querySelectorAll('button'))"
        "  .filter(btn => isVisible(btn) && !btn.disabled);"
        "for (const btn of allButtons) {"
        "  const t = (btn.textContent || '').toLowerCase().trim();"
        "  if (t.includes(target)) {"
        "    const rect = btn.getBoundingClientRect();"
        "    const x = rect.x + rect.width / 2;"
        "    const y = rect.y + rect.height / 2;"
        "    ['pointerdown','mousedown','pointerup','mouseup','click'].forEach(type => {"
        "      btn.dispatchEvent(new MouseEvent(type, {"
        "        bubbles: true, cancelable: true, view: window,"
        "        clientX: x, clientY: y, button: 0,"
        "      }));"
        "    });"
        "    return 'clicked: ' + t.slice(0, 40);"
        "  }"
        "}"
        "return null;"
        "})()"
    )


# ─── IDE Profiles ─────────────────────────────────────────────────
# Each profile defines the DOM selectors for a specific IDE's chat UI.
# These are CSS selectors used via document.querySelector() in the IDE.

@dataclass(frozen=True)
class IdeProfile:
    """DOM selectors and behavior config for a specific IDE."""
    name: str
    display_name: str
    chat_input: str
    send_button: str
    message_container: str
    assistant_message: str
    generating_indicator: str | None = None
    input_is_contenteditable: bool = False
    stop_button: str | None = None


# TEAM_001: IDE profiles — selectors discovered via live CDP DOM inspection
IDE_PROFILES: dict[str, IdeProfile] = {
    "antigravity": IdeProfile(
        name="antigravity",
        display_name="Antigravity",
        # Real selectors from CDP DOM dump:
        # - Chat input: contenteditable div with role=textbox inside antigravity-agent-side-panel
        # - Container: div.antigravity-agent-side-panel identified in the DOM
        chat_input='div.antigravity-agent-side-panel div[role="textbox"]',
        send_button='div.antigravity-agent-side-panel button[aria-label*="Send" i], div.antigravity-agent-side-panel button[type="submit"]',
        message_container='div.antigravity-agent-side-panel',
        assistant_message='div.antigravity-agent-side-panel div.leading-relaxed.select-text:not(.opacity-70)',
        generating_indicator='div.antigravity-agent-side-panel [class*="loading"], div.antigravity-agent-side-panel [class*="streaming"]',
        input_is_contenteditable=True,
        stop_button='div.antigravity-agent-side-panel button[aria-label*="Stop" i]',
    ),
    "cursor": IdeProfile(
        name="cursor",
        display_name="Cursor",
        chat_input='textarea.chat-textarea, div[contenteditable="true"].ProseMirror, textarea[placeholder*="message" i]',
        send_button='button[aria-label*="send" i], button.send-btn, button[data-testid="send"]',
        message_container='.chat-scroll-container, .messages-container',
        assistant_message='.message-assistant, [data-role="assistant"], .response-message',
        generating_indicator='.generating, .is-streaming, [data-generating="true"]',
        input_is_contenteditable=False,
        stop_button='button[aria-label*="stop" i]',
    ),
    "vscode": IdeProfile(
        name="vscode",
        display_name="VS Code (Copilot Chat)",
        chat_input='textarea.interactive-input, div[role="textbox"][contenteditable="true"]',
        send_button='a.codicon-send, button[aria-label*="Send"]',
        message_container='.interactive-list',
        assistant_message='.interactive-response, [data-role="response"]',
        generating_indicator='.progress-container .progress-bit, .codicon-loading',
        input_is_contenteditable=False,
        stop_button='a.codicon-debug-stop, button[aria-label*="Cancel"]',
    ),
    "windsurf": IdeProfile(
        name="windsurf",
        display_name="Windsurf",
        chat_input='textarea[placeholder*="message" i], div[contenteditable="true"]',
        send_button='button[aria-label*="send" i], button[type="submit"]',
        message_container='.chat-messages, .message-container',
        assistant_message='[data-role="assistant"], .assistant-message',
        generating_indicator='.generating, .streaming, .thinking',
        stop_button='button[aria-label*="stop" i]',
    ),
}


class IdeBridgeError(Exception):
    """Raised when IDE interaction fails."""


class IdeBridge:
    """High-level bridge to interact with an IDE's chat UI via CDP.

    Sends messages to the IDE's AI assistant and reads back responses,
    using the IDE's own AI subscription — no external API keys needed.
    """

    def __init__(
        self,
        cdp: CdpManager,
        profile_name: str = "antigravity",
        response_timeout: int = 120,
    ) -> None:
        self.cdp = cdp
        self.profile = IDE_PROFILES.get(profile_name)
        if not self.profile:
            raise ValueError(
                f"Unknown IDE profile: {profile_name}. "
                f"Available: {', '.join(IDE_PROFILES.keys())}"
            )
        self.response_timeout = response_timeout
        self._ide_title: str | None = None

    @property
    def ide_name(self) -> str:
        return self._ide_title or self.profile.display_name

    async def connect(self) -> str:
        """Connect to the IDE via CDP. Returns the IDE window title."""
        self._ide_title = await self.cdp.connect()
        logger.info("IDE Bridge connected to: %s", self._ide_title)
        return self._ide_title

    async def send_message(self, text: str) -> None:
        """Type a message into the IDE's chat input and send it.

        Uses document.execCommand('insertText') for contenteditable divs
        so React's synthetic events are properly triggered.

        Args:
            text: The message to send.

        Raises:
            IdeBridgeError: If the chat input is not found or send fails.
        """
        p = self.profile

        # Escape text for JS template literal
        escaped_text = (
            text.replace("\\", "\\\\")
                .replace("`", "\\`")
                .replace("$", "\\$")
        )

        if p.input_is_contenteditable:
            # For contenteditable divs (VS Code / Antigravity):
            # Must use execCommand('insertText') to fire React's onChange.
            # Simply setting textContent doesn't trigger framework events.
            js = f"""
            (() => {{
                const selectors = [
                    'div.antigravity-agent-side-panel div[role="textbox"]',
                    'div[contenteditable="true"][role="textbox"]',
                    'div[contenteditable="true"]'
                ];
                let input = null;
                for (const sel of selectors) {{
                    input = document.querySelector(sel);
                    if (input) break;
                }}
                if (!input) return 'INPUT_NOT_FOUND';
                input.focus();
                document.execCommand('selectAll', false, null);
                document.execCommand('delete', false, null);
                document.execCommand('insertText', false, `{escaped_text}`);
                return 'OK';
            }})()
            """
        else:
            # For textarea elements
            js = f"""
            (() => {{
                const input = document.querySelector('{p.chat_input}');
                if (!input) return 'INPUT_NOT_FOUND';
                input.focus();
                const setter = Object.getOwnPropertyDescriptor(
                    window.HTMLTextAreaElement.prototype, 'value'
                ).set;
                setter.call(input, `{escaped_text}`);
                input.dispatchEvent(new Event('input', {{ bubbles: true }}));
                input.dispatchEvent(new Event('change', {{ bubbles: true }}));
                return 'OK';
            }})()
            """

        result = await self.cdp.evaluate(js)
        if result == "INPUT_NOT_FOUND":
            raise IdeBridgeError(
                f"Chat input not found in {self.profile.display_name}. "
                "Make sure the Antigravity chat panel is open and visible."
            )

        # Wait for React state to settle
        await asyncio.sleep(0.5)

        # Send: try button click first, then Enter keypress fallback
        send_js = f"""
        (() => {{
            const sendSelectors = [
                'div.antigravity-agent-side-panel button[aria-label*="Send" i]',
                'div.antigravity-agent-side-panel button[type="submit"]',
                'button[aria-label*="Send" i]',
                'button[aria-label*="send" i]'
            ];
            for (const sel of sendSelectors) {{
                const btn = document.querySelector(sel);
                if (btn && btn.offsetParent !== null) {{
                    btn.click();
                    return 'CLICKED:' + sel;
                }}
            }}
            const inputSelectors = [
                'div.antigravity-agent-side-panel div[role="textbox"]',
                'div[role="textbox"][contenteditable="true"]',
                'div[contenteditable="true"]'
            ];
            for (const sel of inputSelectors) {{
                const inp = document.querySelector(sel);
                if (inp) {{
                    inp.dispatchEvent(new KeyboardEvent('keydown', {{
                        key: 'Enter', code: 'Enter', keyCode: 13,
                        bubbles: true, cancelable: true
                    }}));
                    inp.dispatchEvent(new KeyboardEvent('keyup', {{
                        key: 'Enter', code: 'Enter', keyCode: 13, bubbles: true
                    }}));
                    return 'ENTER:' + sel;
                }}
            }}
            return 'SEND_FAILED';
        }})()
        """

        result = await self.cdp.evaluate(send_js)
        if result == "SEND_FAILED":
            raise IdeBridgeError("Could not send message — no send button or input found.")

        logger.info("Message sent to %s (method: %s)", self.profile.display_name, result)

    async def get_message_count(self) -> int:
        """Get the current number of assistant messages in the chat."""
        js = f"""
        (() => {{
            const msgs = document.querySelectorAll('{self.profile.assistant_message}');
            return msgs.length;
        }})()
        """
        return await self.cdp.evaluate(js) or 0

    async def is_generating(self) -> bool:
        """Check if the IDE is currently generating a response."""
        if not self.profile.generating_indicator:
            return False
        js = f"""
        (() => {{
            const el = document.querySelector('{self.profile.generating_indicator}');
            if (!el) return false;
            const s = window.getComputedStyle(el);
            return s.display !== 'none' && s.visibility !== 'hidden';
        }})()
        """
        try:
            return bool(await self.cdp.evaluate(js))
        except Exception:
            return False

    async def get_latest_response(self) -> str:
        """Get the text content of the latest assistant message.

        TEAM_002: Uses full LazyGravity-ported RESPONSE_TEXT_SCRIPT that:
        - Iterates backward through all candidate DOM nodes
        - Skips activity logs, thought blocks, feedback, tool output
        - Skips nodes inside excluded containers (details, dialogs, footer)
        - Clones the node and removes <style>/<script> before extracting innerHTML
        - Returns innerHTML which is then converted to clean Telegram text
        """
        raw_html = await self.cdp.evaluate(RESPONSE_TEXT_SCRIPT)
        if not raw_html:
            return ""
        return html_to_telegram(raw_html)

    async def get_full_chat_content(self) -> dict | None:
        """Get structured chat content: process logs + response.

        TEAM_002: Returns {processLogs: [...], response: '...'} where
        processLogs are activity messages and response is the clean AI text.
        Returns None if nothing found.
        """
        data = await self.cdp.evaluate(FULL_CHAT_SCRIPT)
        if not data or not isinstance(data, dict):
            return None
        # Convert responseHtml to formatted text
        raw_html = data.get("responseHtml", "")
        response_text = html_to_telegram(raw_html) if raw_html else ""
        return {
            "processLogs": data.get("processLogs", []),
            "response": response_text,
        }

    # TEAM_004: Structured progress extraction for Telegram progress UI
    async def get_structured_progress(self) -> dict | None:
        """Get structured progress data: files, commands, activity, task status.

        Returns dict with keys: taskName, taskStatus, files, commands,
        activityLogs, isGenerating, responseHtml.
        Returns None if panel not found.
        """
        try:
            data = await self.cdp.evaluate(STRUCTURED_PROGRESS_SCRIPT)
            if not data or not isinstance(data, dict):
                return None
            # Convert responseHtml to formatted Telegram text
            raw_html = data.get("responseHtml", "")
            if raw_html:
                data["responseText"] = html_to_telegram(raw_html)
            else:
                data["responseText"] = ""
            return data
        except Exception as e:
            logger.error("get_structured_progress failed: %s", e)
            return None

    async def _check_stop_button(self) -> bool:
        """Check if the stop/cancel button is present (AI is generating).

        TEAM_002: Ported from LazyGravity's STOP_BUTTON detector.
        """
        try:
            result = await self.cdp.evaluate(STOP_BUTTON_SCRIPT)
            if isinstance(result, dict) and result.get("isGenerating"):
                return True
        except Exception:
            pass
        return False

    async def detect_approval_prompt(self) -> list[dict] | None:
        """Detect active approval prompts inside the side panel.
        
        TEAM_002: Returns structured data about visible approval prompts.
        Each prompt has: header, preview, buttons (list of button texts).
        Returns None if no prompts are active.
        """
        try:
            result = await self.cdp.evaluate(DETECT_PROMPT_SCRIPT)
            if isinstance(result, list) and len(result) > 0:
                return result
        except Exception:
            pass
        return None

    async def click_approval_button(self, button_text: str) -> str | None:
        """Click a specific approval button by text match.
        
        TEAM_002: Used by Telegram callback handlers to click Run/Reject.
        Returns the click result string, or None if button not found.
        """
        try:
            script = _make_click_button_script(button_text)
            result = await self.cdp.evaluate(script)
            if result:
                logger.info("Clicked approval button: %s", result)
                return result
        except Exception as e:
            logger.error("Failed to click approval button '%s': %s", button_text, e)
        return None

    async def _auto_click_approvals(self) -> None:
        """Continuously check for and click Run/Accept/Allow buttons."""
        while self.is_waiting:
            try:
                # TEAM_002: LazyGravity's Execution Context iteration logic.
                # The Run/Reject buttons in Antigravity are inside an iframe/WebView
                # (e.g., 'cascade-panel'). We must run the script in each context.
                contexts = list(self.cdp.get_contexts().values())
                
                # If no contexts are available, just run in the default one
                if not contexts:
                    res = await self.cdp.evaluate(APPROVAL_CLICK_SCRIPT)
                    if res:
                        logger.info("Auto-clicked IDE prompt (default context): %s", res)
                else:
                    # Sort contexts to try 'cascade-panel' and 'Extension' first
                    def ctx_priority(ctx: dict) -> int:
                        url = ctx.get("url", "")
                        name = ctx.get("name", "")
                        if "cascade-panel" in url: return 0
                        if "Extension" in name: return 1
                        return 2
                        
                    contexts.sort(key=ctx_priority)
                    
                    for ctx in contexts:
                        ctx_id = ctx.get("id")
                        if not ctx_id:
                            continue
                        try:
                            res = await self.cdp.evaluate(
                                APPROVAL_CLICK_SCRIPT, 
                                context_id=ctx_id
                            )
                            if res:
                                logger.info("Auto-clicked IDE prompt (ctx %s): %s", ctx.get("name", ctx_id), res)
                                break  # Stop after clicking once
                        except Exception:
                            # Ignore evaluation errors in specific contexts
                            pass

                await asyncio.sleep(2.0)
            except asyncio.CancelledError:
                break
            except Exception as e:
                # We expect regular failures if the IDE is busy
                await asyncio.sleep(2.0)

    async def wait_for_response(self, initial_count: int | None = None) -> str:
        """Wait for the IDE to finish generating a response.

        TEAM_002: LazyGravity-ported response monitor:
        - Polls every 2s (like LazyGravity)
        - Uses stop button to detect generation start/end
        - Completes when stop button disappears 3 consecutive times
        - Auto-clicks Run/Accept/Allow prompts in a background task
        - Captures baseline text to detect new content
        - Max 5 minute timeout

        Args:
            initial_count: Baseline message count before sending.

        Returns:
            The complete response text.

        Raises:
            IdeBridgeError: If response times out.
        """
        # Capture baseline text so we can detect new content
        baseline_text = await self.get_latest_response()

        start = time.time()
        last_text = ""
        stop_gone_count = 0
        generation_started = False
        poll_interval = 2.0  # LazyGravity uses 2s polling
        stop_gone_needed = 3  # Need 3 consecutive "gone" readings

        self.is_waiting = True
        auto_click_task = asyncio.create_task(self._auto_click_approvals())

        try:
            while time.time() - start < self.response_timeout:
                await asyncio.sleep(poll_interval)

                # 1. Check stop button (= is the AI still generating?)
                is_generating = await self._check_stop_button()

                if is_generating:
                    generation_started = True
                    stop_gone_count = 0
                elif generation_started:
                    # Stop button disappeared — count consecutive disappearances
                    stop_gone_count += 1
                    if stop_gone_count >= stop_gone_needed:
                        # AI is done! Extract final text
                        final_text = await self.get_latest_response()
                        if final_text and final_text != baseline_text:
                            return final_text
                        # If text matches baseline, keep waiting briefly
                        if final_text:
                            return final_text

                # 2. Also extract text periodically for progress tracking
                current_text = await self.get_latest_response()
                if current_text and current_text != baseline_text:
                    last_text = current_text
                    if not generation_started:
                        generation_started = True

                # After 15s with no stop button detected, check text changes
                if not generation_started and time.time() - start > 15:
                    if current_text and current_text != baseline_text:
                        generation_started = True

            # Timeout fallback
            if last_text and last_text != baseline_text:
                return last_text + "\n\n⏱️ (response may be incomplete — timed out)"

            raise IdeBridgeError(
                f"No response from {self.profile.display_name} within {self.response_timeout}s. "
                "The AI may not have received the message."
            )
        finally:
            self.is_waiting = False
            auto_click_task.cancel()
            try:
                await auto_click_task
            except asyncio.CancelledError:
                pass

    async def send_and_wait(self, message: str) -> str:
        """Send a message and wait for the complete AI response.

        Args:
            message: The prompt text.

        Returns:
            The AI's complete response text.
        """
        initial_count = await self.get_message_count()
        await self.send_message(message)
        return await self.wait_for_response(initial_count)

    async def stop_generation(self) -> bool:
        """Stop current generation. Returns True if stop button found."""
        if not self.profile.stop_button:
            return False
        js = f"""
        (() => {{
            const btn = document.querySelector('{self.profile.stop_button}');
            if (btn) {{ btn.click(); return true; }}
            return false;
        }})()
        """
        return bool(await self.cdp.evaluate(js))

    async def screenshot(self) -> bytes:
        """Take a screenshot of the IDE window. Returns PNG bytes."""
        return await self.cdp.screenshot()

    async def disconnect(self) -> None:
        """Disconnect from the IDE."""
        await self.cdp.close()

    async def change_model(self, target_model: str) -> bool:
        """Change the active AI model via the IDE's DOM.
        
        Args:
            target_model: A substring of the model name to select (e.g., 'gpt-4o', 'gemini-2.0').
            
        Returns:
            True if successfully clicked the model, False otherwise.
        """
        # 1. Find and click the model selector dropdown button
        click_dropdown_js = """
        (() => {
            const btn = Array.from(document.querySelectorAll('[role="button"]')).find(el => 
                el.textContent.includes('Gemini') || 
                el.textContent.includes('Claude') || 
                el.textContent.includes('GPT') || 
                el.textContent.includes('deepseek') ||
                el.textContent.includes('o1') ||
                el.textContent.includes('o3')
            );
            if (btn) {
                btn.click();
                return true;
            }
            return false;
        })();
        """
        try:
            clicked = await self.cdp.evaluate(click_dropdown_js)
            if not clicked:
                logger.warning("Could not find the model dropdown button.")
                return False
        except Exception as e:
            logger.error("Error clicking model dropdown: %s", e)
            return False
            
        # Give the UI a moment to render the dropdown menu
        await asyncio.sleep(0.5)
        
        # 2. Find and click the specific model option
        # Look for leaf elements (no children) whose text contains the target model string
        click_option_js = f"""
        (() => {{
            const target = "{target_model.lower()}";
            const options = Array.from(document.querySelectorAll('*')).filter(el => 
                el.textContent.toLowerCase().includes(target) && 
                el.children.length === 0
            );
            if (options.length > 0) {{
                options[0].click();
                return true;
            }}
            return false;
        }})();
        """
        try:
            success = await self.cdp.evaluate(click_option_js)
            if not success:
                logger.warning("Could not find model option matching '%s'.", target_model)
                # If we failed, let's close the dropdown by clicking the button again
                await self.cdp.evaluate(click_dropdown_js)
            return success
        except Exception as e:
            logger.error("Error clicking model option: %s", e)
            return False

    async def detect_chat_elements(self) -> dict[str, bool]:
        """Detect which chat UI elements are currently visible.

        Returns:
            Dict of element name -> found (bool).
        """
        p = self.profile
        results = {}
        for name, selector in [
            ("chat_input", p.chat_input),
            ("send_button", p.send_button),
            ("message_container", p.message_container),
            ("assistant_message", p.assistant_message),
            ("generating_indicator", p.generating_indicator),
            ("stop_button", p.stop_button),
        ]:
            if not selector:
                results[name] = False
                continue
            try:
                results[name] = bool(await self.cdp.evaluate(f"!!document.querySelector('{selector}')"))
            except Exception:
                results[name] = False
        return results
