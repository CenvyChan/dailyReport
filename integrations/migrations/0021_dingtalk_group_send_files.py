from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("integrations", "0020_dingtalk_group_storage_space"),
    ]

    operations = [
        migrations.AddField(
            model_name="dingtalkgroupconfig",
            name="send_files",
            field=models.BooleanField(
                default=False,
                help_text="关闭时只发日报卡片和在线链接；打开后按群文件卡片发送 PDF/Excel。",
                verbose_name="发送 PDF/Excel 附件",
            ),
        ),
    ]
