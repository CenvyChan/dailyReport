"""为两张表单配置补上明细内码字段 FEntryID。

0003 当时判定「FEntryID 不是可查询的简单属性」，将 fld_entry_id 留空、
同步按行序生成明细身份。阶段 1 实施已改为按 FEntryID 幂等 upsert
（保留本地明细主键与已有关联），缺失内码的行会被跳过并记录同步异常。
若继续留空，同步查不到明细内码，一行明细都不会落库，日报检索与
关联功能无数据可用。FEntryID 是单据明细主键，可通过 ExecuteBillQuery
正常查询，此处按实施计划验收标准补上。
"""

from django.db import migrations

ENTRY_ID = "FEntryID"
BUSINESS_TYPES = ["SALES_OUT", "PURCHASE_IN"]


def seed_entry_id(apps, schema_editor):
    Cfg = apps.get_model("integrations", "KingdeeFormConfig")
    Cfg.objects.filter(business_type__in=BUSINESS_TYPES).exclude(fld_entry_id=ENTRY_ID).update(
        fld_entry_id=ENTRY_ID
    )


def reset_entry_id(apps, schema_editor):
    Cfg = apps.get_model("integrations", "KingdeeFormConfig")
    Cfg.objects.filter(business_type__in=BUSINESS_TYPES, fld_entry_id=ENTRY_ID).update(fld_entry_id="")


class Migration(migrations.Migration):
    dependencies = [("integrations", "0008_dingtalk_group_config")]
    operations = [migrations.RunPython(seed_entry_id, reset_entry_id)]
