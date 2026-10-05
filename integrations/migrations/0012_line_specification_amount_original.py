"""明细行补物料规格与原币金额；表单配置补对应取数字段。

实测（账套 688340ae010e02，2026-10）：
- 规格可查：SAL_OUTSTOCK 是 FMaterialID.FSpecification，STK_InStock 是
  FMaterialId.FSpecification（注意大小写差异），值为文本。
- 原币单价 FPrice、原币金额 FAmount、本位币金额 FAmount_LC 均可查；
  本位币单价无独立字段，检索接口按 本位币金额/数量 现算。
同步按 FEntryID 幂等 upsert，部署后重跑历史窗口即可回填两列。
"""

from django.db import migrations, models

SPEC_FIELDS = {
    "SALES_OUT": "FMaterialID.FSpecification",
    "PURCHASE_IN": "FMaterialId.FSpecification",
}


def seed_spec_fields(apps, schema_editor):
    Cfg = apps.get_model("integrations", "KingdeeFormConfig")
    for business_type, field in SPEC_FIELDS.items():
        Cfg.objects.filter(business_type=business_type).update(fld_specification=field)


def reset_spec_fields(apps, schema_editor):
    Cfg = apps.get_model("integrations", "KingdeeFormConfig")
    Cfg.objects.filter(business_type__in=SPEC_FIELDS).update(fld_specification="")


class Migration(migrations.Migration):
    dependencies = [
        ("integrations", "0011_alter_reportcorrection_reported_in_snapshot"),
    ]

    operations = [
        migrations.AddField(
            model_name="kingdeeformconfig",
            name="fld_specification",
            field=models.CharField(blank=True, default="", max_length=64, verbose_name="物料规格字段"),
        ),
        migrations.AddField(
            model_name="kingdeeformconfig",
            name="fld_amount_original",
            field=models.CharField(blank=True, default="FAmount", max_length=64, verbose_name="原币金额字段"),
        ),
        migrations.AddField(
            model_name="stocktransactionline",
            name="specification",
            field=models.CharField(blank=True, default="", max_length=255, verbose_name="物料规格"),
        ),
        migrations.AddField(
            model_name="stocktransactionline",
            name="amount_original",
            field=models.DecimalField(decimal_places=4, default=0, max_digits=20, verbose_name="原币金额"),
        ),
        migrations.RunPython(seed_spec_fields, reset_spec_fields),
    ]
