"""钉钉群推送配置模型和发送服务。

第一期面向企业内部群，使用应用机器人群消息接口。
"""

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0001_initial"),
        ("integrations", "0007_report_snapshot_and_correction"),
    ]

    operations = [
        migrations.CreateModel(
            name="DingtalkGroupConfig",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("company", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="dingtalk_groups",
                    to="core.company",
                    verbose_name="公司",
                )),
                ("app", models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name="group_configs",
                    to="integrations.dingtalkapp",
                    verbose_name="钉钉应用",
                )),
                ("name", models.CharField("配置名称", max_length=120, help_text="用于识别不同的推送目标")),
                ("open_conversation_id", models.CharField(
                    "内部群ID",
                    max_length=128,
                    help_text="群的 openConversationId，通过机器人获取",
                )),
                ("scope", models.CharField(
                    "推送内容",
                    max_length=10,
                    choices=[("SALES", "仅销售"), ("PURCHASE", "仅采购"), ("BOTH", "销售和采购")],
                    default="BOTH",
                )),
                ("send_at", models.TimeField("每日发送时间", help_text="按服务器所在时区（Asia/Shanghai）触发")),
                ("is_active", models.BooleanField("启用", default=True)),
                ("created_at", models.DateTimeField("创建时间", auto_now_add=True)),
                ("updated_at", models.DateTimeField("更新时间", auto_now=True)),
            ],
            options={
                "verbose_name": "钉钉群推送配置",
                "verbose_name_plural": "钉钉群推送配置",
                "ordering": ["company", "send_at", "name"],
            },
        ),
        migrations.AddConstraint(
            model_name="dingtalkgroupconfig",
            constraint=models.UniqueConstraint(
                fields=["company", "name"],
                name="uniq_dingtalk_group_per_company",
            ),
        ),
    ]
