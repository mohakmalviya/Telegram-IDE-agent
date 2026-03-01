"""
TEAM_001: AI assistant command handlers — CDP Bridge edition.
Routes prompts through the IDE's own AI via Chrome DevTools Protocol.
Handles /ai, /ai_edit, /ai_explain, /ai_clear, /ide_status, /ide_connect,
/screenshot, /stop, /ide_profile.

TEAM_002: Added inline keyboard approval buttons for Run/Reject prompts.
"""

import asyncio
import html
import logging
import time

from aiogram import Router, F
from aiogram.types import (
    Message, BufferedInputFile, CallbackQuery,
    InlineKeyboardMarkup, InlineKeyboardButton,
)
from aiogram.filters import Command

from telegram_ide_agent.services.ai_client import AIClient
from telegram_ide_agent.services.file_manager import FileManager, PathSecurityError
from telegram_ide_agent.services.ide_bridge import IDE_PROFILES, IdeBridgeError
from telegram_ide_agent.utils.formatting import escape_md, code_block, truncate
from telegram_ide_agent.utils.progress_formatter import (
    format_status_header,
    format_activity_log,
    format_final_response,
)

logger = logging.getLogger(__name__)

router = Router(name="ai_assistant")

# TEAM_002: Track pending approval messages so callbacks can find the bridge
_pending_approvals: dict[str, AIClient] = {}  # msg_id -> ai_client


def _make_approval_keyboard(buttons: list[str]) -> InlineKeyboardMarkup:
    """Build an inline keyboard from approval button texts.
    
    Maps button texts to emojis and callback data.
    """
    kb_buttons = []
    for btn_text in buttons:
        lower = btn_text.lower()
        # Choose emoji based on button type
        if any(k in lower for k in ['run', 'accept', 'allow', 'apply', 'confirm', 'continue', 'submit']):
            emoji = "✅"
        elif any(k in lower for k in ['reject', 'deny', 'cancel']):
            emoji = "❌"
        else:
            emoji = "🔘"
        
        # Clean the display text (remove keyboard shortcuts like Alt+⏎)
        display = btn_text
        for suffix in ['Alt+⏎', 'Ctrl+⏎', 'Alt+↵', 'Ctrl+↵']:
            display = display.replace(suffix, '').strip()
        
        kb_buttons.append(
            InlineKeyboardButton(
                text=f"{emoji} {display}",
                callback_data=f"approve:{btn_text[:50]}",
            )
        )
    
    return InlineKeyboardMarkup(inline_keyboard=[kb_buttons])


@router.callback_query(F.data.startswith("approve:"))
async def on_approval_callback(callback: CallbackQuery, ai_client: AIClient) -> None:
    """Handle inline button clicks for Run/Reject/Accept etc."""
    button_text = callback.data[len("approve:"):]
    
    result = await ai_client.bridge.click_approval_button(button_text)
    
    if result:
        await callback.answer(f"Clicked: {button_text}")
        # Edit the approval message to show it was handled
        try:
            lower = button_text.lower()
            if any(k in lower for k in ['reject', 'deny', 'cancel']):
                await callback.message.edit_text(f"❌ Rejected: {button_text}")
            else:
                await callback.message.edit_text(f"✅ Approved: {button_text}")
        except Exception:
            pass
    else:
        await callback.answer("⚠️ Button no longer available", show_alert=True)


@router.message(Command("ai"))
async def cmd_ai(message: Message, ai_client: AIClient) -> None:
    """Send a coding prompt to the IDE's AI assistant.

    TEAM_004: Sends structured progress updates via 3 Telegram messages:
    1. Status header (live-updating)
    2. Activity log (files, commands, progress)
    3. Final response (when complete)
    """
    args = (message.text or "").split(maxsplit=1)
    if len(args) < 2:
        await message.answer(
            "Usage: `/ai <prompt>`\n\n"
            "Example: `/ai write a Python function to merge two sorted lists`\n\n"
            "_This sends your prompt directly to the IDE's AI\\._",
            parse_mode="MarkdownV2",
        )
        return

    prompt = args[1]

    # TEAM_004: Message 1 — status header (will be edited in-place)
    status_msg = await message.answer(
        format_status_header(prompt, 0, None),
        parse_mode="HTML",
    )

    # TEAM_004: Message 2 — activity log (will be edited in-place)
    activity_msg = await message.answer(
        "\u23f3 <i>Waiting for activity...</i>",
        parse_mode="HTML",
    )

    bridge = ai_client.bridge

    if not bridge.cdp.connected:
        try:
            await bridge.connect()
        except Exception as e:
            await status_msg.edit_text(
                f"\u274c Cannot connect to {bridge.profile.display_name}.\n\n"
                f"Error: {e}\n\nUse /ide_connect to reconnect."
            )
            return

    try:
        await bridge.send_message(prompt)
    except IdeBridgeError as e:
        await status_msg.edit_text(f"\u274c Failed to send: {e}")
        return

    # ── TEAM_004: Structured progress polling loop ──
    start = time.time()
    stop_gone_count = 0
    generation_started = False
    poll_interval = 3.0
    stop_gone_needed = 3
    timeout = bridge.response_timeout
    sent_prompt_msgs: list[Message] = []
    response = ""
    last_activity_html = ""

    bridge.is_waiting = True
    # TEAM_002: Still run auto-click as fallback for non-critical prompts
    auto_click_task = asyncio.create_task(bridge._auto_click_approvals())
    seen_prompts: set[str] = set()

    try:
        while time.time() - start < timeout:
            await asyncio.sleep(poll_interval)
            elapsed = time.time() - start

            # ── Poll structured progress ──
            progress = await bridge.get_structured_progress()

            # ── Update Message 1: Status header ──
            try:
                new_header = format_status_header(prompt, elapsed, progress)
                await status_msg.edit_text(new_header, parse_mode="HTML")
            except Exception:
                pass  # Telegram may reject if text unchanged

            # ── Update Message 2: Activity log ──
            if progress:
                try:
                    new_activity = format_activity_log(progress)
                    if new_activity != last_activity_html:
                        last_activity_html = new_activity
                        await activity_msg.edit_text(new_activity, parse_mode="HTML")
                except Exception:
                    pass

            # ── Check for approval prompts → inline keyboards ──
            try:
                prompts = await bridge.detect_approval_prompt()
                if prompts:
                    for prompt_info in prompts:
                        prompt_key = (
                            f"{prompt_info.get('header','')}-"
                            f"{prompt_info.get('preview','')[:50]}"
                        )
                        if prompt_key not in seen_prompts:
                            seen_prompts.add(prompt_key)
                            header = prompt_info.get("header", "Approval needed")
                            preview = prompt_info.get("preview", "")
                            buttons = prompt_info.get("buttons", [])
                            if not buttons:
                                continue
                            msg_text = f"\U0001f514 *{escape_md(header)}*"
                            if preview:
                                msg_text += f"\n```\n{preview[:500]}\n```"
                            try:
                                kb = _make_approval_keyboard(buttons)
                                approval_msg = await message.answer(
                                    msg_text,
                                    parse_mode="MarkdownV2",
                                    reply_markup=kb,
                                )
                                sent_prompt_msgs.append(approval_msg)
                            except Exception:
                                try:
                                    kb = _make_approval_keyboard(buttons)
                                    txt = f"\U0001f514 {header}"
                                    if preview:
                                        txt += f"\n{preview[:500]}"
                                    approval_msg = await message.answer(
                                        txt, reply_markup=kb
                                    )
                                    sent_prompt_msgs.append(approval_msg)
                                except Exception:
                                    pass
            except Exception:
                pass

            # ── Check generation status ──
            is_generating = (
                progress.get("isGenerating", False)
                if progress
                else await bridge._check_stop_button()
            )

            if is_generating:
                generation_started = True
                stop_gone_count = 0
            elif generation_started:
                stop_gone_count += 1
                if stop_gone_count >= stop_gone_needed:
                    # Generation finished — grab final response
                    if progress and progress.get("responseText"):
                        response = progress["responseText"]
                    else:
                        response = await bridge.get_latest_response() or ""
                    break

            if not generation_started and elapsed > 15:
                if progress and (
                    progress.get("files")
                    or progress.get("commands")
                    or progress.get("activityLogs")
                ):
                    generation_started = True
        else:
            # Timeout
            if progress and progress.get("responseText"):
                response = progress["responseText"] + "\n\n\u23f1\ufe0f (may be incomplete)"
            else:
                final = await bridge.get_latest_response() or ""
                if final:
                    response = final + "\n\n\u23f1\ufe0f (may be incomplete)"
                else:
                    response = (
                        f"\u23f1\ufe0f No response from {bridge.profile.display_name} "
                        f"within {timeout}s."
                    )
    finally:
        bridge.is_waiting = False
        auto_click_task.cancel()
        try:
            await auto_click_task
        except asyncio.CancelledError:
            pass

    # ── TEAM_004: Update status to complete ──
    elapsed = time.time() - start
    try:
        final_header = format_status_header(prompt, elapsed, progress)
        # Replace the generating state with complete
        final_header = final_header.replace(
            "\u26a1 Generating...", "\u2705 Complete"
        )
        await status_msg.edit_text(final_header, parse_mode="HTML")
    except Exception:
        pass

    # ── TEAM_004: Message 3 — send the final response ──
    if response:
        formatted = format_final_response(response)
        try:
            await message.answer(formatted, parse_mode="HTML")
        except Exception:
            try:
                await message.answer(truncate(response, 4000))
            except Exception:
                await message.answer(truncate(response, 2000))



@router.message(Command("ai_edit"))
async def cmd_ai_edit(
    message: Message, ai_client: AIClient, file_manager: FileManager, user_cwd: dict
) -> None:
    """Ask the IDE's AI to edit a specific file."""
    args = (message.text or "").split(maxsplit=2)
    if len(args) < 3:
        await message.answer(
            "Usage: `/ai_edit <file> <prompt>`\n\n"
            "Example: `/ai_edit app\\.py add error handling to all routes`",
            parse_mode="MarkdownV2",
        )
        return

    filename = args[1]
    prompt = args[2]
    user_id = message.from_user.id
    cwd = user_cwd.get(user_id, file_manager.workspace_root)

    try:
        filepath = file_manager.resolve(filename, cwd)
    except PathSecurityError:
        await message.answer("⛔ Access denied\\.", parse_mode="MarkdownV2")
        return

    if not filepath.exists():
        await message.answer(f"❌ File not found: `{escape_md(filename)}`", parse_mode="MarkdownV2")
        return

    if file_manager.is_binary(filepath):
        await message.answer("❌ Cannot process binary files\\.", parse_mode="MarkdownV2")
        return

    content = await file_manager.read_file(filepath)

    ide_name = escape_md(ai_client.ide_name)
    status_msg = await message.answer(
        f"🤖 _Editing `{escape_md(filename)}` via {ide_name}_\\.\\.\\.",
        parse_mode="MarkdownV2",
    )

    edit_prompt = (
        f"Edit the following file according to the instruction.\n"
        f"Return ONLY the complete updated file content, no explanations.\n\n"
        f"Instruction: {prompt}"
    )

    response = await ai_client.chat_with_file(user_id, edit_prompt, content, filename)

    # Try to extract code from markdown code blocks
    new_content = _extract_code(response)

    try:
        await file_manager.write_file(filepath, new_content)
        await status_msg.edit_text(
            f"✅ Updated `{escape_md(filename)}` via {ide_name}\\.\n\n"
            f"Use `/cat {escape_md(filename)}` to review the changes\\.",
            parse_mode="MarkdownV2",
        )
    except Exception as e:
        await status_msg.edit_text(f"❌ Error saving: {escape_md(str(e))}", parse_mode="MarkdownV2")


@router.message(Command("ai_explain"))
async def cmd_ai_explain(
    message: Message, ai_client: AIClient, file_manager: FileManager, user_cwd: dict
) -> None:
    """Ask the IDE's AI to explain a file."""
    args = (message.text or "").split(maxsplit=1)
    if len(args) < 2:
        await message.answer("Usage: `/ai_explain <file>`", parse_mode="MarkdownV2")
        return

    filename = args[1]
    user_id = message.from_user.id
    cwd = user_cwd.get(user_id, file_manager.workspace_root)

    try:
        filepath = file_manager.resolve(filename, cwd)
    except PathSecurityError:
        await message.answer("⛔ Access denied\\.", parse_mode="MarkdownV2")
        return

    if not filepath.exists():
        await message.answer(f"❌ File not found: `{escape_md(filename)}`", parse_mode="MarkdownV2")
        return

    if file_manager.is_binary(filepath):
        await message.answer("❌ Cannot explain binary files\\.", parse_mode="MarkdownV2")
        return

    content = await file_manager.read_file(filepath)

    ide_name = escape_md(ai_client.ide_name)
    status_msg = await message.answer(
        f"🤖 _Analyzing `{escape_md(filename)}` via {ide_name}_\\.\\.\\.",
        parse_mode="MarkdownV2",
    )

    response = await ai_client.chat_with_file(
        user_id,
        "Explain what this file does. Be concise but thorough. "
        "Cover: purpose, key functions/classes, dependencies, and any notable patterns.",
        content,
        filename,
    )

    try:
        truncated = truncate(response, 4000)
        await status_msg.edit_text(truncated, parse_mode="Markdown")
    except Exception:
        try:
            await status_msg.edit_text(escape_md(truncate(response, 4000)), parse_mode="MarkdownV2")
        except Exception:
            await status_msg.edit_text(truncate(response, 4000))


# ─── IDE Control Commands ─────────────────────────────────────────

@router.message(Command("ide_status", "status"))
async def cmd_ide_status(message: Message, ai_client: AIClient) -> None:
    """Show IDE connection status and detected chat elements."""
    status = await ai_client.status()

    connected = "🟢 Connected" if status["connected"] else "🔴 Disconnected"
    lines = [
        f"*IDE Status*",
        f"Connection: {escape_md(connected)}",
        f"Profile: {escape_md(status['ide_profile'])}",
        f"Window: {escape_md(status.get('ide_title', 'N/A'))}",
    ]

    elements = status.get("chat_elements", {})
    if elements:
        lines.append("")
        lines.append("*Chat Elements:*")
        for name, found in elements.items():
            icon = "✅" if found else "❌"
            lines.append(f"  {icon} {escape_md(name)}")

    if not status["connected"]:
        lines.append("")
        lines.append("_Use /ide\\_connect to connect\\._")

    await message.answer("\n".join(lines), parse_mode="MarkdownV2")


@router.message(Command("ide_connect"))
async def cmd_ide_connect(message: Message, ai_client: AIClient) -> None:
    """Connect or reconnect to the IDE."""
    status_msg = await message.answer("🔌 Connecting to IDE\\.\\.\\.", parse_mode="MarkdownV2")

    try:
        title = await ai_client.connect()
        await status_msg.edit_text(
            f"🟢 Connected to: *{escape_md(title)}*",
            parse_mode="MarkdownV2",
        )
    except Exception as e:
        await status_msg.edit_text(
            f"❌ Connection failed: {escape_md(str(e))}\n\n"
            "Make sure your IDE is running with CDP enabled\\.\n"
            "Use `/ide_open` to launch it, or start manually with:\n"
            "`\\-\\-remote\\-debugging\\-port=9222`",
            parse_mode="MarkdownV2",
        )


@router.message(Command("screenshot"))
async def cmd_screenshot(message: Message, ai_client: AIClient) -> None:
    """Capture and send a screenshot of the IDE."""
    if not ai_client.connected:
        await message.answer("❌ Not connected to IDE\\. Use /ide\\_connect first\\.", parse_mode="MarkdownV2")
        return

    status_msg = await message.answer("📸 Capturing\\.\\.\\.", parse_mode="MarkdownV2")

    img_data = await ai_client.screenshot()
    if img_data:
        doc = BufferedInputFile(img_data, filename="ide_screenshot.png")
        await message.answer_photo(doc, caption=f"📸 {ai_client.ide_name}")
        await status_msg.delete()
    else:
        await status_msg.edit_text("❌ Screenshot failed\\.", parse_mode="MarkdownV2")


@router.message(Command("stop"))
async def cmd_stop(message: Message, ai_client: AIClient) -> None:
    """Stop the current AI generation in the IDE."""
    if not ai_client.connected:
        await message.answer("❌ Not connected to IDE\\.", parse_mode="MarkdownV2")
        return

    stopped = await ai_client.stop()
    if stopped:
        await message.answer("🛑 Generation stopped\\.", parse_mode="MarkdownV2")
    else:
        await message.answer("⚠️ Could not find stop button\\.", parse_mode="MarkdownV2")


@router.message(Command("ide_profile"))
async def cmd_ide_profile(message: Message) -> None:
    """Show available IDE profiles."""
    lines = ["*Available IDE Profiles:*\n"]
    for key, profile in IDE_PROFILES.items():
        lines.append(f"  • `{escape_md(key)}` — {escape_md(profile.display_name)}")

    lines.append("")
    lines.append("_Set profile in `\\.env` with `IDE\\_PROFILE=<name>`_")

    await message.answer("\n".join(lines), parse_mode="MarkdownV2")


@router.message(Command("ai_clear"))
async def cmd_ai_clear(message: Message) -> None:
    """Note about clearing context in CDP mode."""
    await message.answer(
        "ℹ️ In CDP mode, conversation context is managed by the IDE itself\\.\n"
        "To start a fresh conversation, use the IDE's own new chat feature,\n"
        "or send `/ai start a new conversation`\\.",
        parse_mode="MarkdownV2",
    )


@router.message(Command("model"))
async def cmd_model(message: Message, ai_client: AIClient) -> None:
    """Change the active AI model in the IDE."""
    args = (message.text or "").split(maxsplit=1)
    if len(args) < 2:
        await message.answer(
            "Usage: `/model <name>`\n\n"
            "Example: `/model claude-3-5` or `/model gpt-4o`\n\n"
            "_This attempts to open the model dropdown in the IDE and select the specified model\\._",
            parse_mode="MarkdownV2",
        )
        return

    model_name = args[1].strip()
    user_id = message.from_user.id

    status_msg = await message.answer(
        f"🔄 Changing model to `{escape_md(model_name)}`\\.\\.\\.",
        parse_mode="MarkdownV2",
    )

    response = await ai_client.change_model(user_id, model_name)
    await status_msg.edit_text(escape_md(response), parse_mode="MarkdownV2")


def _extract_code(text: str) -> str:
    """Extract code from markdown code blocks in AI response."""
    import re
    pattern = r"```(?:\w+)?\n(.*?)```"
    matches = re.findall(pattern, text, re.DOTALL)
    if matches:
        return max(matches, key=len).strip()
    return text.strip()


# ─── TEAM_002: Live Debug Mirror ─────────────────────────────────
# Background task that continuously polls the IDE chat DOM and
# forwards all content to a Telegram chat for debugging.

_debug_task: asyncio.Task | None = None
_debug_chat_id: int | None = None


async def _debug_mirror_loop(
    ai_client: AIClient,
    chat_id: int,
    bot,
) -> None:
    """Background loop: poll IDE chat every 3s, forward structured progress.

    TEAM_004: Uses structured progress extraction and Telegram HTML formatting.
    Maintains 2 live-editing messages: status header + activity log.
    """
    bridge = ai_client.bridge
    last_prompts: str = ""
    poll_interval = 3.0

    # Connect to IDE if not already
    if not bridge.cdp.connected:
        try:
            await bridge.connect()
        except Exception as e:
            await bot.send_message(chat_id, f"\u274c Debug mirror: can't connect to IDE: {e}")
            return

    # TEAM_004: Send 2 messages — status header + activity log
    status_msg = await bot.send_message(
        chat_id,
        "\U0001f50d <b>Debug Mirror Active</b>\n" + "\u2501" * 20 + "\n\u23f3 Watching...",
        parse_mode="HTML",
    )
    activity_msg = await bot.send_message(
        chat_id,
        "\u23f3 <i>Waiting for activity...</i>",
        parse_mode="HTML",
    )

    last_status_text = ""
    last_activity_text = ""
    start = time.time()
    was_generating = False
    last_response_sent = ""

    while True:
        try:
            await asyncio.sleep(poll_interval)
            elapsed = time.time() - start

            # Poll structured progress
            progress = await bridge.get_structured_progress()

            # Update status header
            try:
                new_status = format_status_header("Debug Mirror", elapsed, progress)
                if new_status != last_status_text:
                    last_status_text = new_status
                    await status_msg.edit_text(new_status, parse_mode="HTML")
            except Exception:
                pass

            # Update activity log
            if progress:
                try:
                    new_activity = format_activity_log(progress)
                    if new_activity != last_activity_text:
                        last_activity_text = new_activity
                        await activity_msg.edit_text(new_activity, parse_mode="HTML")
                except Exception:
                    pass

            # TEAM_004: Detect generation complete → send final response
            if progress:
                is_gen = progress.get("isGenerating", False)
                resp = progress.get("responseText", "")
                if was_generating and not is_gen and resp and resp != last_response_sent:
                    last_response_sent = resp
                    try:
                        formatted = format_final_response(resp)
                        await bot.send_message(chat_id, formatted, parse_mode="HTML")
                    except Exception:
                        try:
                            await bot.send_message(chat_id, truncate(resp, 4000))
                        except Exception:
                            pass
                was_generating = is_gen

            # Check for approval prompts (get their own messages with buttons)
            try:
                prompts = await bridge.detect_approval_prompt()
                if prompts:
                    prompts_key = str(prompts)
                    if prompts_key != last_prompts:
                        last_prompts = prompts_key
                        for p in prompts:
                            header = p.get("header", "Approval needed")
                            preview = p.get("preview", "")
                            buttons = p.get("buttons", [])

                            txt = f"<blockquote>\U0001f514 <b>{html.escape(header)}</b>"
                            if preview:
                                txt += f"\n<code>{html.escape(preview[:500])}</code>"
                            txt += "</blockquote>"

                            if buttons:
                                kb = _make_approval_keyboard(buttons)
                                await bot.send_message(
                                    chat_id, txt,
                                    parse_mode="HTML",
                                    reply_markup=kb,
                                )
                            else:
                                await bot.send_message(
                                    chat_id, txt, parse_mode="HTML"
                                )
                else:
                    last_prompts = ""
            except Exception:
                pass

        except asyncio.CancelledError:
            await bot.send_message(chat_id, "\U0001f50d Debug mirror stopped.")
            return
        except Exception as e:
            logger.debug("Debug mirror error: %s", e)


@router.message(Command("debug_on"))
async def cmd_debug_on(message: Message, ai_client: AIClient) -> None:
    """Start live mirror of IDE chat to Telegram for debugging."""
    global _debug_task, _debug_chat_id

    if _debug_task and not _debug_task.done():
        await message.answer("🔍 Debug mirror is already running. Use /debug_off to stop.")
        return

    _debug_chat_id = message.chat.id
    _debug_task = asyncio.create_task(
        _debug_mirror_loop(ai_client, message.chat.id, message.bot)
    )
    # The start message is sent inside _debug_mirror_loop


@router.message(Command("debug_off"))
async def cmd_debug_off(message: Message) -> None:
    """Stop live debug mirror."""
    global _debug_task, _debug_chat_id

    if _debug_task and not _debug_task.done():
        _debug_task.cancel()
        _debug_task = None
        _debug_chat_id = None
        # Cancel message is sent inside the loop's CancelledError handler
    else:
        await message.answer("🔍 Debug mirror is not running.")
