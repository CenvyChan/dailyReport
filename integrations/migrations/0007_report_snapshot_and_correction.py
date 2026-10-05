"""报表快照与次日更正模型：支持历史报表归档和变更追踪。

阶段 3 核心：
- ReportSnapshot：不可变报表快照，保存生成时间、来源同步信息、计算口径版本
- ReportCorrection：次日更正记录，汇总尚未报告的历史变化
- ReportDelivery：按"快照+渠道+目标"记录发送结果
"""

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("core", "0001_initial"),
        ("integrations", "0006_daily_report_kingdee_link"),
    ]

    operations = [
        migrations.CreateModel(
            name="ReportSnapshot",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("company", models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name="report_snapshots",
                    to="core.company",
                    verbose_name="公司",
                )),
                ("report_date", models.DateField("报表日期", help_text="报表所属业务日期（前一自然日）")),
                ("scope", models.CharField(
                    choices=[("SALES", "仅销售"), ("PURCHASE", "仅采购"), ("BOTH", "销售和采购")],
                    max_length=10,
                    verbose_name="业务范围",
                )),
                ("data", models.JSONField("报表数据", help_text="包含对账结果、经营指标、异常明细等")),
                ("sync_windows", models.JSONField(
                    "同步窗口信息",
                    default=dict,
                    help_text="记录金蝶同步的实际窗口和完成时间",
                )),
                ("calculation_version", models.CharField(
                    "计算口径版本",
                    max_length=32,
                    default="v1",
                    help_text="用于区分不同版本的对账算法",
                )),
                ("is_complete", models.BooleanField(
                    "数据完整",
                    default=True,
                    help_text="金蝶同步失败或累计期间不完整时标记为 False",
                )),
                ("sync_warnings", models.JSONField(
                    "同步警告",
                    default=list,
                    blank=True,
                    help_text="同步失败或窗口不完整的说明",
                )),
                ("generated_at", models.DateTimeField("生成时间", auto_now_add=True)),
            ],
            options={
                "verbose_name": "报表快照",
                "verbose_name_plural": "报表快照",
                "ordering": ["-report_date", "-generated_at"],
                "indexes": [
                    models.Index(fields=["company", "report_date", "scope"], name="snapshot_lookup_idx"),
                ],
            },
        ),
        migrations.AddConstraint(
            model_name="reportsnapshot",
            constraint=models.UniqueConstraint(
                fields=["company", "report_date", "scope"],
                name="uniq_report_snapshot",
            ),
        ),
        migrations.CreateModel(
            name="ReportCorrection",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("company", models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name="report_corrections",
                    to="core.company",
                    verbose_name="公司",
                )),
                ("original_date", models.DateField("原报表日期")),
                ("correction_type", models.CharField(
                    "更正类型",
                    max_length=20,
                    choices=[
                        ("DAILY_ADD", "日报补录"),
                        ("DAILY_EDIT", "日报修改"),
                        ("DAILY_DELETE", "日报删除"),
                        ("LINK_ADD", "关联新增"),
                        ("LINK_REMOVE", "关联解除"),
                        ("K3_CHANGE", "金蝶变更"),
                        ("MAPPING_CHANGE", "映射变更"),
                    ],
                )),
                ("original_value", models.DecimalField(
                    "原值",
                    max_digits=20,
                    decimal_places=4,
                    null=True,
                    blank=True,
                )),
                ("new_value", models.DecimalField(
                    "新值",
                    max_digits=20,
                    decimal_places=4,
                    null=True,
                    blank=True,
                )),
                ("diff_amount", models.DecimalField(
                    "差额",
                    max_digits=20,
                    decimal_places=4,
                    help_text="新值 - 原值",
                )),
                ("reason", models.TextField("变化原因", blank=True, default="")),
                ("affected_report", models.CharField(
                    "受影响报表",
                    max_length=20,
                    choices=[("SALES", "销售"), ("PURCHASE", "采购")],
                )),
                ("reference_id", models.CharField(
                    "关联数据ID",
                    max_length=128,
                    blank=True,
                    default="",
                    help_text="日报ID、关联ID或单据ID，用于追溯",
                )),
                ("detected_at", models.DateTimeField("检测时间", auto_now_add=True)),
                ("reported_in_snapshot", models.ForeignKey(
                    "ReportSnapshot",
                    verbose_name="已报告于快照",
                    null=True,
                    blank=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name="corrections",
                )),
            ],
            options={
                "verbose_name": "报表更正",
                "verbose_name_plural": "报表更正",
                "ordering": ["-detected_at"],
                "indexes": [
                    models.Index(
                        fields=["company", "original_date", "reported_in_snapshot"],
                        name="correction_lookup_idx",
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="ReportDelivery",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("snapshot", models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name="deliveries",
                    to="integrations.reportsnapshot",
                    verbose_name="报表快照",
                )),
                ("channel", models.CharField(
                    "推送渠道",
                    max_length=20,
                    choices=[("EMAIL", "邮件"), ("DINGTALK", "钉钉群消息")],
                )),
                ("target_identifier", models.CharField(
                    "目标标识",
                    max_length=255,
                    help_text="邮件收件组ID或钉钉群ID",
                )),
                ("target_display", models.CharField(
                    "目标名称",
                    max_length=255,
                    blank=True,
                    default="",
                )),
                ("status", models.CharField(
                    "发送状态",
                    max_length=20,
                    choices=[
                        ("PENDING", "待发送"),
                        ("SENT", "发送成功"),
                        ("FAILED", "发送失败"),
                        ("UNCERTAIN", "结果不明"),
                    ],
                    default="PENDING",
                )),
                ("attempt_count", models.PositiveSmallIntegerField("尝试次数", default=0)),
                ("last_error", models.TextField("最近错误", blank=True, default="")),
                ("created_at", models.DateTimeField("创建时间", auto_now_add=True)),
                ("sent_at", models.DateTimeField("发送时间", null=True, blank=True)),
            ],
            options={
                "verbose_name": "报表推送记录",
                "verbose_name_plural": "报表推送记录",
                "ordering": ["-created_at"],
                "indexes": [
                    models.Index(
                        fields=["snapshot", "channel", "target_identifier"],
                        name="report_delivery_idx",
                    ),
                    models.Index(
                        fields=["status", "attempt_count"],
                        name="delivery_retry_idx",
                    ),
                ],
            },
        ),
        migrations.AddConstraint(
            model_name="reportdelivery",
            constraint=models.UniqueConstraint(
                fields=["snapshot", "channel", "target_identifier"],
                name="uniq_delivery_per_target",
            ),
        ),
    ]
