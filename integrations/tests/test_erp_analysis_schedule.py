"""分析开始和定时发送必须是两个独立时间点。"""

from datetime import date, datetime, time
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.core.exceptions import ValidationError
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase, TransactionTestCase, override_settings

from core.testing import company_a
from integrations.admin import ErpAnalysisScheduleForm
from integrations.models import (
    DingtalkApp,
    DingtalkGroupConfig,
    ErpAnalysisSchedule,
    ErpAnalysisTask,
    KingdeeAccount,
    KingdeeOrgBinding,
)
from integrations.services.erp_analysis.runner import enqueue, enqueue_due, notify, process_task

SHANGHAI = ZoneInfo("Asia/Shanghai")


@override_settings(PUBLIC_BASE_URL="https://reports.example.invalid")
class AnalysisScheduleTimingTests(TestCase):
    def setUp(self):
        self.company = company_a()
        self.account = KingdeeAccount.objects.create(
            name="Timing Test",
            server_url="https://example.invalid/k3cloud",
            acct_id="test",
            username="test",
            app_id="test",
            app_secret="test",
        )
        KingdeeOrgBinding.objects.create(company=self.company, account=self.account, org_number="001")
        app = DingtalkApp.objects.create(company=self.company, app_key="test", app_secret="test", robot_code="test")
        self.group = DingtalkGroupConfig.objects.create(
            company=self.company, app=app, name="Timing Test", open_conversation_id="test", send_at=time(8)
        )
        self.schedule = ErpAnalysisSchedule.objects.create(
            company=self.company,
            enabled=True,
            day=1,
            start_time=time(7, 30),
            send_day=1,
            send_time=time(8, 45),
            report_kinds=["purchase"],
            notification_group=self.group,
        )

    def at(self, day, hour, minute=0):
        return datetime(2026, 6, day, hour, minute, tzinfo=SHANGHAI)

    def completed_task(self):
        task = enqueue_due(self.at(1, 7, 30))[0]
        task.status = "SUCCESS"
        task.results = {"purchase": {"status": "SUCCESS"}}
        task.save()
        return task

    def test_enqueue_starts_at_analysis_time_not_send_time(self):
        self.assertEqual(enqueue_due(self.at(1, 7, 29)), [])
        task = enqueue_due(self.at(1, 7, 30))[0]
        self.assertEqual(task.period, date(2026, 5, 1))
        self.assertEqual(task.notification_scheduled_at, self.at(1, 8, 45))
        self.assertEqual(enqueue_due(self.at(1, 8, 45))[0].pk, task.pk)
        self.assertEqual(ErpAnalysisTask.objects.count(), 1)

    def test_ready_report_waits_until_send_time(self):
        task = self.completed_task()
        with patch("integrations.services.erp_analysis.runner.DingtalkClient") as client:
            notify(task.pk, now=self.at(1, 8, 44))
            self.assertFalse(client.called)
        task.refresh_from_db()
        self.assertEqual(task.notification_status, "PENDING")
        with patch("integrations.services.erp_analysis.runner.DingtalkClient") as client:
            notify(task.pk, now=self.at(1, 8, 45))
            self.assertEqual(client.return_value.post.call_count, 1)
        task.refresh_from_db()
        self.assertEqual(task.notification_status, "SENT")

    def test_report_running_at_send_time_is_not_sent(self):
        task = enqueue_due(self.at(1, 7, 30))[0]
        task.status = "RUNNING"
        task.save()
        with patch("integrations.services.erp_analysis.runner.DingtalkClient") as client:
            notify(task.pk, now=self.at(1, 8, 45))
            self.assertFalse(client.called)
        task.status = "SUCCESS"
        task.results = {"purchase": {"status": "SUCCESS"}}
        task.save()
        with patch("integrations.services.erp_analysis.runner.DingtalkClient") as client:
            notify(task.pk, now=self.at(1, 9))
            self.assertEqual(client.return_value.post.call_count, 1)

    def test_send_can_be_on_later_day(self):
        self.schedule.send_day = 2
        self.schedule.send_time = time(8)
        self.schedule.save()
        task = enqueue_due(self.at(1, 7, 30))[0]
        self.assertEqual(task.notification_scheduled_at, self.at(2, 8))
        task.status = "SUCCESS"
        task.results = {"purchase": {"status": "SUCCESS"}}
        task.save()
        with patch("integrations.services.erp_analysis.runner.DingtalkClient") as client:
            notify(task.pk, now=self.at(1, 23))
            self.assertFalse(client.called)
            notify(task.pk, now=self.at(2, 8))
            self.assertEqual(client.return_value.post.call_count, 1)

    def test_validation_rejects_send_before_analysis(self):
        self.schedule.send_time = time(7, 29)
        with self.assertRaises(ValidationError) as caught:
            self.schedule.clean()
        self.assertIn("send_time", caught.exception.message_dict)
        self.schedule.day, self.schedule.send_day = 2, 1
        with self.assertRaises(ValidationError):
            self.schedule.clean()

    def test_equal_analysis_and_send_time_is_allowed(self):
        self.schedule.send_time = self.schedule.start_time
        self.schedule.clean()

    def test_no_group_means_no_notification_due(self):
        self.schedule.notification_group = None
        self.schedule.save()
        task = enqueue_due(self.at(1, 7, 30))[0]
        self.assertEqual(task.notification_status, "NONE")
        self.assertIsNone(task.notification_scheduled_at)

    def test_scheduled_send_time_is_task_snapshot_not_live_config(self):
        task = self.completed_task()
        self.schedule.send_time = time(12)
        self.schedule.save()
        self.assertEqual(enqueue_due(self.at(1, 8, 45))[0].pk, task.pk)
        task.refresh_from_db()
        self.assertEqual(task.notification_scheduled_at, self.at(1, 8, 45))

    def test_admin_has_separate_day_and_time_pickers(self):
        form = ErpAnalysisScheduleForm(instance=self.schedule)
        self.assertEqual(form.fields["start_time"].widget.input_type, "time")
        self.assertEqual(form.fields["send_time"].widget.input_type, "time")
        self.assertIn("send_day", form.fields)
        self.assertNotIn("hour", form.fields)

    def test_manual_notification_without_due_time_remains_immediate(self):
        task = enqueue(self.company, date(2026, 5, 1), ["purchase"], notification_group=self.group)
        task.status = "SUCCESS"
        task.results = {"purchase": {"status": "SUCCESS"}}
        task.save()
        with patch("integrations.services.erp_analysis.runner.DingtalkClient") as client:
            notify(task.pk, now=self.at(1, 7))
            self.assertEqual(client.return_value.post.call_count, 1)

    def test_process_finishing_early_does_not_notify(self):
        task = enqueue_due(self.at(1, 7, 30))[0]
        with (
            patch("integrations.services.erp_analysis.runner.build_sdk", side_effect=ValueError("test failure")),
            patch("integrations.services.erp_analysis.runner.timezone.now", return_value=self.at(1, 7, 31)),
            patch("integrations.services.erp_analysis.runner.DingtalkClient") as client,
        ):
            process_task(task.pk)
        self.assertFalse(client.called)
        task.refresh_from_db()
        self.assertEqual(task.status, "FAILED")
        self.assertEqual(task.notification_status, "PENDING")


class ExistingScheduleMigrationTests(TransactionTestCase):
    def test_existing_hour_and_day_are_preserved_for_both_times(self):
        executor = MigrationExecutor(connection)
        executor.migrate([("integrations", "0024_erp_analysis")])
        try:
            apps = executor.loader.project_state([("integrations", "0024_erp_analysis")]).apps
            company = apps.get_model("core", "Company").objects.get(code="A")
            schedule = apps.get_model("integrations", "ErpAnalysisSchedule").objects.create(
                company=company, enabled=True, day=6, hour=18, report_kinds=["purchase"]
            )
            executor = MigrationExecutor(connection)
            executor.migrate([("integrations", "0025_erp_analysis_separate_send_time")])
            migrated = ErpAnalysisSchedule.objects.get(pk=schedule.pk)
            self.assertEqual(migrated.day, 6)
            self.assertEqual(migrated.start_time, time(18))
            self.assertEqual(migrated.send_day, 6)
            self.assertEqual(migrated.send_time, time(18))
        finally:
            executor = MigrationExecutor(connection)
            executor.migrate(executor.loader.graph.leaf_nodes())
