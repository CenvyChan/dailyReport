from datetime import date
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from core.models import Customer
from core.testing import company_a, login_with_company
from sales.models import SalesShipment


class ReportFilterValidationTests(TestCase):
    """手改 URL 传非法筛选值不应该把页面打成 500。"""

    def setUp(self):
        self.admin = User.objects.create_superuser("admin", password="pw")
        customer = Customer.objects.create(company=company_a(), name="客户 A")
        SalesShipment.objects.create(
            company=company_a(),
            customer=customer,
            owner=self.admin,
            sale_type="DOMESTIC",
            shipment_date=date(2026, 8, 10),
            quantity=1,
            currency="CNY",
            original_amount="10.00",
            exchange_rate="1.0000",
            amount_cny="10.00",
        )
        login_with_company(self.client, self.admin, company_a())

    def test_non_numeric_ids_and_bad_dates_are_ignored(self):
        for query in (
            {"person_id": "abc"},
            {"counterpart_id": "xyz"},
            {"start": "notadate"},
            {"end": "13-13-13"},
            {"start": "2026-99-99"},
        ):
            with self.subTest(query=query):
                self.assertEqual(self.client.get(reverse("reports:sales_dashboard"), query).status_code, 200)
                self.assertEqual(self.client.get(reverse("reports:purchase_dashboard"), query).status_code, 200)

    def test_bad_filters_do_not_silently_drop_valid_rows(self):
        response = self.client.get(reverse("reports:sales_dashboard"), {"start": "notadate"})

        self.assertEqual(response.context["dashboard"]["summary"]["quantity"], 1)

    def test_valid_date_filter_still_applies(self):
        response = self.client.get(reverse("reports:sales_export"), {"start": "2026-08-11"})

        self.assertEqual(response.status_code, 200)


class DashboardChromeTests(TestCase):
    """分析页的筛选与汇总结构。此前 8 个筛选控件挤在一行、汇总是一行灰色
    小文本、图表是四个无标题白框。"""

    def setUp(self):
        self.admin = User.objects.create_superuser("chrome-admin", password="pw")
        self.company = company_a()
        login_with_company(self.client, self.admin, self.company)

    def test_the_active_preset_button_is_highlighted(self):
        """不高亮的话，用户看不出当前是哪个区间生效。"""
        response = self.client.get(reverse("reports:sales_dashboard"), {"preset": "month"})
        html = response.content.decode()

        self.assertRegex(html, r'value="month"[^>]*class="on"')

    def test_no_preset_leaves_every_button_unhighlighted(self):
        response = self.client.get(reverse("reports:sales_dashboard"))
        html = response.content.decode()

        self.assertNotRegex(html, r'value="month"[^>]*class="on"')

    def test_the_effective_filters_are_spelled_out(self):
        """用户翻回这页时已经不记得自己筛过什么。"""
        response = self.client.get(reverse("reports:sales_dashboard"), {"preset": "month"})

        self.assertContains(response, "active-chips")
        self.assertContains(response, "日期：")

    def test_no_date_filter_says_so_explicitly(self):
        response = self.client.get(reverse("reports:sales_dashboard"))

        self.assertContains(response, "全部")

    def test_charts_keep_the_ids_the_script_looks_up(self):
        """dashboard.js 靠 getElementById 找容器，加标题栏不能改动这些 id。"""
        response = self.client.get(reverse("reports:sales_dashboard"))

        for element_id in ("daily-trend", "monthly-trend", "type-share", "counterpart-rank"):
            with self.subTest(element_id=element_id):
                self.assertContains(response, f'id="{element_id}"')

    def test_charts_have_visible_titles(self):
        response = self.client.get(reverse("reports:sales_dashboard"))

        self.assertContains(response, "chart-card")
        self.assertContains(response, "每日趋势")

    def test_summary_amounts_are_formatted(self):
        """汇总数字也要走 money 过滤器，否则和列表页显示口径不一致。"""
        customer = Customer.objects.create(company=self.company, name="格式化客户")
        SalesShipment.objects.create(
            company=self.company,
            customer=customer,
            owner=self.admin,
            sale_type="DOMESTIC",
            shipment_date=date(2026, 8, 22),
            quantity=Decimal("120"),
            currency="CNY",
            original_amount=Decimal("534464"),
            exchange_rate=Decimal("1"),
            amount_cny=Decimal("534464"),
        )

        response = self.client.get(reverse("reports:sales_dashboard"))

        self.assertContains(response, "534,464.00")
        self.assertNotContains(response, "534464.000000")
