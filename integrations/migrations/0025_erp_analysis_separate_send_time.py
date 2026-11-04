import datetime

from django.db import migrations, models

import integrations.services.erp_analysis.catalog


def preserve_existing_timing(apps, schema_editor):
    Schedule = apps.get_model("integrations", "ErpAnalysisSchedule")
    for schedule in Schedule.objects.using(schema_editor.connection.alias).all():
        schedule.start_time = datetime.time(schedule.hour)
        schedule.send_day = schedule.day
        schedule.send_time = schedule.start_time
        schedule.save(update_fields=["start_time", "send_day", "send_time"])


def restore_hour(apps, schema_editor):
    Schedule = apps.get_model("integrations", "ErpAnalysisSchedule")
    for schedule in Schedule.objects.using(schema_editor.connection.alias).all():
        schedule.hour = schedule.start_time.hour
        schedule.save(update_fields=["hour"])


class Migration(migrations.Migration):
    dependencies = [("integrations", "0024_erp_analysis")]

    operations = [
        migrations.AddField(
            model_name="erpanalysisschedule",
            name="start_time",
            field=models.TimeField(
                default=integrations.services.erp_analysis.catalog.default_analysis_start_time, help_text="北京时间；例如 07:30。", verbose_name="开始分析时间"
            ),
        ),
        migrations.AddField(
            model_name="erpanalysisschedule",
            name="send_day",
            field=models.PositiveSmallIntegerField(
                default=1, help_text="北京时间每月 1–28 日，不能早于开始分析时间。", verbose_name="每月定时发送日"
            ),
        ),
        migrations.AddField(
            model_name="erpanalysisschedule",
            name="send_time",
            field=models.TimeField(
                default=integrations.services.erp_analysis.catalog.default_analysis_send_time,
                help_text="到点后发送已完成报告；未完成则完成后补发。工作进程每 60 秒检查一次。",
                verbose_name="定时发送时间",
            ),
        ),
        migrations.AlterField(
            model_name="erpanalysisschedule",
            name="day",
            field=models.PositiveSmallIntegerField(
                default=1, help_text="北京时间每月 1–28 日，到点开始生成分析。", verbose_name="每月开始分析日"
            ),
        ),
        migrations.AddField(
            model_name="erpanalysistask",
            name="notification_scheduled_at",
            field=models.DateTimeField(
                blank=True,
                null=True,
                help_text="创建定时任务时保存的北京时间点；为空表示生成后立即通知。",
                verbose_name="计划发送时间",
            ),
        ),
        migrations.RunPython(preserve_existing_timing, restore_hour),
        migrations.RemoveField(model_name="erpanalysisschedule", name="hour"),
    ]
