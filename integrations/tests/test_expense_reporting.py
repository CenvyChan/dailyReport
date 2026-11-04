from io import BytesIO
from types import SimpleNamespace
from datetime import date, datetime

from django.test import SimpleTestCase
from openpyxl import load_workbook

from integrations.services.expense_reporting import expense_report_title, sorted_expense_details
from integrations.services.payment_excel import export_payment_excel_bytes
from integrations.services.payment_summary import payment_context
from integrations.services.payment_message import build_payment_report_message
from integrations.services.payment_a2ui import build_payment_a2ui_messages


class ExpenseReportPresentationTests(SimpleTestCase):
    def data(self):
        base = {
            "amount": 10,
            "reason": "reason",
            "expected_date": "",
            "status": "COMPLETED",
            "originator": "test",
            "title": "test",
        }
        return {
            "report_type": "month",
            "summary": {
                "total_count": 3,
                "total_amount": 30,
                "by_status": {"COMPLETED": 3, "RUNNING": 0, "TERMINATED": 0, "NEW": 0},
            },
            "by_recipient": [
                {
                    "recipient": "older",
                    "amount": 20,
                    "count": 2,
                    "details": [
                        dict(base, create_date="2026-10-01", process_instance_id="1"),
                        dict(base, create_date="2026-10-15", process_instance_id="2"),
                    ],
                },
                {
                    "recipient": "newer",
                    "amount": 10,
                    "count": 1,
                    "details": [dict(base, create_date="2026-10-31", process_instance_id="3")],
                },
            ],
        }

    def period(self):
        return {"label": "2026年10月", "start_date": date(2026, 10, 1), "end_date": date(2026, 10, 31)}

    def test_names_and_day_compatibility(self):
        self.assertEqual(expense_report_title("week"), "周度支出报表")
        self.assertEqual(expense_report_title("month"), "月度支出报表")
        self.assertEqual(expense_report_title("day"), "付款申请日报")

    def test_flat_details_are_date_descending_across_payees_without_mutation(self):
        data = self.data()
        details = sorted_expense_details(data)
        self.assertEqual([row["create_date"] for row in details], ["2026-10-31", "2026-10-15", "2026-10-01"])
        self.assertEqual(data["by_recipient"][0]["details"][0]["create_date"], "2026-10-01")

    def test_excel_details_date_descending_and_title(self):
        book = load_workbook(BytesIO(export_payment_excel_bytes(self.data(), self.period())))
        self.assertEqual(
            [row[0] for row in list(book["详细清单"].values)[1:]], ["2026-10-31", "2026-10-15", "2026-10-01"]
        )
        self.assertIn("月度支出报表", str(list(book["汇总统计"].values)))

    def test_frozen_source_amount_strings_render_as_decimal(self):
        data = self.data()
        data['sources'] = [{'name':'付款申请','amount':'30.00','count':3}]
        snapshot = SimpleNamespace(data=data, company=SimpleNamespace(name='Test'), period_label='2026年10月',
            period_start=date(2026,10,1), period_end=date(2026,10,31), report_type='month')
        context = payment_context(snapshot)
        self.assertEqual(context['source_rows'][0]['percent'],100.0)

    def test_context_and_push_use_expenditure_name_and_coverage(self):
        snapshot = SimpleNamespace(
            data=self.data(),
            company=SimpleNamespace(name="Test"),
            period_label="2026年10月",
            period_start=date(2026, 10, 1),
            period_end=date(2026, 10, 31),
            report_type="month",
            get_report_type_display=lambda: "月报",
        )
        context = payment_context(snapshot)
        self.assertEqual(context["report_title"], "月度支出报表")
        self.assertEqual([row["create_date"] for row in context["details"]], ["2026-10-31", "2026-10-15", "2026-10-01"])
        self.assertIn("当前覆盖：付款申请", context["scope_note"])
        text = build_payment_report_message(self.data(), self.period(), "month")
        self.assertIn("月度支出报表", text)
        period = {**self.period(), "start": datetime(2026, 10, 1), "end": datetime(2026, 10, 31)}
        model = build_payment_a2ui_messages(self.data(), period, "Test", "week")[1]["updateDataModel"]["value"]
        self.assertEqual(model["reportTitle"], "周度支出报表")
