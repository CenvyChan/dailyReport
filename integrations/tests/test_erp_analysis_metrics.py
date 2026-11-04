from datetime import date
from decimal import Decimal

from django.test import SimpleTestCase

from integrations.services.erp_analysis.calculators import (
    inventory,
    production,
    purchase,
    receivable,
    sales,
    subcontract,
)
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
