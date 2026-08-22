"""导入接口的兜底：文件类型/大小校验、坏文件与缺列的中文提示。

这些路径此前会冒泡成 Django 错误页，而前端 fetch 拿 HTML 去 response.json()
会抛 SyntaxError，界面上表现为「点了没反应」。
"""

from io import BytesIO

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from openpyxl import Workbook

from core.excel import require_columns
from core.errors import ImportFileError
from core.testing import company_a, login_with_company
from core.uploads import MAX_UPLOAD_BYTES


def workbook_bytes(sheets):
    """sheets: {工作表名: [表头行, 数据行...]}"""
    book = Workbook()
    book.remove(book.active)
    for title, rows in sheets.items():
        sheet = book.create_sheet(title)
        for row in rows:
            sheet.append(row)
    buffer = BytesIO()
    book.save(buffer)
    return buffer.getvalue()


def upload(name, content):
    return SimpleUploadedFile(name, content)


class UploadGuardTests(TestCase):
    def setUp(self):
        admin = User.objects.create_superuser("admin", password="pw")
        login_with_company(self.client, admin, company_a())
        self.url = reverse("sales:import_preview")

    def test_wrong_extension_is_rejected_with_advice(self):
        response = self.client.post(self.url, {"file": upload("数据.csv", b"a,b\n1,2\n")})

        self.assertEqual(response.status_code, 400)
        self.assertIn("只支持 .xls 和 .xlsx", response.json()["error"])

    def test_oversized_file_is_rejected_before_parsing(self):
        """低配服务器上 waitress 只有 8 线程，一个超大文件能把服务拖死。"""
        payload = upload("大文件.xlsx", b"x" * (MAX_UPLOAD_BYTES + 1))

        response = self.client.post(self.url, {"file": payload})

        self.assertEqual(response.status_code, 400)
        self.assertIn("超过", response.json()["error"])

    def test_corrupt_workbook_gets_a_chinese_message_not_a_500(self):
        response = self.client.post(self.url, {"file": upload("坏文件.xlsx", b"not really excel")})

        self.assertEqual(response.status_code, 400)
        self.assertIn("Excel", response.json()["error"])
        # 不能把 pandas/xlrd 的英文异常透给业务人员。
        self.assertNotIn("Traceback", response.json()["error"])

    def test_missing_worksheet_names_the_sheet_it_wants(self):
        content = workbook_bytes({"Sheet1": [["客户名称", "业务跟单"], ["客户甲", "张三"]]})

        response = self.client.post(self.url, {"file": upload("改了表名.xlsx", content)})

        self.assertEqual(response.status_code, 400)
        self.assertIn("数据表", response.json()["error"])


class MissingColumnTests(TestCase):
    """缺列时逐行校验的 row.get(列名) 全是 None，会让每一行都报「不能为空」。
    用户明明填了内容却被告知为空，只会反复重填——所以要先校验表头。"""

    def setUp(self):
        admin = User.objects.create_superuser("admin", password="pw")
        login_with_company(self.client, admin, company_a())

    def test_missing_columns_are_listed_instead_of_reported_as_empty_rows(self):
        # 表头把「客户名称」写成了「客户全称」，其余列齐全。
        content = workbook_bytes({
            "数据表": [
                ["客户全称", "业务跟单", "销售类型", "出货日期", "数量", "金额"],
                ["客户甲", "张三", "内销", "2026-08-10", 10, 100],
            ],
            "汇率": [["日期", "汇率"], ["2026年8月", 7.1]],
        })

        response = self.client.post(
            reverse("sales:import_preview"), {"file": upload("列名不对.xlsx", content)}
        )

        self.assertEqual(response.status_code, 400)
        message = response.json()["error"]
        self.assertIn("客户名称", message)
        self.assertIn("客户全称", message)
        self.assertNotIn("不能为空", message)

    def test_a_recognised_alias_is_accepted(self):
        """「客户」是「客户名称」的别名，应当照常通过。"""
        content = workbook_bytes({
            "数据表": [
                ["客户", "业务跟单", "销售类型", "出货日期", "数量", "金额"],
                ["客户甲", "张三", "内销", "2026-08-10", 10, 100],
            ],
            "汇率": [["日期", "汇率"], ["2026年8月", 7.1]],
        })

        response = self.client.post(
            reverse("sales:import_preview"), {"file": upload("用别名.xlsx", content)}
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["valid_row_count"], 1)
        self.assertEqual(response.json()["error_rows"], [])


class RequireColumnsTests(TestCase):
    def test_empty_sheet_is_left_to_the_row_validators(self):
        require_columns([], ("客户名称",))

    def test_alias_tuples_pass_when_any_alias_is_present(self):
        require_columns([{"客户": "甲"}], (("客户名称", "客户"),))

    def test_message_reports_both_what_is_missing_and_what_is_there(self):
        with self.assertRaises(ImportFileError) as caught:
            require_columns([{"金额": 1}], ("客户名称", "数量"))

        message = str(caught.exception)
        self.assertIn("客户名称", message)
        self.assertIn("数量", message)
        self.assertIn("金额", message)
