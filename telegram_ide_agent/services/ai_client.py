"""
TEAM_001: AI client service — CDP Bridge edition.
Routes all AI requests through the IDE's own chat interface via CDP.
No external API keys needed — uses whatever model the IDE is running.
"""

import logging
from dataclasses import dataclass, field

from telegram_ide_agent.services.ide_bridge import IdeBridge, IdeBridgeError

logger = logging.getLogger(__name__)


@dataclass
class SessionContext:
    """Per-user session tracking."""
    ide_profile: str = "antigravity"


class AIClient:
    """AI client that routes prompts through the IDE via CDP.

    Instead of calling OpenAI/Anthropic/Google APIs directly, this client
    sends prompts to the IDE's chat interface and reads back the responses.
    The AI model used is whatever the IDE is configured to use.
    """

    def __init__(self, ide_bridge: IdeBridge) -> None:
        self.bridge = ide_bridge
        self._sessions: dict[int, SessionContext] = {}

    def get_session(self, user_id: int) -> SessionContext:
        """Get or create a session for a user."""
        if user_id not in self._sessions:
            self._sessions[user_id] = SessionContext(
                ide_profile=self.bridge.profile.name
            )
        return self._sessions[user_id]

    @property
    def connected(self) -> bool:
        return self.bridge.cdp.connected

    @property
    def ide_name(self) -> str:
        return self.bridge.ide_name

    async def connect(self) -> str:
        """Connect to the IDE. Returns the IDE window title."""
        return await self.bridge.connect()

    async def chat(self, user_id: int, message: str) -> str:
        """Send a prompt to the IDE and get the AI response.

        Args:
            user_id: Telegram user ID.
            message: The prompt text.

        Returns:
            The AI's response text.
        """
        if not self.bridge.cdp.connected:
            try:
                await self.bridge.connect()
            except Exception as e:
                return (
                    f"❌ Cannot connect to {self.bridge.profile.display_name}.\n\n"
                    f"Error: {e}\n\n"
                    "Make sure the IDE is running with CDP enabled:\n"
                    "`/ide_open` to launch it, or start it manually with "
                    "`--remote-debugging-port=9222`"
                )

        try:
            return await self.bridge.send_and_wait(message)
        except IdeBridgeError as e:
            return f"❌ IDE error: {e}"
        except Exception as e:
            logger.exception("Unexpected error in AI chat")
            return f"❌ Unexpected error: {e}"

    async def chat_with_file(
        self, user_id: int, prompt: str, file_content: str, filename: str
    ) -> str:
        """Send a prompt with file context to the IDE.

        Formats the message with file content so the IDE's AI has context.

        Args:
            user_id: Telegram user ID.
            prompt: User's instruction/question.
            file_content: Content of the file.
            filename: Name of the file for context.

        Returns:
            The AI's response text.
        """
        full_message = (
            f"Here is the file `{filename}`:\n"
            f"```\n{file_content}\n```\n\n"
            f"{prompt}"
        )
        return await self.chat(user_id, full_message)

    async def change_model(self, user_id: int, model_name: str) -> str:
        """Change the active AI model in the IDE.
        
        Args:
            user_id: Telegram user ID.
            model_name: Substring of the desired model (e.g., 'claude-3-5', 'gpt-4o').
            
        Returns:
            A status message to show the user.
        """
        if not self.bridge.cdp.connected:
            try:
                await self.bridge.connect()
            except Exception as e:
                return f"❌ Cannot connect to {self.bridge.profile.display_name}. Make sure it's running."

        try:
            success = await self.bridge.change_model(model_name)
            if success:
                return f"✅ Successfully changed model to one matching `{model_name}` in the IDE."
            else:
                return (
                    f"⚠️ Could not find or click a model matching `{model_name}`.\n"
                    "Make sure the Antigravity chat panel is open and the model dropdown is visible."
                )
        except Exception as e:
            logger.exception("Unexpected error changing model")
            return f"❌ Error changing model: {e}"

    async def stop(self) -> bool:
        """Stop the current generation."""
        return await self.bridge.stop_generation()

    async def screenshot(self) -> bytes | None:
        """Take a screenshot of the IDE."""
        try:
            return await self.bridge.screenshot()
        except Exception as e:
            logger.error("Screenshot failed: %s", e)
            return None

    async def status(self) -> dict:
        """Get connection status info."""
        connected = self.bridge.cdp.connected
        result = {
            "connected": connected,
            "ide_profile": self.bridge.profile.display_name,
            "ide_title": self.bridge.ide_name,
        }

        if connected:
            try:
                elements = await self.bridge.detect_chat_elements()
                result["chat_elements"] = elements
            except Exception:
                result["chat_elements"] = {}

        return result

    async def disconnect(self) -> None:
        """Disconnect from the IDE."""
        await self.bridge.disconnect()
