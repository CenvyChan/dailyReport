"""日报列表的日期筛选。

默认本月而不是当天：日报不是每天都录（周末、假期、补录），线上就出现过最近一条
停在四天前的情况。默认当天时打开列表一片空白，看起来像权限出了问题。

翻页按钮按当前区间长度整段前后移，目标区间由服务端算（step 参数），所以禁用
JS 也能用。此前是在模板里拼 URL 跳转，Django 把 & 转义成 &amp;，参数名变成
amp;end——结束日期根本没传出去，翻页后只剩开始日期。
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

    def test_no_parameters_defaults_to_the_current_month(self):
        resolved = self._resolve()

        self.assertEqual(resolved["start"], date(2026, 8, 1))
        self.assertEqual(resolved["end"], TODAY)
        self.assertEqual(resolved["preset"], "month")

    def test_explicit_dates_win_over_the_preset(self):
        """点翻页传的是具体日期，此时不能再被 preset 顶掉——分析页踩过这个坑。"""
        resolved = self._resolve({"preset": "month", "start": "2026-07-03", "end": "2026-07-03"})

        self.assertEqual(resolved["start"], date(2026, 7, 3))
        self.assertIsNone(resolved["preset"])

    def test_only_one_end_of_the_range_is_filled_out_to_a_single_day(self):
        """否则「前一天」会退化成开区间，翻页步长也算不出来。"""
        resolved = self._resolve({"start": "2026-07-03"})

        self.assertEqual(resolved["start"], date(2026, 7, 3))
        self.assertEqual(resolved["end"], date(2026, 7, 3))

    def test_all_means_no_date_limit(self):
        resolved = self._resolve({"preset": "all"})

        self.assertIsNone(resolved["start"])
        self.assertIsNone(resolved["end"])

    def test_day_preset_narrows_to_today(self):
        resolved = self._resolve({"preset": "day"})

        self.assertEqual(resolved["start"], TODAY)
        self.assertEqual(resolved["end"], TODAY)

    def test_week_starts_on_monday(self):
        resolved = self._resolve({"preset": "week"})

        self.assertEqual(resolved["start"], TODAY - timedelta(days=TODAY.weekday()))

    def test_year_starts_in_january(self):
        resolved = self._resolve({"preset": "year"})

        self.assertEqual(resolved["start"], date(2026, 1, 1))

    def test_an_unknown_preset_falls_back_to_the_default(self):
        """手改 URL 传 preset=decade 不该 500，也不该变成全部。"""
        resolved = self._resolve({"preset": "decade"})

        self.assertEqual(resolved["preset"], "month")

    def test_a_malformed_date_is_ignored_rather_than_crashing(self):
        resolved = self._resolve({"start": "abc"})

        self.assertEqual(resolved["preset"], "month")


class SteppingTests(SimpleTestCase):
    """翻页步长跟随当前区间长度：看单日翻一天，看一段整段移。"""

    def setUp(self):
        self.request_factory = RequestFactory()

    def _resolve(self, params):
        return date_filter.resolve(self.request_factory.get("/", params), today=TODAY)

    def test_a_single_day_steps_by_one_day(self):
        resolved = self._resolve({"start": "2026-08-20", "end": "2026-08-20"})

        self.assertEqual(resolved["span"], 1)
        self.assertEqual(resolved["prev_start"], date(2026, 8, 19))
        self.assertEqual(resolved["next_start"], date(2026, 8, 21))

    def test_a_week_steps_by_seven_days(self):
        resolved = self._resolve({"start": "2026-08-17", "end": "2026-08-23"})

        self.assertEqual(resolved["span"], 7)
        self.assertEqual(resolved["prev_start"], date(2026, 8, 10))
        self.assertEqual(resolved["prev_end"], date(2026, 8, 16))
        self.assertEqual(resolved["next_start"], date(2026, 8, 24))

    def test_stepping_back_is_applied_server_side(self):
        """服务端处理 step 参数，禁用 JS 也能翻页。"""
        resolved = self._resolve({"start": "2026-08-20", "end": "2026-08-20", "step": "prev"})

        self.assertEqual(resolved["start"], date(2026, 8, 19))
        self.assertEqual(resolved["end"], date(2026, 8, 19))

    def test_stepping_forward_moves_the_whole_range(self):
        resolved = self._resolve({"start": "2026-08-01", "end": "2026-08-07", "step": "next"})

        self.assertEqual(resolved["start"], date(2026, 8, 8))
        self.assertEqual(resolved["end"], date(2026, 8, 14))

    def test_an_unknown_step_value_is_ignored(self):
        resolved = self._resolve({"start": "2026-08-20", "end": "2026-08-20", "step": "sideways"})

        self.assertEqual(resolved["start"], date(2026, 8, 20))

    def test_all_dates_cannot_be_stepped(self):
        """没有区间就没有「前一段」可言。"""
        resolved = self._resolve({"preset": "all"})

        self.assertFalse(resolved["can_step"])
        self.assertIsNone(resolved["prev_start"])

    def test_the_step_label_tells_the_user_how_far(self):
        self.assertEqual(self._resolve({"start": "2026-08-20", "end": "2026-08-20"})["step_label"], "一天")
        self.assertEqual(self._resolve({"start": "2026-08-17", "end": "2026-08-23"})["step_label"], "7 天")


class LabelTests(SimpleTestCase):
    def setUp(self):
        self.request_factory = RequestFactory()

    def _label(self, params=None):
        return date_filter.resolve(
            self.request_factory.get("/", params or {}), today=TODAY
        )["label"]

    def test_today_is_spelled_out(self):
        """两个日期框摆着让用户自己换算不友好。"""
        stamp = TODAY.isoformat()

        self.assertIn("今天", self._label({"start": stamp, "end": stamp}))

    def test_yesterday_is_spelled_out(self):
        stamp = (TODAY - timedelta(days=1)).isoformat()

        self.assertIn("昨天", self._label({"start": stamp, "end": stamp}))

    def test_a_range_is_shown_as_a_range(self):
        self.assertIn("至", self._label({"start": "2026-07-01", "end": "2026-07-31"}))

    def test_all_dates_says_so(self):
        self.assertEqual(self._label({"preset": "all"}), "全部日期")


class ShipmentListDateFilterTests(TestCase):
    def setUp(self):
        self.company = company_a()
        self.user = User.objects.create_user("sales-a", first_name="销售甲")
        self.user.groups.add(Group.objects.get(name="sales"))
        self.today = date.today()
        # 本月内一条、上个月一条，用来区分默认口径
        self.this_month = self._shipment("本月的", self.today.replace(day=1))
        last_month_day = self.today.replace(day=1) - timedelta(days=5)
        self.last_month = self._shipment("上月的", last_month_day)
        login_with_company(self.client, self.user, self.company)

    def _shipment(self, name, day):
        customer = Customer.objects.create(company=self.company, name=name)
        SalesAssignment.objects.create(user=self.user, customer=customer)
        return SalesShipment.objects.create(
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

    def test_the_list_defaults_to_the_current_month(self):
        """默认当天的话，没录入的日子里打开就是一片空白。"""
        response = self.client.get(reverse("sales:shipment_list"))

        self.assertContains(response, "本月的")
        self.assertNotContains(response, "上月的")

    def test_the_date_inputs_are_prefilled_with_the_current_range(self):
        """翻页按钮作用于这两个框，所以它们必须反映当前口径。"""
        response = self.client.get(reverse("sales:shipment_list"))

        self.assertEqual(response.context["start"], self.today.replace(day=1).isoformat())
        self.assertEqual(response.context["end"], self.today.isoformat())

    def test_the_filter_bar_offers_stepping_buttons(self):
        response = self.client.get(reverse("sales:shipment_list"))

        self.assertContains(response, 'name="step" value="prev"')
        self.assertContains(response, 'name="step" value="next"')

    def test_stepping_back_a_month_finds_the_older_record(self):
        """核心回归：翻页必须同时改写开始和结束日期。此前 &amp; 转义让 end
        丢失，翻完只剩开始日期，口径变成「某天起」。"""
        first = self.today.replace(day=1)
        response = self.client.get(
            reverse("sales:shipment_list"),
            {"start": first.isoformat(), "end": self.today.isoformat(), "step": "prev"},
        )

        self.assertContains(response, "上月的")
        self.assertNotContains(response, "本月的")

    def test_stepping_keeps_both_ends_of_the_range(self):
        response = self.client.get(
            reverse("sales:shipment_list"),
            {"start": "2026-08-10", "end": "2026-08-16", "step": "prev"},
        )

        self.assertEqual(response.context["dates"]["start"], date(2026, 8, 3))
        self.assertEqual(response.context["dates"]["end"], date(2026, 8, 9))

    def test_the_day_preset_narrows_to_today(self):
        response = self.client.get(reverse("sales:shipment_list"), {"preset": "day"})

        self.assertEqual(response.context["dates"]["preset"], "day")

    def test_all_shows_everything(self):
        response = self.client.get(reverse("sales:shipment_list"), {"preset": "all"})

        self.assertContains(response, "本月的")
        self.assertContains(response, "上月的")

    def test_the_totals_follow_the_date_filter(self):
        """合计必须和列表同口径，否则用户会怀疑哪个数是对的。"""
        response = self.client.get(reverse("sales:shipment_list"))

        self.assertEqual(response.context["totals"]["amount_cny"], Decimal("100"))

    def test_search_survives_a_step(self):
        response = self.client.get(
            reverse("sales:shipment_list"),
            {"q": "本月", "start": "2026-08-10", "end": "2026-08-10", "step": "next"},
        )

        self.assertEqual(response.context["search"], "本月")

    def test_the_purchase_list_behaves_the_same(self):
        buyer = User.objects.create_user("purchase-a")
        buyer.groups.add(Group.objects.get(name="purchase"))
        login_with_company(self.client, buyer, self.company)

        response = self.client.get(reverse("purchase:receipt_list"))

        self.assertContains(response, 'name="step" value="prev"')
        self.assertEqual(response.context["dates"]["preset"], "month")


class PageNumberTests(TestCase):
    """页码直达。此前只有首页/上一页/下一页/末页，要跳到第 7 页得连点六次。"""

    def setUp(self):
        self.company = company_a()
        self.admin = User.objects.create_superuser("admin", password="pw")
        customer = Customer.objects.create(company=self.company, name="示例客户")
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
        response = self.client.get(reverse("sales:shipment_list"), {"preset": "year", "page": 2})

        self.assertContains(response, "preset=year")

    def test_a_short_list_has_no_jump_box(self):
        """三页的表不需要输页码，多一个控件反而是噪音。"""
        SalesShipment.objects.filter(pk__in=SalesShipment.objects.values_list("pk")[60:]).delete()

        response = self.client.get(reverse("sales:shipment_list"))

        self.assertNotContains(response, "page-jump")


class SearchScopeTests(TestCase):
    """搜索和日期筛选是两种意图，不能混在一起联动。

    真实问题：日期框是预填的（默认本月），用户在搜索框打「高」点查询，表单会把
    预填的日期一起交上去，于是变成「本月内含高的记录」——搜不全，而且「本月」的
    高亮消失，看起来像搜索改动了日期。
    """

    def setUp(self):
        self.company = company_a()
        self.admin = User.objects.create_superuser("admin", password="pw")
        self.today = date.today()
        self._shipment("高席的本月单", self.today)
        self._shipment("高席的旧单", self.today.replace(day=1) - timedelta(days=40))
        login_with_company(self.client, self.admin, self.company)

    def _shipment(self, name, day):
        customer = Customer.objects.create(company=self.company, name=name)
        SalesShipment.objects.create(
            company=self.company,
            customer=customer,
            owner=self.admin,
            sale_type="DOMESTIC",
            shipment_date=day,
            quantity=1,
            currency="CNY",
            original_amount=Decimal("1"),
            exchange_rate=Decimal("1"),
            amount_cny=Decimal("1"),
        )

    def test_search_all_time_ignores_the_prefilled_dates(self):
        """核心回归：scope=all 必须压过日期框里的值。"""
        response = self.client.get(
            reverse("sales:shipment_list"),
            {
                "q": "高席",
                "scope": "all",
                "start": self.today.replace(day=1).isoformat(),
                "end": self.today.isoformat(),
            },
        )

        self.assertContains(response, "高席的本月单")
        self.assertContains(response, "高席的旧单")
        self.assertIsNone(response.context["dates"]["start"])

    def test_searching_within_a_date_range_is_still_possible(self):
        """两种意图都要能表达：按日期查询时搜索仍受区间限制。"""
        response = self.client.get(
            reverse("sales:shipment_list"),
            {
                "q": "高席",
                "preset": "",
                "start": self.today.replace(day=1).isoformat(),
                "end": self.today.isoformat(),
            },
        )

        self.assertContains(response, "高席的本月单")
        self.assertNotContains(response, "高席的旧单")

    def test_the_search_box_has_its_own_submit_button(self):
        response = self.client.get(reverse("sales:shipment_list"))

        self.assertContains(response, 'name="scope" value="all"')

    def test_the_search_sits_on_its_own_row(self):
        """搜索和日期分行，各自带提交按钮，两种意图不互相干扰。"""
        response = self.client.get(reverse("sales:shipment_list"))

        self.assertContains(response, "df-search-line")

    def test_a_narrowed_search_offers_a_way_out(self):
        """按日期搜完发现漏了，要能一键改成全时间。"""
        response = self.client.get(
            reverse("sales:shipment_list"),
            {"q": "高席", "preset": "", "start": "2026-08-01", "end": "2026-08-25"},
        )

        self.assertContains(response, "在全部时间里搜")

    def test_scope_all_wins_even_with_a_preset(self):
        response = self.client.get(
            reverse("sales:shipment_list"), {"q": "高席", "scope": "all", "preset": "day"}
        )

        self.assertEqual(response.context["dates"]["preset"], "all")

    def test_the_search_term_is_echoed_back(self):
        response = self.client.get(
            reverse("sales:shipment_list"), {"q": "高席", "scope": "all"}
        )

        self.assertEqual(response.context["search"], "高席")
