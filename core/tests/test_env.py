from pathlib import Path
from tempfile import TemporaryDirectory

from django.test import SimpleTestCase

from config.env import load_env_file


class EnvironmentFileTests(SimpleTestCase):
    def test_load_env_file_reads_comments_and_quoted_values(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / ".env"
            path.write_text("# comment\nDJANGO_ALLOWED_HOSTS=report.internal,127.0.0.1\nDJANGO_SECRET_KEY=\"secret-value\"\n", encoding="utf-8")

            self.assertEqual(
                load_env_file(path),
                {"DJANGO_ALLOWED_HOSTS": "report.internal,127.0.0.1", "DJANGO_SECRET_KEY": "secret-value"},
            )
