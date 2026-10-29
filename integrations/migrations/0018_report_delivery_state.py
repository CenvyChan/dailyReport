from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("integrations", "0017_group_company_selection")]

    operations = [
        migrations.AddField(
            model_name="reportdelivery",
            name="delivery_state",
            field=models.JSONField("分步投递状态", default=dict, blank=True),
        ),
    ]
