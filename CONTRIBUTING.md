# Contributing

Thanks for helping improve Telegram IDE Agent.

## Development

1. Fork and clone the repository.
2. Create a virtual environment with Python 3.11 or newer.
3. Install dependencies:

```bash
python -m pip install -r requirements.txt
```

4. Run the local checks:

```bash
python -m compileall telegram_ide_agent
python -m unittest discover -s tests
```

## Pull requests

- Keep changes focused and explain the user-facing impact.
- Add or update tests for security-sensitive behavior, file handling, command execution, and CDP parsing.
- Do not commit local `.env` files, click logs, screenshots, or IDE debug captures.
- Document new commands or configuration options in `README.md` and `.env.example`.

## Security-sensitive changes

This project can read files, write files, run shell commands, and interact with a local IDE. Treat path handling, callback data, command confirmation, and authentication changes as security-sensitive.
