"""按表单实体前缀修正明细内码字段。

实测（账套 688340ae010e02，2026-10）：0009 恢复的裸 FEntryID 只有
SAL_OUTSTOCK 能解析；STK_InStock 报「FEntryID 不是简单属性」。行内码
必须带实体前缀查询：

- SAL_OUTSTOCK 明细实体是 FEntity → FEntity_FEntryID
- STK_InStock 明细实体是 FInStockEntry → FInStockEntry_FEntryID

不带前缀或用错实体名时查询报错，整个窗口的同步会失败。
"""

from django.db import migrations

ENTRY_FIELDS = {
    "SALES_OUT": "FEntity_FEntryID",
    "PURCHASE_IN": "FInStockEntry_FEntryID",
}


def seed_entity_prefixed_entry_id(apps, schema_editor):
    Cfg = apps.get_model("integrations", "KingdeeFormConfig")
    for business_type, field in ENTRY_FIELDS.items():
        Cfg.objects.filter(business_type=business_type).update(fld_entry_id=field)


def reset_to_fentry_id(apps, schema_editor):
    Cfg = apps.get_model("integrations", "KingdeeFormConfig")
    for business_type in ENTRY_FIELDS:
        Cfg.objects.filter(business_type=business_type).update(fld_entry_id="FEntryID")


class Migration(migrations.Migration):
    dependencies = [("integrations", "0009_seed_entry_id")]
    operations = [migrations.RunPython(seed_entity_prefixed_entry_id, reset_to_fentry_id)]
