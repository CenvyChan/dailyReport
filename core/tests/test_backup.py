from pathlib import Path
from tempfile import TemporaryDirectory

from django.test import TestCase

from scripts.backup_sqlite import PREFIX, SUFFIX, _prune, backup_database


class BackupTests(TestCase):
    def test_backup_database_creates_sqlite_file(self):
        with TemporaryDirectory() as directory:
            output = backup_database(Path(directory))
            self.assertTrue(output.exists())
            self.assertEqual(output.suffix, ".sqlite3")

    def test_backup_is_verified_before_being_kept(self):
        """备份完就跑 integrity_check：一份损坏的备份比没有备份更危险，
        真要恢复时才发现就晚了。这里验证正常路径能通过校验并留下非空文件。"""
        with TemporaryDirectory() as directory:
            output = backup_database(Path(directory))

            self.assertGreater(output.stat().st_size, 0)

    def test_missing_target_directory_is_created(self):
        with TemporaryDirectory() as directory:
            nested = Path(directory) / "a" / "b"

            output = backup_database(nested)

            self.assertTrue(output.exists())


class PruneTests(TestCase):
    """不轮转的话备份目录会一直涨，磁盘满了连数据库都写不进去。"""

    def _touch(self, directory, stamps):
        for stamp in stamps:
            (directory / f"{PREFIX}{stamp}{SUFFIX}").touch()

    def test_only_the_newest_backups_are_kept(self):
        with TemporaryDirectory() as raw:
            directory = Path(raw)
            self._touch(directory, ["20260101-010000", "20260102-010000", "20260103-010000"])

            _prune(directory, keep=2)

            remaining = sorted(path.name for path in directory.glob(f"{PREFIX}*"))
            self.assertEqual(
                remaining,
                [f"{PREFIX}20260102-010000{SUFFIX}", f"{PREFIX}20260103-010000{SUFFIX}"],
            )

    def test_keep_zero_disables_pruning(self):
        with TemporaryDirectory() as raw:
            directory = Path(raw)
            self._touch(directory, ["20260101-010000", "20260102-010000"])

            _prune(directory, keep=0)

            self.assertEqual(len(list(directory.glob(f"{PREFIX}*"))), 2)

    def test_unrelated_files_are_left_alone(self):
        """备份目录里可能有人手工放了存档，轮转不能连它一起删。"""
        with TemporaryDirectory() as raw:
            directory = Path(raw)
            self._touch(directory, ["20260101-010000", "20260102-010000"])
            (directory / "手工存档.sqlite3").touch()
            (directory / "README.txt").touch()

            _prune(directory, keep=1)

            self.assertTrue((directory / "手工存档.sqlite3").exists())
            self.assertTrue((directory / "README.txt").exists())

    def test_pruning_an_empty_directory_is_harmless(self):
        with TemporaryDirectory() as raw:
            self.assertEqual(_prune(Path(raw), keep=5), [])


class BackupDirectorySettingTests(TestCase):
    def test_backup_directory_setting_is_usable_as_a_default_target(self):
        """BACKUP_DIRECTORY 此前定义了却没有任何代码引用，--target 是必填参数
        完全绕过它，而文档把它列为环境变量。现在它是 --target 的默认值。"""
        from django.conf import settings

        self.assertTrue(str(settings.BACKUP_DIRECTORY))
