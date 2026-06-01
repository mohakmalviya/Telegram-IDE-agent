# Telegram IDE Agent

A Telegram bot for operating a local AI IDE from your phone. It connects to Chromium-based IDEs through the Chrome DevTools Protocol (CDP), sends prompts to the IDE's own AI chat, streams progress back to Telegram, and exposes file, terminal, navigation, and screenshot commands.

The project is designed for maintainers who want a secure remote control surface for their development machine without adding another model API key.

## What It Does

```text
Telegram chat -> Python bot -> CDP websocket -> local IDE chat panel
```

1. You send a command or prompt in Telegram.
2. The bot authorizes your Telegram user ID.
3. File and terminal actions run inside `WORKSPACE_ROOT`.
4. AI prompts are injected into the configured IDE chat panel through CDP.
5. Results, progress updates, approval prompts, and screenshots are sent back to Telegram.

## Features

- File operations: browse, read, edit, create, delete, upload, download, search, and tree view.
- Terminal execution: run commands with timeouts and confirmation for dangerous patterns.
- IDE AI bridge: send prompts to Antigravity, Cursor, VS Code, or Windsurf using the IDE's configured model.
- Progress mirroring: track AI activity, files, commands, and final responses from Telegram.
- IDE control: reconnect to CDP, inspect chat element detection, stop generation, and capture screenshots.
- Security controls: Telegram user allowlist, path sandboxing, confirmation callbacks, and local-only CDP guidance.

## Supported IDE Profiles

| Profile | IDE | Status |
| --- | --- | --- |
| `antigravity` | Antigravity | Primary |
| `cursor` | Cursor | Supported |
| `vscode` | VS Code / Copilot Chat | Supported |
| `windsurf` | Windsurf | Supported |

Set the active profile with `IDE_PROFILE=<name>` in `.env`.

## Requirements

- Python 3.11 or newer
- Telegram bot token from [BotFather](https://t.me/BotFather)
- Your Telegram numeric user ID
- A Chromium-based IDE launched with `--remote-debugging-port`

## Quick Start

```bash
git clone https://github.com/mohakmalviya/Telegram-IDE-agent.git
cd Telegram-IDE-agent
python -m venv .venv
```

Activate the virtual environment:

```powershell
.venv\Scripts\activate
```

Or on macOS/Linux:

```bash
source .venv/bin/activate
```

Install dependencies:

```bash
python -m pip install -r requirements.txt
```

Create your environment file:

```bash
cp .env.example .env
```

Configure `.env`:

```env
BOT_TOKEN=your_telegram_bot_token
ALLOWED_USER_IDS=123456789
WORKSPACE_ROOT=/path/to/your/projects
IDE_PROFILE=antigravity
CDP_PORT=9222
RESPONSE_TIMEOUT=120
COMMAND_TIMEOUT=60
```

Launch your IDE with CDP enabled:

```powershell
start_antigravity.bat
```

Or manually:

```bash
Antigravity.exe --remote-debugging-port=9222
Cursor.exe --remote-debugging-port=9222
code --remote-debugging-port=9222
```

Start the bot:

```bash
python -m telegram_ide_agent.bot
```

Open Telegram, find your bot, and send `/start`.

## Commands

| Command | Description |
| --- | --- |
| `/files` | List the current directory |
| `/cat <file>` | Read a file, optionally with a line range |
| `/edit <file>` | Start an interactive file edit flow |
| `/touch <file>` | Create an empty file |
| `/mkdir <dir>` | Create a directory |
| `/rm <path>` | Delete a file or directory after confirmation |
| `/download <file>` | Download a workspace file |
| `/upload` | Show upload instructions |
| `/search <query>` | Search text in files |
| `/tree` | Show a directory tree |
| `/cd <path>` | Change working directory |
| `/pwd` | Show current working directory |
| `/run <cmd>` | Execute a shell command |
| `/git <args>` | Run a git command shortcut |
| `/pip <args>` | Run a pip command shortcut |
| `/npm <args>` | Run an npm command shortcut |
| `/ai <prompt>` | Send a prompt to the IDE AI chat |
| `/ai_edit <file> <prompt>` | Ask the IDE AI to edit a file |
| `/ai_explain <file>` | Ask the IDE AI to explain a file |
| `/model <name>` | Try to select an IDE model by name |
| `/stop` | Stop current AI generation |
| `/ide_status` | Show CDP and chat element diagnostics |
| `/ide_connect` | Connect or reconnect to the IDE |
| `/ide_profile` | List supported IDE profiles |
| `/screenshot` | Capture the IDE window |
| `/debug_on` | Mirror IDE progress to Telegram for debugging |
| `/debug_off` | Stop the debug mirror |

## Security Model

Telegram IDE Agent is powerful: it can read files, write files, execute commands, and control a local IDE. Run it only for yourself or a trusted team.

- Access is limited to IDs in `ALLOWED_USER_IDS`.
- File paths are resolved and checked against `WORKSPACE_ROOT`.
- Uploaded files are written only after sandbox path resolution.
- Delete confirmations use short-lived server-side tokens instead of raw callback paths.
- Dangerous command confirmations store the reviewed command and working directory together.
- CDP should stay bound to localhost unless you fully control the network.

See [SECURITY.md](SECURITY.md) for reporting and operational guidance.

## Development

Run the local checks:

```bash
python -m compileall telegram_ide_agent
python -m unittest discover -s tests
```

The GitHub Actions workflow runs the same compile and unit-test checks on pushes and pull requests.

## Repository Hygiene

The repository intentionally excludes local debug captures such as click logs, generated analysis files, virtual environments, caches, and `.env` secrets.

## Project Layout

```text
telegram_ide_agent/
  bot.py                  # Entry point and dependency wiring
  config.py               # Environment config loader
  middleware/auth.py      # Telegram user allowlist
  handlers/               # Telegram command handlers
  services/               # CDP, IDE bridge, file manager, executor
  utils/                  # Telegram formatting and pagination helpers
tests/
  test_security.py        # Security-focused unit tests
```

## License

MIT. See [LICENSE](LICENSE).

## Inspiration

Inspired by [LazyGravity](https://github.com/tokyoweb3/LazyGravity), a Discord bot built around the same CDP bridge concept.
