import django.db.models.deletion
from django.db import migrations, models


def backfill_company_from_customer(apps, schema_editor):
    SalesShipment = apps.get_model("sales", "SalesShipment")
    for shipment in SalesShipment.objects.filter(company__isnull=True).select_related("customer"):
        SalesShipment.objects.filter(pk=shipment.pk).update(company_id=shipment.customer.company_id)


class Migration(migrations.Migration):

    dependencies = [
        ("sales", "0004_alter_salesshipment_source"),
        ("core", "0005_company_scope"),
    ]

    operations = [
        migrations.AddField(
            model_name="salesshipment",
            name="company",
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.PROTECT, related_name="sales_shipments", to="core.company", verbose_name="公司"),
        ),
        migrations.RunPython(backfill_company_from_customer, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="salesshipment",
            name="company",
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="sales_shipments", to="core.company", verbose_name="公司"),
        ),
    ]
