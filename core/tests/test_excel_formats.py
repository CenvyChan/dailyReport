from io import BytesIO

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from openpyxl import Workbook

from core.excel import read_rows
from core.templates_export import build_template
from core.testing import company_a, login_with_company

XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def xlsx_bytes(sheets):
    workbook = Workbook()
    workbook.remove(workbook.active)
    for title, rows in sheets.items():
        sheet = workbook.create_sheet(title)
        for row in rows:
            sheet.append(row)
    buffer = BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


class ExcelReaderTests(SimpleTestCase):
    """上传框允许 .xls 和 .xlsx，读取层必须两种都吃得下。
    历史上这里写死了 engine="xlrd"，.xlsx 会直接报 'Excel xlsx file; not supported'。"""

    def test_xlsx_is_read_by_sheet_name(self):
        content = xlsx_bytes({"数据表": [["客户名称"], ["客户 A"]]})

        self.assertEqual(read_rows(BytesIO(content), "数据表"), [{"客户名称": "客户 A"}])

    def test_xlsx_is_read_by_sheet_index(self):
        content = xlsx_bytes({"任意名字": [["供应商名称"], ["供应商 A"]]})

        self.assertEqual(read_rows(BytesIO(content)), [{"供应商名称": "供应商 A"}])

    def test_multi_sheet_xlsx_reads_each_sheet_independently(self):
        content = xlsx_bytes({"数据表": [["数量"], [3]], "汇率": [["汇率"], [7.12]]})

        self.assertEqual(read_rows(BytesIO(content), "数据表"), [{"数量": 3}])
        self.assertEqual(read_rows(BytesIO(content), "汇率"), [{"汇率": 7.12}])


class XlsxUploadTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser("admin", password="pw")
        login_with_company(self.client, self.admin, company_a())

    def test_sales_preview_accepts_the_downloaded_xlsx_template(self):
        _, content = build_template("sales")

        response = self.client.post(
            reverse("sales:import_preview"),
            {"file": SimpleUploadedFile("销售模板.xlsx", content, content_type=XLSX_MIME)},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["valid_row_count"], 2)
        self.assertEqual(payload["error_rows"], [])

    def test_sales_commit_accepts_xlsx_and_creates_rows_in_the_active_company(self):
        _, content = build_template("sales")

        response = self.client.post(
            reverse("sales:import_commit"),
            {"file": SimpleUploadedFile("销售模板.xlsx", content, content_type=XLSX_MIME)},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["imported"], 2)
        from sales.models import SalesShipment

        self.assertEqual(SalesShipment.objects.filter(company=company_a()).count(), 2)

    def test_purchase_preview_accepts_xlsx_and_only_flags_the_missing_rate(self):
        _, content = build_template("purchase")

        response = self.client.post(
            reverse("purchase:import_preview"),
            {"file": SimpleUploadedFile("采购模板.xlsx", content, content_type=XLSX_MIME)},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["valid_row_count"], 2)
        self.assertEqual([error["field"] for error in payload["error_rows"]], ["汇率"])
