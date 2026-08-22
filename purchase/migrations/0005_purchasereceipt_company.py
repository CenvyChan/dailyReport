import django.db.models.deletion
from django.db import migrations, models


def backfill_company_from_supplier(apps, schema_editor):
    PurchaseReceipt = apps.get_model("purchase", "PurchaseReceipt")
    for receipt in PurchaseReceipt.objects.filter(company__isnull=True).select_related("supplier"):
        PurchaseReceipt.objects.filter(pk=receipt.pk).update(company_id=receipt.supplier.company_id)


class Migration(migrations.Migration):

    dependencies = [
        ("purchase", "0004_alter_purchasereceipt_source"),
        ("core", "0005_company_scope"),
    ]

    operations = [
        migrations.AddField(
            model_name="purchasereceipt",
            name="company",
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.PROTECT, related_name="purchase_receipts", to="core.company", verbose_name="公司"),
        ),
        migrations.RunPython(backfill_company_from_supplier, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="purchasereceipt",
            name="company",
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="purchase_receipts", to="core.company", verbose_name="公司"),
        ),
    ]
