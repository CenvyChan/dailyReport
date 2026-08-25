"""日报列表的日期筛选。

日报是每天录的，打开列表最常见的意图是「看今天录了什么」，所以默认只显示当天，
并给前一天/后一天的翻页——这比每次手填两个日期快得多。
"""

from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth.models import Group, User
from django.test import RequestFactory, SimpleTestCase, TestCase
from django.urls import reverse

from core.models import Customer, SalesAssignment
from core.services import date_filter
from core.testing import company_a, login_with_company
from sales.models import SalesShipment

TODAY = date(2026, 8, 25)


class ResolveTests(SimpleTestCase):
    def setUp(self):
        self.request_factory = RequestFactory()

    def _resolve(self, params=None):
        return date_filter.resolve(self.request_factory.get("/", params or {}), today=TODAY)

    def test_no_parameters_defaults_to_today(self):
        resolved = self._resolve()

        self.assertEqual(resolved["start"], TODAY)
        self.assertEqual(resolved["end"], TODAY)
        self.assertEqual(resolved["preset"], "day")

    def test_explicit_dates_win_over_the_preset(self):
        """点「前一天」传的是具体日期，此时不能再被 preset 顶掉——
        分析页就踩过这个坑（预设按钮完全没反应）。"""
        resolved = self._resolve({"preset": "month", "start": "2026-07-03", "end": "2026-07-03"})

        self.assertEqual(resolved["start"], date(2026, 7, 3))
        self.assertIsNone(resolved["preset"])

    def test_all_means_no_date_limit(self):
        resolved = self._resolve({"preset": "all"})

        self.assertIsNone(resolved["start"])
        self.assertIsNone(resolved["end"])

    def test_week_starts_on_monday(self):
        resolved = self._resolve({"preset": "week"})

        self.assertEqual(resolved["start"], TODAY - timedelta(days=TODAY.weekday()))
        self.assertEqual(resolved["end"], TODAY)

    def test_month_starts_on_the_first(self):
        resolved = self._resolve({"preset": "month"})

        self.assertEqual(resolved["start"], date(2026, 8, 1))

    def test_year_starts_in_january(self):
        resolved = self._resolve({"preset": "year"})

        self.assertEqual(resolved["start"], date(2026, 1, 1))

    def test_an_unknown_preset_falls_back_to_today(self):
        """手改 URL 传 preset=decade 不该 500，也不该变成全部。"""
        resolved = self._resolve({"preset": "decade"})

        self.assertEqual(resolved["preset"], "day")
        self.assertEqual(resolved["start"], TODAY)

    def test_a_malformed_date_is_ignored_rather_than_crashing(self):
        resolved = self._resolve({"start": "abc"})

        self.assertEqual(resolved["start"], TODAY)


class DaySteppingTests(SimpleTestCase):
    def setUp(self):
        self.request_factory = RequestFactory()

    def _resolve(self, params=None):
        return date_filter.resolve(self.request_factory.get("/", params or {}), today=TODAY)

    def test_single_day_offers_both_arrows(self):
        resolved = self._resolve()

        self.assertTrue(resolved["is_single_day"])
        self.assertEqual(resolved["prev_day"], TODAY - timedelta(days=1))
        self.assertEqual(resolved["next_day"], TODAY + timedelta(days=1))

    def test_a_range_has_no_arrows(self):
        """跨多天时「前一天」没有明确含义。"""
        resolved = self._resolve({"preset": "month"})

        self.assertFalse(resolved["is_single_day"])
        self.assertIsNone(resolved["prev_url"])
        self.assertIsNone(resolved["next_url"])

    def test_the_step_url_keeps_other_parameters(self):
        """手拼链接会漏掉 size、q 之类的参数，翻一天就把筛选条件丢了。"""
        resolved = date_filter.resolve(
            self.request_factory.get("/", {"q": "某客户", "size": "100"}), today=TODAY
        )

        self.assertIn("q=", resolved["prev_url"])
        self.assertIn("size=100", resolved["prev_url"])

    def test_the_step_url_clears_the_preset(self):
        """否则跳到具体某天后又会被预设改回今天。"""
        resolved = self._resolve()

        self.assertIn("preset=&", resolved["prev_url"] + "&")

    def test_the_step_url_drops_the_page_number(self):
        """换了日期还停在第 7 页会看到空列表。"""
        resolved = date_filter.resolve(
            self.request_factory.get("/", {"page": "7"}), today=TODAY
        )

        self.assertNotIn("page=", resolved["prev_url"])


class LabelTests(SimpleTestCase):
    def setUp(self):
        self.request_factory = RequestFactory()

    def _label(self, params=None):
        return date_filter.resolve(
            self.request_factory.get("/", params or {}), today=TODAY
        )["label"]

    def test_today_is_spelled_out(self):
        """两个日期框摆着让用户自己换算不友好。"""
        self.assertIn("今天", self._label())

    def test_yesterday_is_spelled_out(self):
        stamp = (TODAY - timedelta(days=1)).isoformat()

        self.assertIn("昨天", self._label({"start": stamp, "end": stamp}))

    def test_a_range_is_shown_as_a_range(self):
        label = self._label({"start": "2026-07-01", "end": "2026-07-31"})

        self.assertIn("至", label)

    def test_all_dates_says_so(self):
        self.assertEqual(self._label({"preset": "all"}), "全部日期")


class ShipmentListDateFilterTests(TestCase):
    def setUp(self):
        self.company = company_a()
        self.user = User.objects.create_user("sales-a", first_name="销售甲")
        self.user.groups.add(Group.objects.get(name="sales"))
        self.customer = Customer.objects.create(company=self.company, name="示例客户")
        SalesAssignment.objects.create(user=self.user, customer=self.customer)
        self.today = date.today()
        for day, name in ((self.today, "今天的"), (self.today - timedelta(days=3), "三天前的")):
            customer = Customer.objects.create(company=self.company, name=name)
            SalesAssignment.objects.create(user=self.user, customer=customer)
            SalesShipment.objects.create(
                company=self.company,
                customer=customer,
                owner=self.user,
                sale_type="DOMESTIC",
                shipment_date=day,
                quantity=1,
                currency="CNY",
                original_amount=Decimal("100"),
                exchange_rate=Decimal("1"),
                amount_cny=Decimal("100"),
            )
        login_with_company(self.client, self.user, self.company)

    def test_the_list_defaults_to_today(self):
        response = self.client.get(reverse("sales:shipment_list"))

        self.assertContains(response, "今天的")
        self.assertNotContains(response, "三天前的")

    def test_the_filter_bar_offers_day_stepping(self):
        response = self.client.get(reverse("sales:shipment_list"))

        self.assertContains(response, "前一天")
        self.assertContains(response, "后一天")

    def test_stepping_back_three_days_finds_the_older_record(self):
        stamp = (self.today - timedelta(days=3)).isoformat()

        response = self.client.get(
            reverse("sales:shipment_list"), {"start": stamp, "end": stamp, "preset": ""}
        )

        self.assertContains(response, "三天前的")
        self.assertNotContains(response, "今天的")

    def test_the_month_preset_covers_both(self):
        response = self.client.get(reverse("sales:shipment_list"), {"preset": "month"})

        # 月初到今天，两条都在（除非今天是月初前三天，这里用当月判断）
        if self.today.day > 3:
            self.assertContains(response, "三天前的")
        self.assertContains(response, "今天的")

    def test_all_shows_everything(self):
        response = self.client.get(reverse("sales:shipment_list"), {"preset": "all"})

        self.assertContains(response, "今天的")
        self.assertContains(response, "三天前的")

    def test_the_totals_follow_the_date_filter(self):
        """合计必须和列表同口径，否则用户会怀疑哪个数是对的。"""
        response = self.client.get(reverse("sales:shipment_list"))

        self.assertEqual(response.context["totals"]["amount_cny"], Decimal("100"))

    def test_the_purchase_list_behaves_the_same(self):
        buyer = User.objects.create_user("purchase-a")
        buyer.groups.add(Group.objects.get(name="purchase"))
        login_with_company(self.client, buyer, self.company)

        response = self.client.get(reverse("purchase:receipt_list"))

        self.assertContains(response, "前一天")
        self.assertEqual(response.context["dates"]["preset"], "day")


class PageNumberTests(TestCase):
    """页码直达。此前只有首页/上一页/下一页/末页，要跳到第 7 页得连点六次。"""

    def setUp(self):
        self.company = company_a()
        self.admin = User.objects.create_superuser("admin", password="pw")
        customer = Customer.objects.create(company=self.company, name="示例客户")
        today = date.today()
        SalesShipment.objects.bulk_create(
            [
                SalesShipment(
                    company=self.company,
                    customer=customer,
                    owner=self.admin,
                    sale_type="DOMESTIC",
                    shipment_date=today,
                    quantity=1,
                    currency="CNY",
                    original_amount=Decimal("1"),
                    exchange_rate=Decimal("1"),
                    amount_cny=Decimal("1"),
                )
                for _ in range(430)
            ]
        )
        login_with_company(self.client, self.admin, self.company)

    def test_page_numbers_are_rendered(self):
        response = self.client.get(reverse("sales:shipment_list"))

        self.assertContains(response, "page-numbers")
        self.assertContains(response, 'class="current"')

    def test_the_current_page_is_marked_for_screen_readers(self):
        response = self.client.get(reverse("sales:shipment_list"))

        self.assertContains(response, 'aria-current="page"')

    def test_middle_pages_are_elided_when_there_are_many(self):
        """430 条 / 每页 50 = 9 页，超过窗口宽度会出现省略号。"""
        response = self.client.get(reverse("sales:shipment_list"))

        self.assertIn("…", response.content.decode())

    def test_a_jump_box_appears_for_long_lists(self):
        response = self.client.get(reverse("sales:shipment_list"))

        self.assertContains(response, "page-jump")
        self.assertContains(response, "跳至")

    def test_jumping_to_a_page_works(self):
        response = self.client.get(reverse("sales:shipment_list"), {"page": 5})

        self.assertEqual(response.context["page"].number, 5)

    def test_page_links_keep_the_date_filter(self):
        """翻页丢掉日期筛选的话，第 2 页会变成全部数据。"""
        response = self.client.get(reverse("sales:shipment_list"), {"preset": "month", "page": 2})

        self.assertContains(response, "preset=month")

    def test_a_short_list_has_no_jump_box(self):
        """三页的表不需要输页码，多一个控件反而是噪音。"""
        SalesShipment.objects.all().delete()
        customer = Customer.objects.get(name="示例客户")
        SalesShipment.objects.bulk_create(
            [
                SalesShipment(
                    company=self.company,
                    customer=customer,
                    owner=self.admin,
                    sale_type="DOMESTIC",
                    shipment_date=date.today(),
                    quantity=1,
                    currency="CNY",
                    original_amount=Decimal("1"),
                    exchange_rate=Decimal("1"),
                    amount_cny=Decimal("1"),
                )
                for _ in range(60)
            ]
        )

        response = self.client.get(reverse("sales:shipment_list"))

        self.assertNotContains(response, "page-jump")
