"""付款申请在线快照：生成、公开链接、下载与页面口径。"""

from datetime import date
from decimal import Decimal
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from core.models import Company
from integrations.models import PaymentReportSnapshot
from integrations.services.payment_snapshot import (
    build_payment_snapshot_data,
    generate_payment_snapshot,
    payment_snapshot_url,
)
from integrations.services.payment_summary import payment_context

PERIOD = {
    "start_date": date(2026, 10, 19),
    "end_date": date(2026, 10, 25),
    "label": "2026年第43周",
}


def report_data():
    return {
        "summary": {
            "total_count": 4,
            "total_amount": Decimal("375.00"),
            "by_status": {"COMPLETED": 1, "RUNNING": 1, "TERMINATED": 1, "NEW": 1},
        },
        "by_recipient": [
            {
                "recipient": "收款人甲",
                "count": 2,
                "amount": Decimal("300"),
                "details": [
                    {
                        "create_date": "2026-10-19",
                        "amount": Decimal("100"),
                        "status": "COMPLETED",
                        "reason": "采购款",
                        "expected_date": "2026-10-20",
                        "originator": "张三",
                        "title": "付款申请-甲",
                        "process_instance_id": "pi-001",
                    },
                    {
                        "create_date": "2026-10-21",
                        "amount": Decimal("200"),
                        "status": "RUNNING",
                        "reason": "服务费",
                        "expected_date": "2026-10-22",
                        "originator": "李四",
                        "title": "付款申请-甲",
                        "process_instance_id": "pi-002",
                    },
                ],
            },
            {
                "recipient": "收款人乙",
                "count": 1,
                "amount": Decimal("50"),
                "details": [
                    {
                        "create_date": "2026-10-25",
                        "amount": Decimal("50"),
                        "status": "TERMINATED",
                        "reason": "设备款",
                        "expected_date": "",
                        "originator": "王五",
                        "title": "付款申请-乙",
                        "process_instance_id": "pi-003",
                    }
                ],
            },
            {
                "recipient": "收款人丙",
                "count": 1,
                "amount": Decimal("25"),
                "details": [
                    {
                        "create_date": "2026-10-25",
                        "amount": Decimal("25"),
                        "status": "NEW",
                        "reason": "杂费",
                        "expected_date": "",
                        "originator": "赵六",
                        "title": "付款申请-丙",
                        "process_instance_id": "pi-004",
                    }
                ],
            },
        ],
    }


def make_snapshot(company, data=None, report_type="week"):
    snapshot = PaymentReportSnapshot(
        company=company,
        report_type=report_type,
        period_start=PERIOD["start_date"],
        period_end=PERIOD["end_date"],
        process_code="PAYMENT_PROCESS",
        period_label=PERIOD["label"],
        data=build_payment_snapshot_data(data or report_data(), report_type, PERIOD, "测试公司"),
    )
    return snapshot


class PaymentSnapshotGenerationTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(code="FNS", name="慈溪飞诺斯电子科技有限公司")

    def test_snapshot_is_reused_and_decimals_are_frozen_as_strings(self):
        first = generate_payment_snapshot(
            self.company, "week", PERIOD, "PAYMENT_PROCESS", "测试公司", data=report_data()
        )
        second = generate_payment_snapshot(
            self.company, "week", PERIOD, "PAYMENT_PROCESS", "测试公司", data=report_data()
        )
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(PaymentReportSnapshot.objects.count(), 1)
        self.assertEqual(first.data["summary"]["total_amount"], "375.00")
        self.assertEqual(
            first.data["by_recipient"][0]["details"][0]["amount"], "100"
        )

    def test_force_rebuilds_same_row_and_refreshes_generated_at(self):
        first = generate_payment_snapshot(
            self.company, "week", PERIOD, "PAYMENT_PROCESS", "测试公司", data=report_data()
        )
        old_generated_at = first.generated_at
        updated = report_data()
        updated["summary"]["total_amount"] = Decimal("400.00")
        updated["by_recipient"][2]["amount"] = Decimal("50")
        updated["by_recipient"][2]["details"][0]["amount"] = Decimal("50")
        rebuilt = generate_payment_snapshot(
            self.company,
            "week",
            PERIOD,
            "PAYMENT_PROCESS",
            "测试公司",
            data=updated,
            force=True,
        )
        self.assertEqual(rebuilt.pk, first.pk)
        self.assertEqual(PaymentReportSnapshot.objects.count(), 1)
        self.assertGreater(rebuilt.generated_at, old_generated_at)
        self.assertEqual(rebuilt.data["summary"]["total_amount"], "400.00")

    def test_different_process_code_gets_its_own_snapshot(self):
        generate_payment_snapshot(
            self.company, "week", PERIOD, "PAYMENT_PROCESS", "测试公司", data=report_data()
        )
        generate_payment_snapshot(
            self.company, "week", PERIOD, "OTHER_PROCESS", "测试公司", data=report_data()
        )
        self.assertEqual(PaymentReportSnapshot.objects.count(), 2)

    def test_public_link_carries_snapshot_token(self):
        snapshot = generate_payment_snapshot(
            self.company, "week", PERIOD, "PAYMENT_PROCESS", "测试公司", data=report_data()
        )
        url = payment_snapshot_url(snapshot)
        parsed = urlparse(url)
        self.assertIn(f"/integrations/payment-snapshots/{snapshot.pk}/public/", parsed.path)
        self.assertTrue(parse_qs(parsed.query)["token"][0])


class PaymentSummaryContextTests(SimpleTestCase):
    def setUp(self):
        self.company = Company(code="FNS", name="测试公司")

    def test_metrics_match_card_formulas(self):
        context = payment_context(make_snapshot(self.company))
        metrics = {metric["label"]: metric["value"] for metric in context["metrics"]}
        self.assertEqual(metrics["申请总额"], "¥375.00")
        self.assertEqual(metrics["审批中金额"], "¥200.00")
        self.assertEqual(metrics["已完成金额"], "¥100.00")
        self.assertEqual(metrics["已终止金额"], "¥50.00")
        self.assertEqual(metrics["收款人数量"], "3 家")
        self.assertEqual(metrics["平均单笔"], "¥93.75")
        self.assertEqual(context["warning"], "")
        self.assertEqual(context["report_title"], "付款申请周报")

    def test_daily_chart_covers_every_day_of_period(self):
        context = payment_context(make_snapshot(self.company))
        points = context["daily_chart"]["series"][0]["points_list"]
        self.assertEqual(len(points), 7)
        self.assertEqual(points[0]["date"], "2026-10-19")
        self.assertEqual(points[-1]["date"], "2026-10-25")
        self.assertAlmostEqual(sum(point["value"] for point in points), 0.0375)

    def test_total_mismatch_surfaces_warning_instead_of_failing(self):
        data = report_data()
        data["summary"]["total_amount"] = Decimal("999.00")
        context = payment_context(make_snapshot(self.company, data=data))
        self.assertIn("汇总与明细不一致", context["warning"])

    def test_unknown_status_is_listed(self):
        data = report_data()
        data["by_recipient"][2]["details"][0]["status"] = "OTHER"
        rows = {
            row["status"]: row
            for row in payment_context(make_snapshot(self.company, data=data))["status_rows"]
        }
        self.assertEqual(rows["OTHER"]["label"], "其他（OTHER）")
        self.assertEqual(rows["OTHER"]["count"], 1)
        self.assertEqual(rows["OTHER"]["amount_text"], "¥25.00")

    def test_status_rows_replace_new_with_total(self):
        # 现实数据里 NEW 恒为 0：把夹具里的 NEW 明细改成 RUNNING 以模拟真实情况。
        data = report_data()
        data["by_recipient"][2]["details"][0]["status"] = "RUNNING"
        rows = payment_context(make_snapshot(self.company, data=data))["status_rows"]
        statuses = [row["status"] for row in rows]
        self.assertNotIn("NEW", statuses)
        total = rows[-1]
        self.assertTrue(total["is_total"])
        self.assertEqual(total["label"], "发起的流程数")
        self.assertEqual(total["count"], 4)
        self.assertEqual(total["amount_text"], "¥375.00")
        self.assertEqual(total["percent"], 100.0)

    def test_new_status_still_shown_when_it_actually_occurs(self):
        data = report_data()
        data["by_recipient"][2]["details"][0]["status"] = "NEW"
        rows = payment_context(make_snapshot(self.company, data=data))["status_rows"]
        statuses = [row["status"] for row in rows]
        self.assertIn("NEW", statuses)
        self.assertEqual(rows[-1]["label"], "发起的流程数")

    def test_payee_top_five_plus_other_preserves_total(self):
        data = report_data()
        for index in range(4):
            data["by_recipient"].append(
                {
                    "recipient": f"其他收款人{index}",
                    "count": 1,
                    "amount": Decimal("10"),
                    "details": [
                        {
                            "create_date": "2026-10-20",
                            "amount": Decimal("10"),
                            "status": "RUNNING",
                        }
                    ],
                }
            )
        data["summary"] = {"total_count": 8, "total_amount": Decimal("415")}
        context = payment_context(make_snapshot(self.company, data=data))
        self.assertEqual(len(context["payee_rows"]), 6)
        self.assertEqual(context["payee_rows"][-1]["name"], "其他 2 家")
        self.assertEqual(context["payee_rows"][-1]["count"], 2)
        self.assertAlmostEqual(
            sum(row["amount_wan"] for row in context["payee_rows"]), 0.0415
        )

    def test_detail_rows_sorted_newest_first(self):
        context = payment_context(make_snapshot(self.company))
        dates = [
            detail["create_date"] for detail in context["detail_groups"][0]["details"]
        ]
        self.assertEqual(dates, ["2026-10-21", "2026-10-19"])

    def test_empty_period_renders_without_fake_values(self):
        data = {
            "summary": {
                "total_count": 0,
                "total_amount": Decimal("0"),
                "by_status": {"COMPLETED": 0, "RUNNING": 0, "TERMINATED": 0, "NEW": 0},
            },
            "by_recipient": [],
        }
        context = payment_context(make_snapshot(self.company, data=data))
        metrics = {metric["label"]: metric["value"] for metric in context["metrics"]}
        self.assertEqual(metrics["申请总额"], "¥0.00")
        self.assertEqual(metrics["平均单笔"], "—")
        self.assertFalse(context["daily_chart"]["has_data"])
        self.assertEqual(context["payee_rows"], [])
        self.assertEqual(context["focus_items"], [])
        self.assertEqual(context["detail_groups"], [])


class PaymentSnapshotPublicViewTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(code="FNS", name="慈溪飞诺斯电子科技有限公司")
        self.snapshot = make_snapshot(self.company)
        self.snapshot.save()
        other = make_snapshot(self.company)
        other.period_start = date(2026, 10, 12)
        other.period_end = date(2026, 10, 18)
        other.period_label = "2026年第42周"
        other.save()
        self.other = other

    def _token(self, snapshot):
        return parse_qs(urlparse(payment_snapshot_url(snapshot)).query)["token"][0]

    def test_valid_link_renders_without_login(self):
        response = self.client.get(
            reverse("integrations:payment_snapshot_public", args=[self.snapshot.pk]),
            {"token": self._token(self.snapshot)},
        )
        self.assertEqual(response.status_code, 200)
        body = response.content.decode("utf-8")
        self.assertIn("付款申请周报", body)
        self.assertIn("申请明细", body)
        self.assertIn('name="viewport"', body)
        self.assertEqual(response["X-Robots-Tag"], "noindex, nofollow")

    def test_public_page_uses_left_nav_layout(self):
        response = self.client.get(
            reverse("integrations:payment_snapshot_public", args=[self.snapshot.pk]),
            {"token": self._token(self.snapshot)},
        )
        body = response.content.decode("utf-8")
        self.assertIn('class="report-layout"', body)
        self.assertIn('class="report-toc"', body)
        for anchor in ("overview", "status", "trend", "ranking", "details"):
            self.assertIn(f'id="{anchor}"', body)
            self.assertIn(f'href="#{anchor}"', body)

    def test_monthly_report_uses_the_same_layout(self):
        month = make_snapshot(self.company, report_type="month")
        month.period_start = date(2026, 9, 1)
        month.period_end = date(2026, 9, 30)
        month.period_label = "2026年9月"
        month.save()
        response = self.client.get(
            reverse("integrations:payment_snapshot_public", args=[month.pk]),
            {"token": self._token(month)},
        )
        self.assertEqual(response.status_code, 200)
        body = response.content.decode("utf-8")
        self.assertIn("付款申请月报", body)
        self.assertIn('class="report-toc"', body)

    def test_bad_or_mismatched_token_is_forbidden(self):
        url = reverse("integrations:payment_snapshot_public", args=[self.snapshot.pk])
        self.assertEqual(self.client.get(url, {"token": "bad"}).status_code, 403)
        self.assertEqual(
            self.client.get(url, {"token": self._token(self.other)}).status_code, 403
        )

    def test_public_page_offers_pdf_and_excel_download_links(self):
        response = self.client.get(
            reverse("integrations:payment_snapshot_public", args=[self.snapshot.pk]),
            {"token": self._token(self.snapshot)},
        )
        body = response.content.decode("utf-8")
        self.assertIn("下载 PDF", body)
        self.assertIn("下载 Excel", body)
        self.assertIn("download=pdf", body)
        self.assertIn("download=excel", body)

    def test_public_downloads_require_the_same_token(self):
        url = reverse("integrations:payment_snapshot_public", args=[self.snapshot.pk])
        token = self._token(self.snapshot)
        excel = self.client.get(url, {"token": token, "download": "excel"})
        self.assertEqual(excel.status_code, 200)
        self.assertIn("spreadsheetml", excel["Content-Type"])
        self.assertTrue(excel.content.startswith(b"PK"))
        with patch(
            "integrations.views_payment_snapshot._pdf_bytes", return_value=b"%PDF-test"
        ):
            pdf = self.client.get(url, {"token": token, "download": "pdf"})
        self.assertEqual(pdf.status_code, 200)
        self.assertEqual(pdf["Content-Type"], "application/pdf")
        self.assertEqual(pdf.content, b"%PDF-test")
        self.assertEqual(
            self.client.get(url, {"token": "bad", "download": "excel"}).status_code,
            403,
        )

    def test_internal_view_requires_login(self):
        response = self.client.get(
            reverse("integrations:payment_snapshot_view", args=[self.snapshot.pk])
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login", response["Location"])
