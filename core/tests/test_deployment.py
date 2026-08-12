import subprocess
import sys
from pathlib import Path

from django.test import SimpleTestCase


class WaitressScriptTests(SimpleTestCase):
    def test_waitress_script_can_import_project_when_loaded_from_scripts_directory(self):
        script_directory = Path(__file__).resolve().parents[2] / "scripts"
        result = subprocess.run(
            [sys.executable, "-c", "import run_waitress"],
            cwd=script_directory,
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 0, result.stderr)

    def test_backup_script_can_import_project_when_loaded_from_scripts_directory(self):
        script_directory = Path(__file__).resolve().parents[2] / "scripts"
        result = subprocess.run(
            [sys.executable, "backup_sqlite.py", "--help"],
            cwd=script_directory,
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
