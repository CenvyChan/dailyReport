from django.contrib import admin
from django.contrib.auth.models import User
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from core.admin import action_label
from core.models import Customer, ExchangeRate, OperationLog, Supplier
from purchase.models import PurchaseReceipt
from sales.models import SalesShipment


class AdminLocalizationTests(SimpleTestCase):
    def test_custom_models_and_site_header_are_chinese(self):
        self.assertEqual(admin.site.site_header, "FINOSSReportSystem")
        self.assertEqual(Customer._meta.verbose_name, "客户")
        self.assertEqual(Supplier._meta.verbose_name, "供应商")
        self.assertEqual(ExchangeRate._meta.verbose_name, "月度汇率")
        self.assertEqual(OperationLog._meta.verbose_name, "操作日志")

    def test_operation_actions_have_chinese_explanation(self):
        self.assertEqual(action_label("CREATE"), "新增")
        self.assertEqual(action_label("PASSWORD_RESET"), "重置密码")

    def test_sales_and_purchase_sources_have_chinese_labels(self):
        self.assertEqual(SalesShipment.DataSource.MANUAL.label, "手工录入")
        self.assertEqual(SalesShipment.DataSource.HISTORY_IMPORT.label, "历史数据导入")
        self.assertEqual(PurchaseReceipt.DataSource.MANUAL.label, "手工录入")
        self.assertEqual(PurchaseReceipt.DataSource.HISTORY_IMPORT.label, "历史数据导入")


class AdminFriendlyPageTests(TestCase):
    def setUp(self):
        self.admin_user = User.objects.create_superuser("admin", password="pw")
        self.client.force_login(self.admin_user)

    def test_admin_pages_use_chinese_and_explain_key_fields(self):
        response = self.client.get(reverse("admin:index"))

        self.assertContains(response, "FINOSSReportSystem")
        self.assertContains(response, "基础管理")
        self.assertContains(response, "销售管理")
        self.assertContains(response, "采购管理")
        self.assertNotContains(response, "Django administration")

        response = self.client.get(reverse("admin:core_customer_add"))
        self.assertContains(response, "用于销售日报选择和报表汇总")

        response = self.client.get(reverse("admin:core_exchangerate_add"))
        self.assertContains(response, "请选择对应月份的 1 日")

    def test_operation_log_detail_explains_action_and_field_names(self):
        log = OperationLog.objects.create(
            actor=self.admin_user,
            action="UPDATE",
            model_label="core.Customer",
            object_id="42",
            before_data={"name": "客户 A", "is_active": True},
            after_data={"name": "客户 B", "is_active": False},
        )

        response = self.client.get(reverse("admin:core_operationlog_change", args=[log.pk]))

        self.assertContains(response, "操作说明")
        self.assertContains(response, "admin 修改了客户（数据编号：42）")
        self.assertContains(response, "客户名称")
        self.assertContains(response, "启用")
        self.assertNotContains(response, "OperationLog object")

    def test_role_group_page_shows_chinese_business_meaning(self):
        response = self.client.get(reverse("admin:auth_group_changelist"))

        self.assertContains(response, "中文角色")
        self.assertContains(response, "角色说明")
        self.assertContains(response, "管理员")
        self.assertContains(response, "销售")
        self.assertContains(response, "采购")
        self.assertContains(response, "报表查看者")
