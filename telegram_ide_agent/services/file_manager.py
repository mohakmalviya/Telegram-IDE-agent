"""
TEAM_001: File manager service.
Async file operations with path sandboxing.
"""

import os
import stat
from pathlib import Path

import aiofiles


class PathSecurityError(Exception):
    """Raised when a path escapes the workspace sandbox."""


class FileManager:
    """Async file operations scoped to a workspace root."""

    def __init__(self, workspace_root: Path) -> None:
        self.workspace_root = workspace_root.resolve()

    def resolve(self, path: str, cwd: Path | None = None) -> Path:
        """Resolve a user-provided path safely within the workspace.

        Args:
            path: Relative or absolute path from the user.
            cwd: Current working directory (must be inside workspace).

        Returns:
            Resolved absolute path.

        Raises:
            PathSecurityError: If resolved path escapes the workspace.
        """
        base = cwd if cwd else self.workspace_root
        if os.path.isabs(path):
            resolved = Path(path).resolve()
        else:
            resolved = (base / path).resolve()

        # Security check — must be inside workspace
        try:
            resolved.relative_to(self.workspace_root)
        except ValueError:
            raise PathSecurityError(
                f"Access denied: path escapes workspace. "
                f"Workspace: {self.workspace_root}"
            )
        return resolved

    async def list_dir(self, path: Path) -> list[dict]:
        """List directory contents.

        Returns:
            List of dicts: {"name": str, "is_dir": bool, "size": int | None}
        """
        entries = []
        for entry in sorted(path.iterdir()):
            try:
                st = entry.stat()
                entries.append({
                    "name": entry.name,
                    "is_dir": entry.is_dir(),
                    "size": st.st_size if not entry.is_dir() else None,
                })
            except PermissionError:
                entries.append({
                    "name": entry.name,
                    "is_dir": False,
                    "size": None,
                })
        return entries

    async def read_file(
        self, path: Path, start_line: int | None = None, end_line: int | None = None
    ) -> str:
        """Read file content, optionally a specific line range.

        Args:
            path: Path to the file.
            start_line: Start line (1-indexed, inclusive).
            end_line: End line (1-indexed, inclusive).

        Returns:
            File content as string.
        """
        async with aiofiles.open(path, "r", encoding="utf-8", errors="replace") as f:
            if start_line is not None or end_line is not None:
                lines = await f.readlines()
                s = (start_line or 1) - 1
                e = end_line or len(lines)
                selected = lines[s:e]
                # Add line numbers
                result_lines = []
                for i, line in enumerate(selected, start=s + 1):
                    result_lines.append(f"{i:4d} │ {line.rstrip()}")
                return "\n".join(result_lines)
            else:
                content = await f.read()
                return content

    async def write_file(self, path: Path, content: str) -> None:
        """Write content to a file (creates or overwrites)."""
        path.parent.mkdir(parents=True, exist_ok=True)
        async with aiofiles.open(path, "w", encoding="utf-8") as f:
            await f.write(content)

    async def edit_lines(
        self, path: Path, start_line: int, end_line: int, new_content: str
    ) -> str:
        """Replace a range of lines in a file.

        Args:
            path: Path to the file.
            start_line: First line to replace (1-indexed).
            end_line: Last line to replace (1-indexed).
            new_content: Replacement text.

        Returns:
            The resulting file content.
        """
        async with aiofiles.open(path, "r", encoding="utf-8", errors="replace") as f:
            lines = await f.readlines()

        new_lines = new_content.splitlines(keepends=True)
        # Ensure the last line ends with newline
        if new_lines and not new_lines[-1].endswith("\n"):
            new_lines[-1] += "\n"

        lines[start_line - 1 : end_line] = new_lines

        async with aiofiles.open(path, "w", encoding="utf-8") as f:
            await f.writelines(lines)

        return "".join(lines)

    async def delete(self, path: Path) -> None:
        """Delete a file or empty directory."""
        if path.is_dir():
            # Remove directory tree
            import shutil
            shutil.rmtree(path)
        else:
            path.unlink()

    async def create_file(self, path: Path) -> None:
        """Create an empty file (and parent dirs)."""
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()

    async def create_dir(self, path: Path) -> None:
        """Create a directory (and parents)."""
        path.mkdir(parents=True, exist_ok=True)

    async def search(
        self, root: Path, query: str, max_results: int = 50
    ) -> list[dict]:
        """Search for a string in files under root.

        Returns:
            List of {"file": str, "line": int, "content": str}
        """
        results = []
        for dirpath, _, filenames in os.walk(root):
            for filename in filenames:
                filepath = Path(dirpath) / filename
                # Skip binary files and hidden dirs
                if any(part.startswith(".") for part in filepath.parts):
                    continue
                try:
                    async with aiofiles.open(
                        filepath, "r", encoding="utf-8", errors="ignore"
                    ) as f:
                        for line_num, line in enumerate(await f.readlines(), 1):
                            if query in line:
                                rel = filepath.relative_to(root)
                                results.append({
                                    "file": str(rel),
                                    "line": line_num,
                                    "content": line.rstrip()[:120],
                                })
                                if len(results) >= max_results:
                                    return results
                except (PermissionError, UnicodeDecodeError, OSError):
                    continue
        return results

    def tree(self, root: Path, prefix: str = "", max_depth: int = 3, _depth: int = 0) -> list[str]:
        """Generate a directory tree representation.

        Returns:
            List of formatted tree lines.
        """
        if _depth >= max_depth:
            return []

        lines = []
        try:
            entries = sorted(root.iterdir(), key=lambda e: (not e.is_dir(), e.name))
        except PermissionError:
            return [f"{prefix}[permission denied]"]

        for i, entry in enumerate(entries):
            is_last = i == len(entries) - 1
            connector = "└── " if is_last else "├── "
            icon = "📁" if entry.is_dir() else "📄"

            lines.append(f"{prefix}{connector}{icon} {entry.name}")

            if entry.is_dir():
                extension = "    " if is_last else "│   "
                lines.extend(
                    self.tree(entry, prefix + extension, max_depth, _depth + 1)
                )

        return lines

    def is_binary(self, path: Path) -> bool:
        """Heuristic check if a file is binary."""
        try:
            with open(path, "rb") as f:
                chunk = f.read(8192)
                if b"\x00" in chunk:
                    return True
                return False
        except (OSError, PermissionError):
            return True
