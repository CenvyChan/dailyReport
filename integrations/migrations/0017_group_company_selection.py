from django.db import migrations, models
import django.db.models.deletion


def copy_legacy_company_links(apps, schema_editor):
    Group = apps.get_model("integrations", "DingtalkGroupConfig")
    Dispatch = apps.get_model("integrations", "PaymentReportDispatch")
    for group in Group.objects.exclude(company_id=None):
        group.companies.add(group.company_id)
    for dispatch in Dispatch.objects.select_related("group"):
        if dispatch.group.company_id is None:
            raise RuntimeError(
                f"付款投递记录 {dispatch.pk} 的历史群配置没有公司，无法迁移"
            )
        dispatch.company_id = dispatch.group.company_id
        dispatch.save(update_fields=["company"])


def restore_legacy_company_links(apps, schema_editor):
    Group = apps.get_model("integrations", "DingtalkGroupConfig")
    Dispatch = apps.get_model("integrations", "PaymentReportDispatch")
    for group in Group.objects.filter(company_id=None):
        company_id = group.companies.values_list("pk", flat=True).first()
        if company_id:
            group.company_id = company_id
            group.save(update_fields=["company"])
    for dispatch in Dispatch.objects.filter(company_id=None).select_related("group"):
        if dispatch.group.company_id:
            dispatch.company_id = dispatch.group.company_id
            dispatch.save(update_fields=["company"])


class Migration(migrations.Migration):
    dependencies = [("integrations", "0016_payment_organization_routing")]

    operations = [
        migrations.AlterField(
            model_name="dingtalkgroupconfig",
            name="company",
            field=models.ForeignKey(
                blank=True,
                help_text="仅兼容历史配置；新建群配置请在“推送公司”中多选。",
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="legacy_dingtalk_groups",
                to="core.company",
                verbose_name="旧版公司",
            ),
        ),
        migrations.AddField(
            model_name="dingtalkgroupconfig",
            name="companies",
            field=models.ManyToManyField(
                blank=True,
                help_text="同一个群配置可多选公司；只推送勾选的公司。",
                related_name="dingtalk_groups",
                to="core.company",
                verbose_name="推送公司",
            ),
        ),
        migrations.AddField(
            model_name="paymentreportdispatch",
            name="company",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="payment_report_dispatches",
                to="core.company",
            ),
        ),
        migrations.RunPython(copy_legacy_company_links, restore_legacy_company_links),
        migrations.AlterField(
            model_name="paymentreportdispatch",
            name="company",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="payment_report_dispatches",
                to="core.company",
            ),
        ),
        migrations.RemoveConstraint(
            model_name="paymentreportdispatch",
            name="uniq_payment_dispatch",
        ),
        migrations.AddConstraint(
            model_name="paymentreportdispatch",
            constraint=models.UniqueConstraint(
                fields=("group", "company", "report_type", "delivery_date"),
                name="uniq_payment_dispatch",
            ),
        ),
    ]
