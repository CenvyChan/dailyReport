"""用 query_metadata + 真实单据核对后的字段名定稿两张表单配置。

核对结论（账套 6a54899b91f454，2026-09）：
- 销售出库 SAL_OUTSTOCK：客户=FCustomerID，物料=FMaterialID（大写ID），币别=FSettleCurrID。
- 采购入库 STK_InStock：供应商=FSupplierId，物料=FMaterialId（小写d），币别=FSettleCurrId。
- 两表金额取 FAmount（未税，与系统 amount_cny 未税口径一致），数量 FRealQty，单价 FPrice，单位 FUnitID.FName。
- 明细内码 FEntryID / 行号 FSeq 均不是可查询的简单属性 → 明细内码留空，同步时按行序生成。
"""

from django.db import migrations

COMMON = {
    "date_field": "FDate",
    "status_filter": "C",
    "fld_fid": "FID",
    "fld_entry_id": "",
    "fld_bill_no": "FBillNo",
    "fld_date": "FDate",
    "fld_status": "FDocumentStatus",
    "fld_approve_date": "FApproveDate",
    "fld_org_number": "FStockOrgId.FNumber",
    "fld_qty": "FRealQty",
    "fld_unit": "FUnitID.FName",
    "fld_price": "FPrice",
    "fld_amount": "FAmount",
}

SALES = {
    **COMMON,
    "form_id": "SAL_OUTSTOCK",
    "fld_party_number": "FCustomerID.FNumber",
    "fld_party_name": "FCustomerID.FName",
    "fld_material_number": "FMaterialID.FNumber",
    "fld_material_name": "FMaterialID.FName",
    "fld_currency": "FSettleCurrID.FNumber",
}

PURCHASE = {
    **COMMON,
    "form_id": "STK_InStock",
    "fld_party_number": "FSupplierId.FNumber",
    "fld_party_name": "FSupplierId.FName",
    "fld_material_number": "FMaterialId.FNumber",
    "fld_material_name": "FMaterialId.FName",
    "fld_currency": "FSettleCurrId.FNumber",
}


def finalize(apps, schema_editor):
    Cfg = apps.get_model("integrations", "KingdeeFormConfig")
    for business_type, values in (("SALES_OUT", SALES), ("PURCHASE_IN", PURCHASE)):
        Cfg.objects.update_or_create(business_type=business_type, defaults=values)


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [("integrations", "0002_seed_form_config")]
    operations = [migrations.RunPython(finalize, noop)]
