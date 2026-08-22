from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from core.testing import company_a, login_with_company


class SalesImportViewTests(TestCase):
    def test_non_admin_cannot_preview_sales_import(self):
        user = User.objects.create_user("sales-a")
        login_with_company(self.client, user, company_a())
        response = self.client.post(reverse("sales:import_preview"))
        self.assertEqual(response.status_code, 403)

    def test_administrator_can_open_sales_import_page(self):
        admin = User.objects.create_superuser("admin", password="pw")
        login_with_company(self.client, admin, company_a())

        response = self.client.get(reverse("sales:import_page"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "销售数据导入")
        self.assertContains(response, "操作说明")
        self.assertContains(response, "数据表和汇率两个工作表")
        self.assertContains(response, company_a().name)

    def test_import_errors_use_clear_chinese_messages(self):
        user = User.objects.create_user("sales-a")
        login_with_company(self.client, user, company_a())
        response = self.client.get(reverse("sales:import_page"))
        self.assertContains(response, "仅管理员可导入销售数据", status_code=403)

        admin = User.objects.create_superuser("admin", password="pw")
        login_with_company(self.client, admin, company_a())
        response = self.client.post(reverse("sales:import_preview"))
        self.assertEqual(response.json()["error"], "请选择要上传的 Excel 文件")
