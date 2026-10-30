from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("integrations", "0019_dingtalk_group_enabled_at"),
    ]

    operations = [
        migrations.AddField(
            model_name="dingtalkgroupconfig",
            name="storage_space_id",
            field=models.CharField(
                blank=True,
                default="",
                help_text="该群对应的钉钉群文件空间 spaceId。测试群和正式群各填各的，避免文件发错群；留空时按 openConversationId 自动查询。",
                max_length=64,
                verbose_name="群文件空间ID",
            ),
        ),
    ]
