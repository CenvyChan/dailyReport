"""分析页筛选栏的行为。

预设区间原先有个真实 bug：条件写成 `if preset and not (start or end)`，
即只在两个日期框都空时才生效。但预设按钮是 submit，提交时会把日期框的当前值
一起带上——用户筛过一次日期之后再点「本月」就完全没反应，图表也不动。
"""

from datetime import date
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import RequestFactory, TestCase
from django.urls import reverse

from core.models import Customer
from core.testing import company_a, login_with_company
from reports.views import _filters, _resolve_names
from sales.models import SalesShipment


class PresetOverridesStaleDatesTests(TestCase):
    def setUp(self):
        self.request_factory = RequestFactory()

    def _filters_for(self, params):
        return _filters(self.request_factory.get("/", params))

    def test_preset_wins_over_dates_left_in_the_inputs(self):
        """核心回归：日期框里有旧值时，点预设仍要改写日期。"""
        stale = self._filters_for({"preset": "month", "start": "2026-06-01", "end": "2026-06-30"})

        self.assertNotEqual(stale["start"], "2026-06-01")
        self.assertNotEqual(stale["end"], "2026-06-30")

    def test_preset_fills_both_dates_when_inputs_are_empty(self):
        filters = self._filters_for({"preset": "month"})

        self.assertIsNotNone(filters["start"])
        self.assertIsNotNone(filters["end"])

    def test_an_empty_preset_leaves_manual_dates_alone(self):
        """手改日期后点「查询」提交的是 preset=''，此时不能覆盖用户填的值。"""
        filters = self._filters_for({"preset": "", "start": "2026-07-01", "end": "2026-07-15"})

        self.assertEqual(filters["start"], "2026-07-01")
        self.assertEqual(filters["end"], "2026-07-15")

    def test_an_unknown_preset_is_not_echoed_as_active(self):
        """手改 URL 传进 preset=decade 时不该把某个按钮点亮。"""
        filters = self._filters_for({"preset": "decade", "start": "2026-07-01"})

        self.assertIsNone(filters["preset"])
        self.assertEqual(filters["start"], "2026-07-01")

    def test_week_and_year_presets_also_override(self):
        for preset in ("week", "year"):
            with self.subTest(preset=preset):
                filters = self._filters_for({"preset": preset, "start": "2020-01-01"})

                self.assertNotEqual(filters["start"], "2020-01-01")


class NameResolutionTests(TestCase):
    """客户/供应商动辄上百个，原生 select 只能按首字母跳。界面改成
    input + datalist 后提交的是名称，要能映射回主键。"""

    def setUp(self):
        self.people = [{"id": 7, "label": "张三"}]
        self.counterparts = [{"id": 12, "label": "示例客户甲"}]

    def _resolve(self, **names):
        filters = {"person_id": None, "counterpart_id": None, **names}
        return _resolve_names(filters, self.people, self.counterparts)

    def test_a_matching_name_becomes_its_primary_key(self):
        filters = self._resolve(person_name="张三", counterpart_name="示例客户甲")

        self.assertEqual(filters["person_id"], "7")
        self.assertEqual(filters["counterpart_id"], "12")

    def test_a_name_that_matches_nothing_is_treated_as_no_filter(self):
        """用户输了一半就回车，不该报错也不该乱筛。"""
        filters = self._resolve(person_name="张", counterpart_name="不存在的客户")

        self.assertIsNone(filters["person_id"])
        self.assertIsNone(filters["counterpart_id"])

    def test_blank_names_leave_the_filters_untouched(self):
        filters = self._resolve(person_name="", counterpart_name="")

        self.assertIsNone(filters["person_id"])
        self.assertIsNone(filters["counterpart_id"])


class DashboardFilterIntegrationTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser("admin", password="pw")
        self.company = company_a()
        self.customer = Customer.objects.create(company=self.company, name="示例客户甲")
        other = Customer.objects.create(company=self.company, name="示例客户乙")
        for customer, day, amount in (
            (self.customer, 10, "100.00"),
            (other, 11, "200.00"),
        ):
            SalesShipment.objects.create(
                company=self.company,
                customer=customer,
                owner=self.admin,
                sale_type="DOMESTIC",
                shipment_date=date(2026, 8, day),
                quantity=1,
                currency="CNY",
                original_amount=Decimal(amount),
                exchange_rate=Decimal("1"),
                amount_cny=Decimal(amount),
            )
        login_with_company(self.client, self.admin, self.company)

    def test_the_counterpart_input_is_offered_with_a_datalist(self):
        response = self.client.get(reverse("reports:sales_dashboard"))

        self.assertContains(response, 'list="counterpart-options"')
        self.assertContains(response, "示例客户甲")

    def test_filtering_by_customer_name_narrows_the_summary(self):
        response = self.client.get(
            reverse("reports:sales_dashboard"), {"counterpart": "示例客户甲"}
        )

        self.assertEqual(response.context["dashboard"]["summary"]["amount_cny"], Decimal("100.00"))

    def test_the_typed_name_is_echoed_back_into_the_input(self):
        response = self.client.get(
            reverse("reports:sales_dashboard"), {"counterpart": "示例客户甲"}
        )

        self.assertEqual(response.context["filters"]["counterpart_name"], "示例客户甲")

    def test_export_honours_the_same_name_filter_as_the_page(self):
        """口径不一致的话，用户按客户筛完再导出会拿到全部数据。"""
        response = self.client.get(reverse("reports:sales_export"), {"counterpart": "示例客户甲"})

        self.assertEqual(response.status_code, 200)
        self.assertGreater(len(response.content), 0)

    def test_the_json_api_honours_the_name_filter_too(self):
        response = self.client.get(
            reverse("reports:sales_dashboard_api"), {"counterpart": "示例客户甲"}
        )

        # JSON 里 Decimal 会去掉末尾的零，比数值不比字符串
        self.assertEqual(Decimal(response.json()["summary"]["amount_cny"]), Decimal("100"))
