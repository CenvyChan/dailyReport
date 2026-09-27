from django.db import migrations


def seed_form_configs(apps, schema_editor):
    KingdeeFormConfig = apps.get_model("integrations", "KingdeeFormConfig")
    defaults = {
        "SALES_OUT": {
            "form_id": "SAL_OUTSTOCK",
            "fld_qty": "FRealQty",
            "fld_amount": "FAmount",
            "fld_price": "FPrice",
        },
        "PURCHASE_IN": {
            "form_id": "STK_InStock",
            "fld_qty": "FRealQty",
            "fld_amount": "FAmount",
            "fld_price": "FPrice",
        },
    }
    for business_type, values in defaults.items():
        KingdeeFormConfig.objects.get_or_create(business_type=business_type, defaults=values)


def unseed(apps, schema_editor):
    KingdeeFormConfig = apps.get_model("integrations", "KingdeeFormConfig")
    KingdeeFormConfig.objects.filter(business_type__in=["SALES_OUT", "PURCHASE_IN"]).delete()


class Migration(migrations.Migration):
    dependencies = [("integrations", "0001_initial")]
    operations = [migrations.RunPython(seed_form_configs, unseed)]
