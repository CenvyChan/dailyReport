from pathlib import Path
from tempfile import TemporaryDirectory

from django.test import TestCase

from scripts.backup_sqlite import backup_database


class BackupTests(TestCase):
    def test_backup_database_creates_sqlite_file(self):
        with TemporaryDirectory() as directory:
            output = backup_database(Path(directory))
            self.assertTrue(output.exists())
            self.assertEqual(output.suffix, ".sqlite3")
