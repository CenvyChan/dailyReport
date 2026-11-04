from decimal import Decimal
from types import SimpleNamespace

from django.test import SimpleTestCase, TestCase

from core.testing import company_a, company_b
from integrations.models import DingtalkApp, DingtalkApprovalInstance, DingtalkCompanyMapping, DingtalkProcessConfig
from integrations.services.expense_fields import normalize_expense_form
from integrations.services.payment_organizations import save_approval


def reimbursement_form(amounts=("10", "20"), total="30", company="Company B"):
    rows = [
        {
            "rowNumber": str(i),
            "rowValue": [
                {"key": "amount-id", "value": amount},
                {"key": "reason-id", "value": "expense"},
                {"key": "file-id", "value": [{"url": "private"}]},
            ],
        }
        for i, amount in enumerate(amounts)
    ]
    table = {
        "componentType": "TableField",
        "props": {"label": "报销明细"},
        "children": [
            {"props": {"id": "amount-id", "label": "报销金额（元）"}},
            {"props": {"id": "reason-id", "label": "费用说明"}},
            {"props": {"id": "date-id", "label": "费用发生日期"}},
        ],
        "value": rows,
        "extValue": {"statValue": [{"id": "amount-id", "num": total}]},
    }
    return [
        {"name": "申请公司", "value": company},
        {
            "component_type": "DDBizSuite",
            "value": [table, {"props": {"label": "入账时间"}, "value": "2026-10-15 12:00"}],
        },
    ]


class ExpenseFieldTests(SimpleTestCase):
    def test_salary_amount_and_missing_company(self):
        process = SimpleNamespace(name="员工薪资发放申请A", amount_component="付款总额")
        data = normalize_expense_form(process, {"申请公司": "A", "付款总额": "1,200.50"})
        self.assertEqual(data["__expense"]["amount"], "1200.50")
        with self.assertRaisesRegex(ValueError, "申请公司"):
            normalize_expense_form(process, {"付款总额": 100})
        with self.assertRaisesRegex(ValueError, "金额"):
            normalize_expense_form(process, {"申请公司": "A", "付款总额": "bad"})

    def test_unnamed_reimbursement_suite_and_total(self):
        process = SimpleNamespace(name="日常报销单据", amount_component="报销金额（元）")
        data = normalize_expense_form(process, reimbursement_form())
        expense = data["__expense"]
        self.assertEqual(expense["amount"], "30")
        self.assertEqual([row["amount"] for row in expense["lines"]], ["10", "20"])
        self.assertEqual(expense["posting_time"], "2026-10-15 12:00")
        self.assertEqual(expense["lines"][0]["expense_date"], "")
        self.assertNotIn("private", str(expense))

    def test_reimbursement_mismatch_and_schema_change_fail(self):
        process = SimpleNamespace(name="日常报销单据", amount_component="报销金额（元）")
        with self.assertRaisesRegex(ValueError, "合计"):
            normalize_expense_form(process, reimbursement_form(total="31"))
        with self.assertRaises(ValueError):
            normalize_expense_form(process, reimbursement_form(amounts=("NaN",), total="NaN"))
        with self.assertRaisesRegex(ValueError, "明细表"):
            normalize_expense_form(process, [{"name": "申请公司", "value": "B"}])


class ExpenseStorageBoundaryTests(TestCase):
    def setUp(self):
        self.a, self.b = company_a(), company_b()
        self.app = DingtalkApp.objects.create(company=self.a, name="app", app_key="test", app_secret="test")
        DingtalkCompanyMapping.objects.create(app=self.app, application_company="Company B", company=self.b)
        self.process = DingtalkProcessConfig.objects.create(
            app=self.app, name="日常报销单据", process_code="reimburse-test", amount_component="报销金额（元）"
        )

    def test_application_company_not_app_company_and_idempotent(self):
        raw = {"form_component_values": reimbursement_form(), "create_time": "2026-10-15 12:00:00", "status": "RUNNING"}
        save_approval(self.app, self.process, raw, "actual-instance-id")
        save_approval(self.app, self.process, raw, "actual-instance-id")
        row = DingtalkApprovalInstance.objects.get()
        self.assertEqual(row.company, self.b)
        self.assertEqual(row.amount, Decimal(30))
        self.assertEqual(len(row.form_values["__expense"]["lines"]), 2)

    def test_unmapped_company_or_mismatch_does_not_write(self):
        with self.assertRaisesRegex(ValueError, "映射"):
            save_approval(self.app, self.process, {"form_component_values": reimbursement_form(company="Unknown")}, "x")
        with self.assertRaisesRegex(ValueError, "合计"):
            save_approval(self.app, self.process, {"form_component_values": reimbursement_form(total="900")}, "y")
        self.assertEqual(DingtalkApprovalInstance.objects.count(), 0)
