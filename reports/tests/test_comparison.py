"""采购销售对比表。口径：FNS/NBHH 销售数据均以未税为准，不做含税换算；
采购与销售都直接取折算人民币金额，占比 = 采购/销售。"""

from datetime import date
from decimal import Decimal

from django.contrib.auth.models import Group, User
from django.test import TestCase
from django.urls import reverse

from core.models import Customer, PurchaseAssignment, SalesAssignment, Supplier
from core.testing import company_a, company_b, login_with_company
from purchase.models import PurchaseReceipt
from reports.comparison import monthly_comparison
from sales.models import SalesShipment


def add_sale(company, customer, owner, day, amount, *, currency="CNY", rate="1"):
    return SalesShipment.objects.create(
        company=company, customer=customer, owner=owner, sale_type="DOMESTIC",
        shipment_date=day, quantity="1", currency=currency,
        original_amount=amount, exchange_rate=rate,
        amount_cny=Decimal(amount) * Decimal(rate),
    )


def add_purchase(company, supplier, buyer, day, amount):
    return PurchaseReceipt.objects.create(
        company=company, supplier=supplier, buyer=buyer, purchase_type="DOMESTIC",
        purchase_date=day, quantity="1", currency="CNY",
        original_amount=amount, exchange_rate="1", amount_cny=amount,
    )


class ComparisonMathTests(TestCase):
    def setUp(self):
        self.company = company_a()
        self.user = User.objects.create_superuser("admin", password="pw")
        self.customer = Customer.objects.create(company=self.company, name="客户")
        self.supplier = Supplier.objects.create(company=self.company, name="供应商")

    def test_sales_are_used_untaxed_without_any_gross_up(self):
        add_sale(self.company, self.customer, self.user, date(2026, 8, 1), "1000")

        report = monthly_comparison(company=self.company, year=2026, month=8)

        self.assertEqual(report["rows"][0]["sales_amount"], Decimal("1000.00"))

    def test_purchases_are_used_as_is(self):
        add_purchase(self.company, self.supplier, self.user, date(2026, 8, 1), "1000")

        report = monthly_comparison(company=self.company, year=2026, month=8)

        self.assertEqual(report["rows"][0]["purchase_amount"], Decimal("1000.00"))

    def test_share_is_purchase_over_sales(self):
        add_purchase(self.company, self.supplier, self.user, date(2026, 8, 1), "500")
        add_sale(self.company, self.customer, self.user, date(2026, 8, 1), "1000")

        report = monthly_comparison(company=self.company, year=2026, month=8)

        self.assertEqual(report["rows"][0]["share"], Decimal("50.0000"))

    def test_share_is_none_when_there_is_no_sale_that_day(self):
        add_purchase(self.company, self.supplier, self.user, date(2026, 8, 1), "100")

        report = monthly_comparison(company=self.company, year=2026, month=8)

        self.assertIsNone(report["rows"][0]["share"])

    def test_share_above_one_hundred_is_flagged(self):
        add_purchase(self.company, self.supplier, self.user, date(2026, 8, 1), "5000")
        add_sale(self.company, self.customer, self.user, date(2026, 8, 1), "1000")

        row = monthly_comparison(company=self.company, year=2026, month=8)["rows"][0]

        self.assertTrue(row["over_full"])

    def test_every_day_of_the_month_is_listed_even_without_data(self):
        report = monthly_comparison(company=self.company, year=2026, month=8)

        self.assertEqual(len(report["rows"]), 31)
        self.assertEqual(report["days_with_data"], 0)
        self.assertTrue(all(not row["has_data"] for row in report["rows"]))

    def test_february_length_follows_the_calendar(self):
        self.assertEqual(len(monthly_comparison(company=self.company, year=2026, month=2)["rows"]), 28)
        self.assertEqual(len(monthly_comparison(company=self.company, year=2024, month=2)["rows"]), 29)

    def test_totals_equal_the_sum_of_the_daily_rows(self):
        add_purchase(self.company, self.supplier, self.user, date(2026, 8, 1), "100")
        add_purchase(self.company, self.supplier, self.user, date(2026, 8, 2), "200")
        add_sale(self.company, self.customer, self.user, date(2026, 8, 1), "1000")

        report = monthly_comparison(company=self.company, year=2026, month=8)

        self.assertEqual(report["purchase_total"], sum(r["purchase_amount"] for r in report["rows"]))
        self.assertEqual(report["sales_total"], sum(r["sales_amount"] for r in report["rows"]))

    def test_another_company_data_is_excluded(self):
        other = company_b()
        other_customer = Customer.objects.create(company=other, name="客户")
        add_sale(other, other_customer, self.user, date(2026, 8, 1), "9999")

        report = monthly_comparison(company=self.company, year=2026, month=8)

        self.assertEqual(report["sales_total"], Decimal("0.00"))

    def test_export_sales_use_the_month_rate_snapshot(self):
        """外销按录入的汇率快照折算人民币，不再加税。"""
        add_sale(self.company, self.customer, self.user, date(2026, 8, 1), "100",
                 currency="USD", rate="7")

        report = monthly_comparison(company=self.company, year=2026, month=8)

        self.assertEqual(report["rows"][0]["sales_amount"], Decimal("700.00"))


class ComparisonViewTests(TestCase):
    def setUp(self):
        self.company = company_a()
        self.admin = User.objects.create_superuser("admin", password="pw")
        self.customer = Customer.objects.create(company=self.company, name="客户")
        self.supplier = Supplier.objects.create(company=self.company, name="供应商")
        add_purchase(self.company, self.supplier, self.admin, date(2026, 8, 3), "500")
        add_sale(self.company, self.customer, self.admin, date(2026, 8, 3), "1000")

    def test_page_renders_the_table_with_totals(self):
        login_with_company(self.client, self.admin, self.company)

        response = self.client.get(reverse("reports:monthly_comparison"), {"year": 2026, "month": 8})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "采购入库金额与销售金额对比表")
        self.assertContains(response, "500.00")
        self.assertContains(response, "1000.00")
        self.assertContains(response, "50.00%")
        self.assertContains(response, "月度合计")

    def test_invalid_month_falls_back_instead_of_erroring(self):
        login_with_company(self.client, self.admin, self.company)

        for params in ({"year": "abc", "month": "8"}, {"year": "2026", "month": "13"}, {"month": "0"}):
            with self.subTest(params=params):
                self.assertEqual(
                    self.client.get(reverse("reports:monthly_comparison"), params).status_code, 200
                )

    def test_export_returns_a_workbook_named_after_the_company_and_month(self):
        login_with_company(self.client, self.admin, self.company)

        response = self.client.get(
            reverse("reports:monthly_comparison_export"), {"year": 2026, "month": 8}
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("comparison-A-202608.xlsx", response["Content-Disposition"])

    def test_report_viewer_can_open_the_comparison(self):
        viewer = User.objects.create_user("viewer")
        viewer.groups.add(Group.objects.get(name="report_viewer"))
        login_with_company(self.client, viewer, self.company)

        self.assertEqual(self.client.get(reverse("reports:monthly_comparison")).status_code, 200)

    def test_sales_role_can_open_the_comparison(self):
        """对比表现在与明细同口径。此前只放管理员和 report_viewer，理由是导入会
        自动给业务员建归属、业务员会因此蒙到全公司汇总；而明细本身已经放开到全
        公司可见，再挡着对比表就没有意义了。"""
        seller = User.objects.create_user("seller")
        seller.groups.add(Group.objects.get(name="sales"))
        login_with_company(self.client, seller, self.company)

        self.assertEqual(self.client.get(reverse("reports:monthly_comparison")).status_code, 200)

    def test_a_salesperson_with_assignments_can_open_the_comparison(self):
        seller = User.objects.create_user("both_sides")
        SalesAssignment.objects.create(customer=self.customer, user=seller)
        PurchaseAssignment.objects.create(supplier=self.supplier, user=seller)
        login_with_company(self.client, seller, self.company)

        self.assertEqual(self.client.get(reverse("reports:monthly_comparison")).status_code, 200)

    def test_a_user_with_no_business_role_still_cannot_open_the_comparison(self):
        """放开给业务线成员，不等于放开给任何登录用户。"""
        outsider = User.objects.create_user("outsider")
        login_with_company(self.client, outsider, self.company)

        self.assertEqual(self.client.get(reverse("reports:monthly_comparison")).status_code, 403)
        self.assertEqual(
            self.client.get(reverse("reports:monthly_comparison_export")).status_code, 403
        )

    def test_comparison_link_is_offered_to_a_salesperson_with_assignments(self):
        """导航入口和视图门禁必须同一条规则，否则会出现看得到链接点进去 403，
        或者能访问却找不到入口。"""
        seller = User.objects.create_user("assigned")
        SalesAssignment.objects.create(customer=self.customer, user=seller)
        PurchaseAssignment.objects.create(supplier=self.supplier, user=seller)
        login_with_company(self.client, seller, self.company)

        self.assertContains(self.client.get(reverse("sales:shipment_list")), "采销对比")

    def test_navigation_offers_the_comparison_to_permitted_users(self):
        login_with_company(self.client, self.admin, self.company)

        response = self.client.get(reverse("sales:shipment_list"))

        self.assertContains(response, "采销对比")
