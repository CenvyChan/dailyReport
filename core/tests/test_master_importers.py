from io import BytesIO

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from openpyxl import Workbook

from core.importers import validate_named_rows, validate_user_rows
from core.models import CompanyMembership, Customer, Supplier, UserProfile
from core.testing import company_a, company_b, login_with_company


class MasterImporterTests(SimpleTestCase):
    def test_customer_or_supplier_name_rows_are_retained(self):
        preview = validate_named_rows([{"名称": "客户 A"}], field="名称")
        self.assertEqual(preview.valid_row_count, 1)

    def test_user_import_requires_initial_password_and_supported_role(self):
        preview = validate_user_rows([{"用户名": "sales-a", "姓名": "销售甲", "角色": "sales", "初始密码": ""}])
        self.assertEqual(preview.error_rows[0]["field"], "初始密码")

    def test_role_column_accepts_several_roles_in_one_cell(self):
        for cell in ("销售、采购", "销售,采购", "销售，采购", "sales/purchase", "销售 、 采购"):
            with self.subTest(cell=cell):
                preview = validate_user_rows(
                    [{"用户名": "both", "姓名": "", "角色": cell, "初始密码": "pw"}]
                )
                self.assertEqual(preview.error_rows, [])
                self.assertEqual(preview.rows[0]["roles"], ["sales", "purchase"])

    def test_roles_are_deduplicated_and_ordered_consistently(self):
        preview = validate_user_rows(
            [{"用户名": "x", "姓名": "", "角色": "采购、销售、采购", "初始密码": "pw"}]
        )

        self.assertEqual(preview.rows[0]["roles"], ["sales", "purchase"])

    def test_one_bad_role_in_the_cell_reports_which_word_failed(self):
        preview = validate_user_rows(
            [{"用户名": "x", "姓名": "", "角色": "销售、内销", "初始密码": "pw"}]
        )

        self.assertEqual(preview.error_rows[0]["field"], "角色")
        self.assertIn("内销", preview.error_rows[0]["message"])


def workbook_file(name, headers, row):
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(headers)
    sheet.append(row)
    content = BytesIO()
    workbook.save(content)
    return SimpleUploadedFile(name, content.getvalue(), content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


class MasterImportViewTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser("admin", password="pw")
        login_with_company(self.client, self.admin, company_a())

    def test_customer_and_supplier_import_commit(self):
        response = self.client.post(
            reverse("core:customer_import_commit"),
            {"file": workbook_file("customers.xlsx", ["客户名称"], ["客户 A"])},
        )
        self.assertEqual(response.json()["imported"], 1)
        self.assertTrue(Customer.objects.filter(company=company_a(), name="客户 A").exists())

        response = self.client.post(
            reverse("core:supplier_import_commit"),
            {"file": workbook_file("suppliers.xlsx", ["供应商名称"], ["供应商 A"])},
        )
        self.assertEqual(response.json()["imported"], 1)
        self.assertTrue(Supplier.objects.filter(company=company_a(), name="供应商 A").exists())

    def test_master_data_is_imported_into_the_active_company_only(self):
        self.client.post(
            reverse("core:customer_import_commit"),
            {"file": workbook_file("customers.xlsx", ["客户名称"], ["客户 A"])},
        )

        self.assertTrue(Customer.objects.filter(company=company_a(), name="客户 A").exists())
        self.assertFalse(Customer.objects.filter(company=company_b(), name="客户 A").exists())

    def test_user_import_sets_role_password_and_first_login_flag(self):
        response = self.client.post(
            reverse("core:user_import_commit"),
            {"file": workbook_file("users.xlsx", ["用户名", "姓名", "角色", "初始密码"], ["sales-a", "销售甲", "sales", "Initial@123"])},
        )

        self.assertEqual(response.json()["imported"], 1)
        user = User.objects.get(username="sales-a")
        self.assertTrue(user.check_password("Initial@123"))
        self.assertTrue(user.groups.filter(name="sales").exists())
        self.assertTrue(UserProfile.objects.get(user=user).must_change_password)
        self.assertTrue(CompanyMembership.objects.filter(user=user, company=company_a()).exists())

    def test_import_pages_explain_columns_and_commit_flow(self):
        response = self.client.get(reverse("core:customer_import_page"))
        self.assertContains(response, "操作说明")
        self.assertContains(response, "客户名称")
        self.assertContains(response, "先预览")
        self.assertContains(response, company_a().name)

        response = self.client.get(reverse("core:user_import_page"))
        self.assertContains(response, "用户名、姓名、角色、初始密码")
        self.assertContains(response, "首次登录后必须自行修改密码")
