# Security Policy

## Supported versions

Security fixes are maintained on the default branch.

## Reporting a vulnerability

Please report security issues privately by opening a GitHub security advisory or contacting the maintainer through GitHub.

Avoid posting exploit details in public issues until a fix is available.

## Security model

Telegram IDE Agent is intended for personal or trusted-team use.

- Only Telegram users listed in `ALLOWED_USER_IDS` can access the bot.
- File operations are restricted to `WORKSPACE_ROOT`.
- Destructive file operations and dangerous shell patterns require confirmation.
- CDP should be bound to localhost or otherwise protected by your network controls.

The bot can still execute commands inside the configured workspace, so run it on a machine and project directory you trust.
