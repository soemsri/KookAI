import subprocess
import unittest
from unittest.mock import MagicMock, patch

import main


class TestProcessCleanup(unittest.TestCase):
    @patch("main.os.kill")
    @patch("main.subprocess.run")
    @patch("main.os.path.exists", return_value=False)
    def test_windows_scans_agy_with_powershell(self, _mock_exists, mock_run, mock_kill):
        mock_run.return_value = MagicMock(returncode=0, stdout="1234\n")

        main.kill_processes_locking_db("conversation-123")

        command = mock_run.call_args.args[0]
        self.assertEqual(command[:4], ["powershell", "-NoProfile", "-NonInteractive", "-Command"])
        self.assertEqual(mock_run.call_args.kwargs["env"]["KOOKAI_TARGET_CONVERSATION_ID"], "conversation-123")
        mock_kill.assert_called_once_with(1234, 9)

    @patch("main.os.kill")
    @patch("main.subprocess.run")
    @patch("main.os.path.exists", return_value=False)
    @patch("main.os.name", "posix")
    def test_unix_scans_ps_output_for_matching_agy_process(self, _mock_exists, mock_run, mock_kill):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="user 4321 1 0 agy --conversation conversation-456\n",
        )

        main.kill_processes_locking_db("conversation-456")

        mock_run.assert_called_once_with(["ps", "-ef"], capture_output=True, text=True, timeout=5)
        mock_kill.assert_called_once_with(4321, 9)

    @patch("main.logging.warning")
    @patch("main.subprocess.run", side_effect=FileNotFoundError("powershell"))
    @patch("main.os.path.exists", return_value=False)
    def test_missing_process_scanner_is_nonfatal(self, _mock_exists, _mock_run, mock_warning):
        main.kill_processes_locking_db("conversation-789")

        self.assertTrue(mock_warning.called)


if __name__ == "__main__":
    unittest.main()
