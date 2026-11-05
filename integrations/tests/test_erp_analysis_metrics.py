from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from django.template.loader import render_to_string
from django.test import SimpleTestCase

from integrations.services.erp_analysis.calculators import (
    inventory,
    production,
    purchase,
    receivable,
    sales,
    subcontract,
)
from integrations.services.erp_analysis.presentation import supporting_charts, trend_chart
from integrations.services.erp_analysis.common import parse_date, period_window


class AnalysisMetricTests(SimpleTestCase):
    def test_period_and_slash_date(self):
        self.assertEqual(parse_date("2026/5/4"), date(2026, 5, 4))
        self.assertEqual(parse_date("2026-05-04T08:30:00"), date(2026, 5, 4))
        self.assertIsNone(parse_date("2026/2/31"))
        self.assertEqual(period_window(date(2026, 1, 1), 12)[0][0], date(2025, 2, 1))

    def test_purchase_delivery_uses_entries_and_preserves_overdelivery(self):
        rows = [
            {
                "bill": "PO1",
                "date": date(2026, 5, 1),
                "supplier": "S",
                "material": "M",
                "org": "O",
                "qty": Decimal(0),
                "received": Decimal(7),
                "stockin": Decimal(0),
                "amount": Decimal(100),
                "payable": Decimal(90),
                "settled": Decimal(100),
                "unsettled": Decimal(0),
                "due": date(2026, 5, 31),
            }
        ]
        entries = [
            {
                "bill": "PO1",
                "entry": "1",
                "date": date(2026, 5, 1),
                "supplier": "S",
                "material": "M",
                "qty": Decimal(5),
                "remaining": Decimal(-2),
                "due": date(2026, 5, 31),
            }
        ]
        report = purchase(rows, entries, date(2026, 6, 1))
        self.assertEqual(report["metrics"]["delivery"]["over_count"], 1)
        self.assertEqual(report["metrics"]["delivery"]["entry_count"], 1)
        self.assertGreater(report["metrics"]["summary"]["settlement_rate"], 100)

    def test_receivable_does_not_recompute_plan_debt_from_head(self):
        heads = [{"bill": "AR1", "date": date(2026, 5, 4), "customer": "C", "amount": Decimal(100)}]
        plans = [{"bill": "AR1", "settled": Decimal(60), "unsettled": Decimal(50)}]
        result = receivable(heads, plans)["metrics"]["summary"]
        self.assertEqual(result["unsettled"], 50)
        self.assertEqual(result["head_plan_diff"], -10)

    def test_sales_funnel_uses_two_different_denominators_and_keeps_negative_debt(self):
        rows = [
            {
                "bill": "SO1",
                "date": date(2026, 5, 4),
                "customer": "C",
                "material": "M",
                "salesperson": "P",
                "out": Decimal(100),
                "receivable": Decimal(50),
                "settled": Decimal(60),
                "unsettled": Decimal(-10),
            }
        ]
        result = sales(rows)["metrics"]
        self.assertEqual(result["summary"]["settlement_rate"], 60)
        self.assertEqual(result["monthly"][0]["settlement_rate"], 120)
        self.assertEqual(result["summary"]["unsettled"], -10)

    def test_inventory_uses_global_period_count_and_latest_stock_only(self):
        base = {
            "name": "M",
            "group": "G",
            "warehouse": "W",
            "init_qty": Decimal(0),
            "init_amount": Decimal(0),
            "in_qty": Decimal(0),
            "in_amount": Decimal(0),
            "out_amount": Decimal(0),
            "end_amount": Decimal(0),
        }
        rows = [
            dict(base, code="M", period="2026-04", out_qty=Decimal(10), end_qty=Decimal(20)),
            dict(base, code="N", period="2026-05", out_qty=Decimal(0), end_qty=Decimal(0)),
        ]
        result = inventory(rows)["metrics"]
        material = next(item for item in result["materials"] if item["code"] == "M")
        self.assertEqual(material["avg_out"], 5)
        self.assertEqual(material["end_qty"], 0)
        self.assertEqual(result["summary"]["latest_period"], "2026-05")
        self.assertEqual(len(result["buckets"]), 7)

    def test_production_overdue_does_not_require_backlog_and_uses_reference_date(self):
        row = {
            "bill": "MO1",
            "entry": "1",
            "date": date(2026, 5, 4),
            "material": "M",
            "workshop": "W",
            "status": "3",
            "bill_type": "标准",
            "qty": Decimal(5),
            "stockin": Decimal(5),
            "remaining": Decimal(0),
            "plan_start": None,
            "due": date(2026, 5, 31),
            "start": date(2026, 5, 4),
            "finish": None,
        }
        result = production([row], [], date(2026, 6, 1))["metrics"]
        self.assertEqual(result["summary"]["overdue_count"], 1)
        self.assertEqual(result["backlog"], [])

    def test_subcontract_wip_keeps_erp_values_and_good_return(self):
        row = {
            "bill": "B1",
            "entry": "1",
            "supplier": "S",
            "parent": "P",
            "material": "M",
            "order": "O",
            "must": Decimal(25),
            "picked": Decimal(25),
            "consumed": Decimal("10.171"),
            "defect_return": Decimal(0),
            "good_return": Decimal(9),
            "wip": Decimal("5.829"),
            "not_picked": Decimal(0),
        }
        negative = dict(
            row, bill="B2", picked=Decimal(0), consumed=Decimal(10), good_return=Decimal(0), wip=Decimal(-10)
        )
        result = subcontract([], [], [row, negative], date(2026, 6, 1))["metrics"]["wip"]
        self.assertEqual(result["unbalanced_count"], 0)
        self.assertEqual(result["negative_count"], 1)
        self.assertEqual(result["wip"], Decimal("-4.171"))

    def test_empty_data_preserves_report_sections(self):
        results = [
            purchase([], [], date(2026, 6, 1)),
            receivable([], []),
            sales([]),
            inventory([]),
            production([], [], date(2026, 6, 1)),
            subcontract([], [], [], date(2026, 6, 1)),
        ]
        for result in results:
            self.assertTrue(result["sections"])
            self.assertTrue(all(section["headers"] for section in result["sections"]))


class AnalysisPresentationTests(SimpleTestCase):
    def test_single_month_has_no_empty_trend_line(self):
        self.assertIsNone(
            trend_chart(
                "purchase",
                {"metrics": {"monthly": [{"month": "2026-10", "amount": 100, "settled": 20, "unsettled": 80}]}},
            )
        )
        chart = trend_chart(
            "purchase",
            {"metrics": {"monthly": [{"month": "2026-09", "amount": 100}, {"month": "2026-10", "amount": 120}]}},
        )
        self.assertEqual(len(chart["labels"]), 2)


    def test_trend_hover_keeps_monthly_values_and_amount_units(self):
        data = {"metrics": {"monthly": [
            {"month": "2026-09", "amount": "1234.56", "settled": "20.01", "unsettled": "1214.55"},
            {"month": "2026-10", "amount": "-12.34", "settled": "0", "unsettled": "-12.34"},
        ]}}
        chart = trend_chart("purchase", data)
        self.assertEqual(chart["unit_label"], "金额（元）")
        self.assertEqual([sample["month"] for sample in chart["samples"]], ["2026-09", "2026-10"])
        self.assertEqual(
            [(value["label"], value["text"]) for value in chart["samples"][0]["values"]],
            [("订单金额", "1,234.56"), ("已结算", "20.01"), ("未结算", "1,214.55")],
        )
        self.assertEqual(chart["samples"][1]["values"][0]["text"], "-12.34")
        self.assertIn("2026-09", chart["samples"][0]["description"])
        self.assertIn("订单金额：1,234.56", chart["samples"][0]["description"])
        for sample in chart["samples"]:
            self.assertGreater(sample["hit_width"], 0)
            self.assertGreaterEqual(sample["tooltip_x"], 8)
            self.assertLessEqual(sample["tooltip_x"] + 230, 892)
        for series_index, line in enumerate(chart["lines"]):
            for sample, coordinates in zip(chart["samples"], line["points"].split(), strict=True):
                self.assertEqual(coordinates, f"{sample['x']},{sample['values'][series_index]['y']}")
        self.assertEqual(data["metrics"]["monthly"][0]["amount"], "1234.56")

    def test_trend_hover_quantity_precision_and_unrecognized_month(self):
        chart = trend_chart("production", {"metrics": {"monthly": [
            {"month": "2026-09", "qty": "1234.56789", "stockin": "0", "remaining": "-2.500"},
            {"month": "未识别", "qty": "99999"},
            {"month": "2026-10", "qty": "12"},
        ]}})
        self.assertEqual(chart["unit_label"], "数量（原始单位）")
        self.assertEqual([sample["month"] for sample in chart["samples"]], ["2026-09", "2026-10"])
        self.assertEqual([v["text"] for v in chart["samples"][0]["values"]], ["1,234.56789", "0", "-2.5"])

    def test_trend_hover_is_available_for_all_six_reports(self):
        for kind in ("purchase", "receivable", "inventory", "sales", "production", "subcontract"):
            with self.subTest(kind=kind):
                chart = trend_chart(kind, {"metrics": {"monthly": [{"month": "2026-09"}, {"month": "2026-10"}]}})
                self.assertEqual(len(chart["samples"]), 2)
                self.assertTrue(all(len(sample["values"]) == 3 for sample in chart["samples"]))

    def test_html_trend_hover_is_keyboard_accessible_and_escaped(self):
        chart = trend_chart("purchase", {"metrics": {"monthly": [
            {"month": '<script>alert("hover")</script>', "amount": "1234.56"},
            {"month": "2026-10", "amount": "5"},
        ]}})
        html = render_to_string("reports/erp_analysis_report.html", {
            "task": SimpleNamespace(company=SimpleNamespace(name="Test"), period=date(2026, 10, 1), org_number="001", created_at=None),
            "title": "采购执行分析", "report": {"cards": [], "sections": [], "notes": []},
            "chart": chart, "supporting_charts": [],
        })
        self.assertEqual(html.count('class="trend-sample"'), 2)
        self.assertEqual(html.count('class="trend-point"'), 6)
        self.assertIn('tabindex="0" role="group"', html)
        self.assertIn('.trend-sample:hover .trend-tooltip', html)
        self.assertIn('.trend-sample:focus-visible .trend-tooltip', html)
        self.assertIn('class="trend-tooltip"', html)
        self.assertIn("订单金额：1,234.56", html)
        self.assertNotIn('<script>alert("hover")</script>', html)
        self.assertIn('&lt;script&gt;', html)


class SupportingChartTests(SimpleTestCase):
    def test_purchase_has_real_amount_delivery_and_supplier_charts(self):
        data = {
            "metrics": {
                "summary": {"payable": "100", "settled": "30", "unsettled": "70"},
                "delivery": {"entry_count": 10, "exact_count": 6, "short_count": 3, "over_count": 1},
                "rankings": {"supplier": [{"name": "供应商甲", "unsettled": "70"}]},
            }
        }
        charts = supporting_charts("purchase", data)
        self.assertEqual([chart["type"] for chart in charts], ["bar", "donut", "bar"])
        self.assertEqual(charts[1]["total"], "10")
        self.assertEqual([item["value"] for item in charts[1]["items"]], ["6", "3", "1"])
        self.assertEqual(charts[2]["items"][0]["label"], "供应商甲")
        self.assertEqual(charts[2]["items"][0]["value"], "70")

    def test_sales_negative_debt_is_drawn_left_of_zero(self):
        charts = supporting_charts(
            "sales",
            {
                "metrics": {
                    "summary": {"out": 100, "receivable": 90, "settled": 110},
                    "customers": [{"name": "超收客户", "unsettled": -20}, {"name": "欠款客户", "unsettled": 30}],
                }
            },
        )
        item = next(item for item in charts[1]["items"] if item["value"] == "-20")
        self.assertLess(item["x"], charts[1]["zero_x"])
        self.assertGreater(item["width"], 0)

    def test_empty_chart_does_not_invent_a_full_donut(self):
        from integrations.services.erp_analysis.presentation import donut_chart

        chart = donut_chart("empty", "无数据", [("交齐", 0), ("欠交", 0)], "分录数")
        self.assertTrue(chart["empty"])
        self.assertEqual(chart["segments"], [])
        self.assertEqual(chart["total"], "0")

    def test_inventory_negative_amount_uses_bar_not_pie(self):
        charts = supporting_charts(
            "inventory",
            {
                "metrics": {
                    "buckets": [{"name": "正库存", "amount": 100}, {"name": "负库存", "amount": -10}],
                    "materials": [],
                }
            },
        )
        self.assertEqual(charts[0]["type"], "bar")
        self.assertIn("-10", [item["value"] for item in charts[0]["items"]])

    def test_all_six_reports_have_chart_sections_without_data(self):
        for kind in ("purchase", "receivable", "inventory", "sales", "production", "subcontract"):
            charts = supporting_charts(kind, {"metrics": {}})
            self.assertTrue(charts)
            self.assertTrue(all(chart["empty"] for chart in charts))
