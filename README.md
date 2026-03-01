# 🚀 Telegram IDE Agent

A Telegram bot that lets you remotely operate your AI IDE (Antigravity, Cursor, VS Code, Windsurf) from anywhere — using the IDE's own AI models, zero API keys needed.

## How It Works

```
┌──────────────┐         ┌──────────────┐         ┌──────────────┐
│  Telegram    │  HTTP   │  This Bot    │   CDP   │  Your IDE    │
│  (Phone)     │◄──────►│  (Python)    │◄──────►│  (Antigravity)│
│              │ Bot API │              │WebSocket│              │
└──────────────┘         └──────────────┘         └──────────────┘
```

1. You send a message in Telegram
2. The bot receives it and connects to your IDE via **Chrome DevTools Protocol (CDP)**
3. It injects your prompt into the IDE's chat input
4. The IDE's AI processes it (using whatever model it's configured with)
5. The bot reads the response from the IDE and sends it back to Telegram

**No API keys needed** — the AI model is whatever your IDE subscription provides.

## Features

- 📂 **File Operations** — Browse, read, edit, create, delete, upload/download files
- 💻 **Terminal** — Execute shell commands remotely with timeout & safety checks
- 🤖 **IDE AI Bridge** — Send prompts to Antigravity/Cursor/VS Code/Windsurf's AI
- 📸 **Screenshots** — Capture the IDE window from Telegram
- 🔒 **Secure** — User ID whitelist, path sandboxing, dangerous command confirmation
- 🔍 **Search** — Grep-like search across your codebase
- 🌳 **Tree View** — Visual directory tree

## Quick Start

### 1. Prerequisites
- Python 3.11+
- A Telegram Bot Token ([@BotFather](https://t.me/BotFather))
- An IDE with CDP support (Antigravity, Cursor, VS Code, etc.)

### 2. Install

```bash
cd Telegram_agent
python -m venv venv
venv\Scripts\activate        # Windows
# source venv/bin/activate   # Linux/Mac
pip install -r requirements.txt
```

### 3. Configure

Edit `.env`:

```env
BOT_TOKEN=your_telegram_bot_token
ALLOWED_USER_IDS=your_telegram_user_id
WORKSPACE_ROOT=/path/to/your/projects
IDE_PROFILE=antigravity    # or: cursor, vscode, windsurf
```

### 4. Launch IDE with CDP

**Option A** — Use the included launcher:
```bash
start_antigravity.bat       # Windows
```

**Option B** — Launch manually:
```bash
Antigravity.exe --remote-debugging-port=9222
# or for Cursor:
Cursor.exe --remote-debugging-port=9222
# or for VS Code:
code --remote-debugging-port=9222
```

### 5. Start the Bot

```bash
python -m telegram_ide_agent.bot
```

Open Telegram → find your bot → send `/start` 🎉

## Commands

| Command | Description |
|---------|-------------|
| **File Operations** | |
| `/files` | List directory contents |
| `/cat <file>` | Read file (with optional line range) |
| `/edit <file>` | Interactive file editor |
| `/touch <file>` | Create empty file |
| `/mkdir <dir>` | Create directory |
| `/rm <path>` | Delete (with confirmation) |
| `/download <file>` | Download file as document |
| `/upload` | Upload — send a document |
| `/search <query>` | Search in files |
| `/tree` | Directory tree view |
| **Navigation** | |
| `/cd <path>` | Change directory |
| `/pwd` | Print working directory |
| **Terminal** | |
| `/run <cmd>` | Execute shell command |
| `/git <args>` | Git shortcut |
| `/pip <args>` | Pip shortcut |
| `/npm <args>` | NPM shortcut |
| **AI (via IDE)** | |
| `/ai <prompt>` | Send prompt to IDE's AI |
| `/ai_edit <file> <prompt>` | AI-powered file editing |
| `/ai_explain <file>` | AI explains a file |
| `/stop` | Stop current generation |
| **IDE Control** | |
| `/ide_status` | Connection status & diagnostics |
| `/ide_connect` | Connect/reconnect to IDE |
| `/ide_profile` | Show supported IDE profiles |
| `/screenshot` | Capture IDE window |

## Supported IDEs

| Profile | IDE | Status |
|---------|-----|--------|
| `antigravity` | Antigravity | ✅ Primary |
| `cursor` | Cursor | ✅ Supported |
| `vscode` | VS Code (Copilot Chat) | ✅ Supported |
| `windsurf` | Windsurf | ✅ Supported |

Set your IDE in `.env` with `IDE_PROFILE=<name>`.

## Deployment (Docker)

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
CMD ["python", "-m", "telegram_ide_agent.bot"]
```

> **Note:** The IDE must be running on the same machine or network-accessible via CDP.

## Security

- Only whitelisted Telegram user IDs can interact with the bot
- All file operations are sandboxed to `WORKSPACE_ROOT`
- Dangerous shell commands require inline confirmation
- Path traversal attacks are blocked
- CDP connection is local-only (127.0.0.1)

## Architecture

```
telegram_ide_agent/
├── bot.py              ← Entry point
├── config.py           ← Environment config
├── middleware/
│   └── auth.py         ← User whitelist enforcement
├── handlers/
│   ├── navigation.py   ← /start, /help, /cd, /pwd
│   ├── files.py        ← File operations
│   ├── terminal.py     ← Shell execution
│   └── ai_assistant.py ← AI commands + IDE control
├── services/
│   ├── cdp_manager.py  ← Low-level CDP WebSocket connection
│   ├── ide_bridge.py   ← IDE chat UI interaction + profiles
│   ├── ai_client.py    ← AI client routing through IDE
│   ├── file_manager.py ← Async file ops + sandboxing
│   └── executor.py     ← Subprocess execution
└── utils/
    ├── formatting.py   ← Telegram MarkdownV2 utilities
    └── pagination.py   ← Inline keyboard pagination
```

## Inspiration

Inspired by [LazyGravity](https://github.com/tokyoweb3/LazyGravity) — a Discord bot with the same CDP-bridge concept.

## License

MIT
