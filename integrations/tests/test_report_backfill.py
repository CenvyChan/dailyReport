"""漏发补投的边界测试。

补发的正确性全压在「范围严格早于本轮目标日期」这一条上：若把目标日期本身
也纳入补发范围，补发会无视 send_at 把当天的日报提前发出去，等于废掉定时窗口。
"""

from datetime import date, time
from unittest.mock import patch

from django.test import TestCase

from core.testing import company_a
from integrations.models import (
    DingtalkApp,
    DingtalkGroupConfig,
    ReportDelivery,
    ReportSnapshot,
)
from integrations.services.report_delivery import backfill_missed_deliveries


class FakeClient:
    def __init__(self, app):
        self.app = app
        self.posts = []

    def post(self, path, payload):
        self.posts.append((path, payload))
        return {"errcode": 0}

    def upload_media(self, name, content):
        return "MEDIA-1"


class BackfillTests(TestCase):
    def setUp(self):
        self.company = company_a()
        self.app = DingtalkApp.objects.create(company=self.company, app_key="k", app_secret="s")
        DingtalkGroupConfig.objects.create(
            company=self.company,
            app=self.app,
            name="经营群",
            open_conversation_id="cid-test",
            scope=DingtalkGroupConfig.Scope.BOTH,
            # 故意设成深夜，确保被补发的快照不是靠「窗口已到」才发出去的
            send_at=time(23, 59),
        )
        self.target_date = date(2026, 10, 8)

    def _snapshot(self, report_date):
        return ReportSnapshot.objects.create(
            company=self.company,
            report_date=report_date,
            scope="BOTH",
            data={},
        )

    def _run(self, days=3):
        with patch(
            "integrations.services.dingtalk_client.build_client",
            side_effect=lambda app: FakeClient(app),
        ), patch(
            "integrations.services.report_delivery.render_snapshot_pdf",
            return_value=b"%PDF-fake",
        ):
            return backfill_missed_deliveries(
                company=self.company,
                before_date=self.target_date,
                days=days,
            )

    def test_backfills_missed_snapshot(self):
        missed = self._snapshot(date(2026, 10, 6))

        result = self._run()

        self.assertEqual([snap.id for snap, _ in result], [missed.id])
        self.assertTrue(
            ReportDelivery.objects.filter(
                snapshot=missed, status=ReportDelivery.Status.SENT
            ).exists()
        )

    def test_target_date_is_never_backfilled(self):
        """目标日期本身不在补发范围内，否则会绕过 send_at 提前发。"""
        today_target = self._snapshot(self.target_date)

        result = self._run()

        self.assertEqual(result, [])
        self.assertFalse(ReportDelivery.objects.filter(snapshot=today_target).exists())

    def test_already_sent_is_not_resent(self):
        sent = self._snapshot(date(2026, 10, 6))
        ReportDelivery.objects.create(
            snapshot=sent,
            channel=ReportDelivery.Channel.DINGTALK,
            target_identifier=str(DingtalkGroupConfig.objects.get().id),
            status=ReportDelivery.Status.SENT,
            attempt_count=1,
        )

        result = self._run()

        self.assertEqual(result, [])
        self.assertEqual(
            ReportDelivery.objects.filter(snapshot=sent).get().attempt_count, 1
        )

    def test_out_of_window_snapshot_is_ignored(self):
        """超出回溯天数的旧快照不再补发，避免翻旧账刷屏。"""
        self._snapshot(date(2026, 10, 1))

        result = self._run(days=3)

        self.assertEqual(result, [])
