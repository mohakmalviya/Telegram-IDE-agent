import tempfile
import unittest
from pathlib import Path

from telegram_ide_agent.handlers.terminal import _pending_commands
from telegram_ide_agent.services.file_manager import FileManager, PathSecurityError


class FileManagerSecurityTests(unittest.TestCase):
    def test_resolve_blocks_parent_traversal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            manager = FileManager(Path(tmp))

            with self.assertRaises(PathSecurityError):
                manager.resolve("../outside.txt")

    def test_nested_upload_path_stays_in_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manager = FileManager(root)
            safe_path = manager.resolve("nested/upload.txt", root)

            self.assertEqual(safe_path, root / "nested" / "upload.txt")
            self.assertTrue(str(safe_path).startswith(str(root)))


class TerminalConfirmationTests(unittest.TestCase):
    def tearDown(self) -> None:
        _pending_commands.clear()

    def test_pending_command_stores_reviewed_cwd(self) -> None:
        reviewed_cwd = Path("/workspace/project")
        _pending_commands[123] = {"command": "rm -rf tmp", "cwd": reviewed_cwd}

        pending = _pending_commands.pop(123)

        self.assertEqual(pending["command"], "rm -rf tmp")
        self.assertEqual(pending["cwd"], reviewed_cwd)


if __name__ == "__main__":
    unittest.main()
