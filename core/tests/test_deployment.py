import subprocess
import sys
from pathlib import Path

from django.test import SimpleTestCase

PROJECT_ROOT = Path(__file__).resolve().parents[2]


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


class DeployScriptParityTests(SimpleTestCase):
    """部署脚本和 docker-compose.yml 必须描述同一套容器。

    真实教训：backup sidecar 一开始只加进了 compose，而目标主机没有 compose
    插件、走的是 plain docker run，结果自动备份根本没起来，部署完才发现。
    """

    def _deploy_script(self):
        return (PROJECT_ROOT / "scripts" / "deploy_remote.sh").read_text(encoding="utf-8")

    def _compose(self):
        return (PROJECT_ROOT / "docker-compose.yml").read_text(encoding="utf-8")

    def test_deploy_script_starts_every_service_compose_defines(self):
        script = self._deploy_script()
        compose = self._compose()
        for service, variable in (("web", "WEB"), ("mailer", "MAILER"), ("backup", "BACKUP")):
            self.assertIn(f"{service}:", compose)
            self.assertIn(f'--name "${variable}"', script)

    def test_deploy_script_runs_the_backup_loop(self):
        script = self._deploy_script()

        self.assertIn("backup_sqlite.py", script)
        self.assertIn("--keep 30", script)

    def test_logs_live_under_the_data_volume(self):
        """不能单独挂一个 logs 卷：容器内以 uid 10001 运行，而宿主机挂载目录
        通常归部署用户（这台机器上是 uid 1001），属主不同就不可写，Django 的
        file handler 建不起来会直接起不来——这个坑真实发生过一次。
        放在已经可写的 data 卷下，同样持久化且不依赖宿主机权限。"""
        script = self._deploy_script()

        self.assertIn("LOG_DIRECTORY=/app/data/logs", script)
        self.assertNotIn('-v "$PWD/logs:/app/logs"', script)

    def test_the_backup_directory_is_mounted_where_the_setting_points(self):
        script = self._deploy_script()

        self.assertIn("BACKUP_DIRECTORY=/app/backups", script)
        self.assertIn('-v "$PWD/backups:/app/backups"', script)

    def test_stale_containers_are_removed_before_recreating(self):
        """漏删某个容器会导致下次 docker run 因名字冲突失败。"""
        script = self._deploy_script()

        self.assertIn('docker rm -f "$WEB" "$MAILER" "$BACKUP"', script)
