from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse


class PurchaseImportViewTests(TestCase):
    def test_non_admin_cannot_preview_purchase_import(self):
        user = User.objects.create_user("buyer-a")
        self.client.force_login(user)
        response = self.client.post(reverse("purchase:import_preview"))
        self.assertEqual(response.status_code, 403)

    def test_administrator_can_open_purchase_import_page(self):
        admin = User.objects.create_superuser("admin", password="pw")
        self.client.force_login(admin)

        response = self.client.get(reverse("purchase:import_page"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "采购数据导入")
        self.assertContains(response, "操作说明")
        self.assertContains(response, "国外采购需要先维护对应月份汇率")

    def test_import_errors_use_clear_chinese_messages(self):
        user = User.objects.create_user("buyer-a")
        self.client.force_login(user)
        response = self.client.get(reverse("purchase:import_page"))
        self.assertContains(response, "仅管理员可导入采购数据", status_code=403)

        admin = User.objects.create_superuser("admin", password="pw")
        self.client.force_login(admin)
        response = self.client.post(reverse("purchase:import_preview"))
        self.assertEqual(response.json()["error"], "请上传 Excel 文件")
