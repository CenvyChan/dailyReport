"""import_history 命令的安全兜底：--reset 需显式确认、初始密码不写在代码里、
人员映射从版本库外的文件读取。"""

import json
import tempfile
from pathlib import Path

from django.contrib.auth.models import User
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from core.models import Customer
from core.testing import company_a


class ImportHistorySafetyTests(TestCase):
    def setUp(self):
        self.company = company_a()
        User.objects.create_superuser("admin", password="pw")
        Customer.objects.create(company=self.company, name="客户甲")
        self.directory = Path(tempfile.mkdtemp())
        self.people_file = self._write_json("people.json", {"张三": "zhangsan"})

    def _write_json(self, name, payload):
        path = self.directory / name
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        return str(path)

    def _run(self, **kwargs):
        options = {
            "company": self.company.code,
            "people_file": self.people_file,
            # 源表路径故意指向不存在的文件：这些用例都应在读表之前就中止。
            "sales_file": "missing-on-purpose.xls",
            "purchase_file": "missing-on-purpose.xls",
        }
        options.update(kwargs)
        call_command("import_history", **options)

    def test_reset_without_confirmation_deletes_nothing(self):
        """误敲 --reset 就是全公司数据清零，所以必须先报数再退出。"""
        with self.assertRaises(CommandError) as caught:
            self._run(reset=True)

        self.assertIn("--yes-i-know", str(caught.exception))
        self.assertTrue(Customer.objects.filter(company=self.company).exists())

    def test_missing_people_file_is_reported_clearly(self):
        with self.assertRaises(CommandError) as caught:
            self._run(people_file=str(self.directory / "nowhere.json"))

        self.assertIn("人员映射文件", str(caught.exception))

    def test_malformed_people_file_is_reported_clearly(self):
        broken = self.directory / "broken.json"
        broken.write_text("{not json", encoding="utf-8")

        with self.assertRaises(CommandError) as caught:
            self._run(people_file=str(broken))

        self.assertIn("不是合法 JSON", str(caught.exception))

    def test_comment_keys_in_the_example_file_are_not_treated_as_people(self):
        with_comments = self._write_json("commented.json", {"_说明": "示例", "张三": "zhangsan"})

        with self.assertRaises(CommandError) as caught:
            self._run(people_file=with_comments, reset=True)

        # 能走到 reset 确认，说明映射已加载且 "_说明" 没被当成人名。
        self.assertIn("--yes-i-know", str(caught.exception))
