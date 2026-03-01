"""
TEAM_001: Chrome DevTools Protocol manager.
Handles WebSocket connection to Chromium-based IDEs (Antigravity, Cursor, etc.)
launched with --remote-debugging-port.
"""

import asyncio
import base64
import json
import logging
from typing import Any

import aiohttp

logger = logging.getLogger(__name__)

# Fallback ports used only when CDP_PORT is not set in .env
CDP_PORT_CANDIDATES = [9222, 9223, 9333, 9444, 9555, 9666]


class CdpConnectionError(Exception):
    """Raised when CDP connection fails."""


class CdpManager:
    """Low-level Chrome DevTools Protocol connection via WebSocket.

    Connects to a Chromium-based application (Antigravity, Cursor, etc.)
    that was launched with --remote-debugging-port and sends CDP commands.
    """

    def __init__(self, port: int | None = None, max_reconnect_attempts: int = 3) -> None:
        self._port = port
        self._ws: aiohttp.ClientWebSocketResponse | None = None
        self._session: aiohttp.ClientSession | None = None
        self._msg_id = 0
        self._max_reconnect = max_reconnect_attempts
        self._ws_url: str | None = None
        self._pending: dict[int, asyncio.Future] = {}
        self._listener_task: asyncio.Task | None = None
        self._connected = False
        # TEAM_002: Track execution contexts for iframes (like cascade-panel)
        self._contexts: dict[int, dict] = {}

    @property
    def connected(self) -> bool:
        return self._connected and self._ws is not None and not self._ws.closed

    async def connect(self) -> str:
        """Connect to the IDE's CDP endpoint.

        If a specific port was set (via CDP_PORT env var), connects directly.
        Otherwise scans candidate ports for any available IDE.

        Returns:
            The title of the connected target.

        Raises:
            CdpConnectionError: If no IDE is found or connection fails.
        """
        if self._session is None:
            self._session = aiohttp.ClientSession()

        target = None

        if self._port:
            # Dedicated port — go straight to it, no scanning
            target = await self._get_page_target(self._port)
            if not target:
                raise CdpConnectionError(
                    f"Antigravity not found on port {self._port}. "
                    f"Run start_antigravity.bat to launch it on port {self._port}."
                )
        else:
            # Auto-scan fallback (when CDP_PORT not set)
            for port in CDP_PORT_CANDIDATES:
                target = await self._get_page_target(port)
                if target:
                    self._port = port
                    break
            if not target:
                raise CdpConnectionError(
                    f"No IDE found on ports {CDP_PORT_CANDIDATES}. "
                    "Run start_antigravity.bat first."
                )

        self._ws_url = target["webSocketDebuggerUrl"]
        title = target.get("title", "Antigravity")

        logger.info("Connecting to CDP target: %s (port %d)", title, self._port)
        try:
            self._ws = await self._session.ws_connect(self._ws_url)
            self._connected = True
            self._msg_id = 0
            self._pending.clear()
            self._contexts.clear()
            self._listener_task = asyncio.create_task(self._listen())
            
            # TEAM_002: Enable Runtime domain to receive executionContextCreated events
            try:
                await self.send("Runtime.enable")
            except Exception as e:
                logger.warning("Failed to enable Runtime tracking: %s", e)

            logger.info("CDP connected: %s", title)
            return title
        except Exception as e:
            raise CdpConnectionError(f"WebSocket connection failed: {e}")

    def get_contexts(self) -> dict[int, dict]:
        """Return all active JavaScript execution contexts."""
        return self._contexts

    async def _get_page_target(self, port: int) -> dict | None:
        """Get the best IDE page target from a CDP port.

        TEAM_002: Improved target selection ported from LazyGravity's
        cdpService.discoverTarget(). Filters out non-IDE targets like
        Lenovo Vantage, browser widgets, etc. and prefers Antigravity
        workbench pages.
        """
        try:
            async with self._session.get(
                f"http://127.0.0.1:{port}/json",
                timeout=aiohttp.ClientTimeout(total=3),
            ) as resp:
                if resp.status != 200:
                    return None
                targets = await resp.json()
        except Exception:
            return None

        # TEAM_002: Reject known non-IDE targets by URL
        NON_IDE_URL_PATTERNS = [
            "vantage.csw.lenovo.com",  # Lenovo Vantage widget
            "chrome-extension://",
            "devtools://",
            "chrome://",
            "about:blank",
        ]

        def is_ide_target(t: dict) -> bool:
            """Check if a target looks like an IDE page, not some random widget."""
            if t.get("type") != "page":
                return False
            if "webSocketDebuggerUrl" not in t:
                return False
            title = t.get("title", "")
            url = t.get("url", "")
            # Reject non-IDE targets
            if any(pat in url for pat in NON_IDE_URL_PATTERNS):
                return False
            if title == "Launchpad":
                return False
            return True

        def is_workbench_target(t: dict) -> bool:
            """Check if target is specifically an IDE workbench page."""
            url = t.get("url", "")
            title = t.get("title", "")
            # LazyGravity uses 'cascade-panel' keyword
            if "cascade-panel" in url:
                return True
            # Antigravity/Cursor/VS Code workbench pages
            if "workbench" in url.lower():
                return True
            # Title contains workspace info
            if any(kw in title.lower() for kw in ["antigravity", "cursor", "visual studio"]):
                return True
            return False

        # Priority 1: Workbench-specific target
        for t in targets:
            if is_ide_target(t) and is_workbench_target(t):
                logger.info("Found workbench target: %s", t.get("title", "?"))
                return t

        # Priority 2: Any valid IDE page target
        ide_pages = [t for t in targets if is_ide_target(t)]
        if ide_pages:
            logger.info("Found IDE page target: %s", ide_pages[0].get("title", "?"))
            return ide_pages[0]

        # Priority 3: Fall back to any page with websocket (last resort)
        for t in targets:
            if t.get("type") == "page" and "webSocketDebuggerUrl" in t:
                logger.warning("Falling back to non-IDE target: %s (%s)", 
                             t.get("title", "?"), t.get("url", "?")[:60])
                return t

        return None

    async def _listen(self) -> None:
        """Background listener for WebSocket messages from the IDE."""
        try:
            async for msg in self._ws:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    data = json.loads(msg.data)
                    msg_id = data.get("id")
                    method = data.get("method")
                    
                    if msg_id is not None and msg_id in self._pending:
                        self._pending[msg_id].set_result(data)
                        
                    # TEAM_002: Track execution contexts
                    elif method == "Runtime.executionContextCreated":
                        ctx = data.get("params", {}).get("context", {})
                        ctx_id = ctx.get("id")
                        if ctx_id is not None:
                            self._contexts[ctx_id] = ctx
                            logger.debug("CDP Context added: %s (%s)", ctx.get("name"), ctx.get("url"))
                            
                    elif method == "Runtime.executionContextDestroyed":
                        ctx_id = data.get("params", {}).get("executionContextId")
                        if ctx_id is not None and ctx_id in self._contexts:
                            del self._contexts[ctx_id]
                            
                elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                    break
        except Exception as e:
            logger.warning("CDP listener error: %s", e)
        finally:
            self._connected = False
            logger.warning("CDP connection lost")

    async def send(self, method: str, params: dict | None = None) -> dict:
        """Send a CDP command and wait for the response.

        Args:
            method: CDP method name (e.g., "Runtime.evaluate").
            params: Optional parameters dict.

        Returns:
            The CDP response dict.
        """
        if not self.connected:
            await self._reconnect()

        self._msg_id += 1
        msg_id = self._msg_id
        message: dict = {"id": msg_id, "method": method}
        if params:
            message["params"] = params

        future: asyncio.Future = asyncio.get_event_loop().create_future()
        self._pending[msg_id] = future
        
        # TEAM_002: Start asyncio future BEFORE sending
        try:
            await self._ws.send_json(message)
            result = await asyncio.wait_for(future, timeout=30)
            return result
        except asyncio.TimeoutError:
            self._pending.pop(msg_id, None)
            raise CdpConnectionError(f"CDP command timed out: {method}")
        except Exception as e:
            self._pending.pop(msg_id, None)
            raise CdpConnectionError(f"CDP command failed: {e}")

    async def evaluate(
        self, expression: str, await_promise: bool = False, context_id: int | None = None
    ) -> Any:
        """Execute JavaScript in the IDE's page context.

        Args:
            expression: JavaScript expression to evaluate.
            await_promise: If True, waits for promise resolution.
            context_id: Optional execution context ID (e.g. for iframes).

        Returns:
            The evaluation result value.
        """
        params: dict[str, Any] = {"expression": expression, "returnByValue": True}
        if await_promise:
            params["awaitPromise"] = True
        if context_id is not None:
            params["contextId"] = context_id

        result = await self.send("Runtime.evaluate", params)

        if "error" in result:
            raise CdpConnectionError(f"JS evaluation error: {result['error']}")

        js_result = result.get("result", {}).get("result", {})
        if js_result.get("subtype") == "error":
            raise CdpConnectionError(f"JS error: {js_result.get('description', 'Unknown')}")

        return js_result.get("value")

    async def screenshot(self) -> bytes:
        """Capture a screenshot of the IDE window. Returns PNG bytes."""
        result = await self.send("Page.captureScreenshot", {"format": "png"})
        data = result.get("result", {}).get("data", "")
        return base64.b64decode(data)

    async def _reconnect(self) -> None:
        """Attempt to reconnect to the CDP endpoint."""
        for attempt in range(1, self._max_reconnect + 1):
            logger.info("CDP reconnect attempt %d/%d", attempt, self._max_reconnect)
            try:
                await self.disconnect()
                await asyncio.sleep(2)
                await self.connect()
                return
            except Exception:
                if attempt == self._max_reconnect:
                    raise CdpConnectionError(
                        "All reconnect attempts failed. "
                        "Is Antigravity still running with --remote-debugging-port?"
                    )

    async def disconnect(self) -> None:
        """Close the CDP WebSocket connection."""
        self._connected = False
        self._contexts.clear()
        if self._listener_task and not self._listener_task.done():
            self._listener_task.cancel()
            try:
                await self._listener_task
            except asyncio.CancelledError:
                pass
        if self._ws and not self._ws.closed:
            await self._ws.close()
        self._ws = None
        self._pending.clear()

    async def close(self) -> None:
        """Close connection and release all resources."""
        await self.disconnect()
        if self._session and not self._session.closed:
            await self._session.close()
        self._session = None
