"""漏发补投的边界测试。

补发的正确性全压在「范围严格早于本轮目标日期」这一条上：若把目标日期本身
也纳入补发范围，补发会无视 send_at 把当天的日报提前发出去，等于废掉定时窗口。
"""

from datetime import date, datetime, time
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.testing import company_a
from integrations.models import (
    DingtalkApp,
    DingtalkGroupConfig,
    ReportDelivery,
    ReportSnapshot,
)
from integrations.services.report_delivery import (
    backfill_missed_deliveries,
    send_manual_report,
)

BASELINE = timezone.make_aware(datetime(2026, 1, 1, 0, 0))


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
            content_types=["SALES", "PURCHASE"],
            # 故意设成深夜，确保被补发的快照不是靠「窗口已到」才发出去的
            send_at=time(23, 59),
        )
        # 模拟配置早已存在；enabled_at 默认是创建时刻，会把历史快照全部挡掉。
        DingtalkGroupConfig.objects.update(enabled_at=BASELINE)
        self.target_date = date(2026, 10, 8)

    def _snapshot(self, report_date):
        return ReportSnapshot.objects.create(
            company=self.company,
            report_date=report_date,
            scope="BOTH",
            data={"sales": {}, "purchase": {}},
        )

    def _run(self, days=3):
        with patch(
            "integrations.services.dingtalk_client.build_client",
            side_effect=lambda app: FakeClient(app),
        ), patch(
            "integrations.services.operations_delivery.deliver_operations_report",
            return_value=None,
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


class ScheduledResendTests(TestCase):
    """手动提前发过的日报，到定时窗口仍须按时再发一次，且只补这一次。"""

    def setUp(self):
        self.company = company_a()
        app = DingtalkApp.objects.create(company=self.company, app_key="k", app_secret="s")
        self.group = DingtalkGroupConfig.objects.create(
            company=self.company, app=app, name="经营群", open_conversation_id="cid-test",
            content_types=["SALES", "PURCHASE"], send_at=time(0, 0),
        )
        DingtalkGroupConfig.objects.update(enabled_at=BASELINE)
        self.snapshot = ReportSnapshot.objects.create(
            company=self.company, report_date=date(2026, 10, 27), scope="BOTH",
            data={"sales": {}, "purchase": {}},
        )

    def _sent_at(self, sent_at):
        from django.utils import timezone
        from datetime import datetime
        return ReportDelivery.objects.create(
            snapshot=self.snapshot, channel=ReportDelivery.Channel.DINGTALK,
            target_identifier=str(self.group.id), status=ReportDelivery.Status.SENT,
            attempt_count=1, sent_at=timezone.make_aware(datetime(*sent_at)),
        )

    def _send(self, send_now=False):
        from integrations.services.report_delivery import send_report_to_all_channels
        with patch("integrations.services.dingtalk_client.build_client",
                   side_effect=lambda app: FakeClient(app)), \
             patch("integrations.services.operations_delivery.deliver_operations_report",
                   return_value=None) as deliver:
            results = send_report_to_all_channels(self.snapshot, send_now=send_now)
        return results, deliver

    def test_manual_send_before_window_is_resent_by_schedule(self):
        delivery = self._sent_at((2026, 10, 27, 23, 30))  # 早于 10-28 00:00 窗口

        results, deliver = self._send()

        self.assertEqual(deliver.call_count, 1)
        self.assertIn(("钉钉", "SENT", "经营群"), results)
        delivery.refresh_from_db()
        self.assertEqual(delivery.status, ReportDelivery.Status.SENT)
        self.assertGreater(delivery.sent_at.year, 2026 - 1)

        # 定时发出后 sent_at 已在窗口之后，下一轮不得再发
        _, deliver_again = self._send()
        self.assertEqual(deliver_again.call_count, 0)

    def test_scheduled_send_is_not_repeated(self):
        self._sent_at((2026, 10, 28, 0, 5))  # 窗口之后发的，即定时发送

        results, deliver = self._send()

        self.assertEqual(deliver.call_count, 0)
        self.assertIn(("钉钉", "SKIPPED", "经营群 已发送"), results)

    def test_manual_now_does_not_trigger_resend(self):
        self._sent_at((2026, 10, 27, 23, 30))

        _, deliver = self._send(send_now=True)

        self.assertEqual(deliver.call_count, 0)


class EnabledBaselineTests(TestCase):
    """新建或重新启用的群只从启用时刻之后的定时窗口开始推送。"""

    def setUp(self):
        self.company = company_a()
        app = DingtalkApp.objects.create(company=self.company, app_key="k", app_secret="s")
        self.group = DingtalkGroupConfig.objects.create(
            company=self.company, app=app, name="新群", open_conversation_id="cid-new",
            content_types=["SALES", "PURCHASE"], send_at=time(0, 0),
        )
        self.snapshot = ReportSnapshot.objects.create(
            company=self.company, report_date=date(2026, 10, 6), scope="BOTH",
            data={"sales": {}, "purchase": {}},
        )

    def _patched(self):
        return patch(
            "integrations.services.dingtalk_client.build_client",
            side_effect=lambda app: FakeClient(app),
        ), patch(
            "integrations.services.operations_delivery.deliver_operations_report",
            return_value=None,
        )

    def test_backfill_does_not_pour_history_into_new_group(self):
        """新建群没有已发送基线，补投不能把启用前的快照灌进去。"""
        client_patch, deliver_patch = self._patched()
        with client_patch, deliver_patch as deliver:
            result = backfill_missed_deliveries(
                company=self.company,
                before_date=date(2026, 10, 8),
                days=3,
            )

        self.assertEqual(result, [])
        self.assertEqual(deliver.call_count, 0)
        self.assertFalse(ReportDelivery.objects.filter(snapshot=self.snapshot).exists())

    def test_schedule_skips_window_before_enable(self):
        """今天已过的发送时间不应该在重新启用后立刻补发。"""
        from integrations.services.report_delivery import send_report_to_all_channels

        client_patch, deliver_patch = self._patched()
        with client_patch, deliver_patch as deliver:
            results = send_report_to_all_channels(self.snapshot, send_now=False)

        self.assertEqual(results, [])
        self.assertEqual(deliver.call_count, 0)


class ManualPushTests(TestCase):
    """人为手动推送只影响选中的群配置。"""

    def setUp(self):
        self.company = company_a()
        app = DingtalkApp.objects.create(company=self.company, app_key="k", app_secret="s")
        self.group_a = DingtalkGroupConfig.objects.create(
            company=self.company, app=app, name="测试群", open_conversation_id="cid-a",
            content_types=["SALES", "PURCHASE"], send_at=time(23, 59),
        )
        self.group_b = DingtalkGroupConfig.objects.create(
            company=self.company, app=app, name="正式群", open_conversation_id="cid-b",
            content_types=["SALES", "PURCHASE"], send_at=time(23, 59),
        )
        self.snapshot = ReportSnapshot.objects.create(
            company=self.company, report_date=date(2026, 10, 26), scope="BOTH",
            data={"sales": {}, "purchase": {}},
        )
        ReportDelivery.objects.create(
            snapshot=self.snapshot,
            channel=ReportDelivery.Channel.DINGTALK,
            target_identifier=str(self.group_a.id),
            target_display=self.group_a.name,
            status=ReportDelivery.Status.SENT,
            attempt_count=1,
        )

    def test_manual_push_resends_only_selected_group(self):
        with patch(
            "integrations.services.dingtalk_client.build_client",
            side_effect=lambda app: FakeClient(app),
        ), patch(
            "integrations.services.operations_delivery.deliver_operations_report",
            return_value=None,
        ) as deliver:
            results = send_manual_report(self.snapshot, [self.group_a])

        self.assertEqual(deliver.call_count, 1)
        self.assertEqual(results, [("钉钉", "SENT", "测试群")])
        delivery = ReportDelivery.objects.get(snapshot=self.snapshot, target_identifier=str(self.group_a.id))
        self.assertEqual(delivery.status, ReportDelivery.Status.SENT)
        self.assertEqual(delivery.attempt_count, 1)
        self.assertFalse(
            ReportDelivery.objects.filter(
                snapshot=self.snapshot, target_identifier=str(self.group_b.id)
            ).exists()
        )


class ManualPushAdminTests(TestCase):
    """后台手动推送页：能打开，且只发送勾选的群配置。"""

    def setUp(self):
        user_model = get_user_model()
        self.admin_user = user_model.objects.create_superuser(
            username="push-admin", email="push@example.com", password="pw-test-123"
        )
        self.client.force_login(self.admin_user)
        self.company = company_a()
        app = DingtalkApp.objects.create(company=self.company, app_key="k", app_secret="s")
        self.group = DingtalkGroupConfig.objects.create(
            company=self.company, app=app, name="测试群", open_conversation_id="cid-test",
            content_types=["SALES", "PURCHASE"], send_at=time(18),
        )
        self.group.companies.set([self.company])
        self.snapshot = ReportSnapshot.objects.create(
            company=self.company, report_date=date(2026, 10, 26), scope="BOTH",
            data={"sales": {}, "purchase": {}},
        )

    def test_manual_push_page_renders(self):
        response = self.client.get(
            reverse("admin:integrations_dingtalkgroupconfig_manual_push")
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "手动推送会")

    def test_post_only_targets_selected_group(self):
        with patch(
            "integrations.services.dingtalk_client.build_client",
            side_effect=lambda app: FakeClient(app),
        ), patch(
            "integrations.services.operations_delivery.deliver_operations_report",
            return_value=None,
        ) as deliver:
            response = self.client.post(
                reverse("admin:integrations_dingtalkgroupconfig_manual_push"),
                {
                    "report_date": "2026-10-26",
                    "group_configs": [self.group.id],
                    "companies": [self.company.id],
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(deliver.call_count, 1)
        self.assertContains(response, "SENT")
