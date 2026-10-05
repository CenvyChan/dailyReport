"""金额字段由原币 FAmount 改为本位币 FAmount_LC。

0003 误将 fld_amount 定为 FAmount，并注释「与系统 amount_cny 未税口径一致」。
该判断只对本位币单成立：FAmount 是原币未税金额，外币单（如美元，汇率 6.8~6.9）
会比系统侧 amount_cny（未税折人民币）小一个汇率倍数，导致月度汇总差异巨大。
改用 FAmount_LC（本位币未税金额），与系统侧口径对齐。币别 fld_currency 已在 0003 配好。

注意：改配置后需重新同步（sync_kingdee --from ... --to ...）覆盖历史 total_amount 才生效。
"""

from django.db import migrations


def to_local_currency(apps, schema_editor):
    Cfg = apps.get_model("integrations", "KingdeeFormConfig")
    Cfg.objects.filter(business_type__in=["SALES_OUT", "PURCHASE_IN"]).update(fld_amount="FAmount_LC")


def revert(apps, schema_editor):
    Cfg = apps.get_model("integrations", "KingdeeFormConfig")
    Cfg.objects.filter(business_type__in=["SALES_OUT", "PURCHASE_IN"]).update(fld_amount="FAmount")


class Migration(migrations.Migration):
    dependencies = [("integrations", "0004_encrypt_secrets")]
    operations = [migrations.RunPython(to_local_currency, revert)]
