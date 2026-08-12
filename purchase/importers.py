import uuid
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

import pandas as pd
from django.contrib.auth.models import Group, User
from django.db import transaction

from core.models import ExchangeRate, PurchaseAssignment, Supplier
from core.services.permissions import is_administrator
from purchase.services import create_purchase_receipt


PURCHASE_COLUMNS = (
    ("供应商", "客户名称"),
    ("采购员", "业务跟单"),
    ("采购类型", "销售类型"),
    ("采购日期", "出货日期"),
    ("数量",),
    ("金额",),
)
PURCHASE_TYPES = {
    "国内采购": "DOMESTIC",
    "国外采购": "FOREIGN",
    "内销": "DOMESTIC",
    "外销": "FOREIGN",
}


@dataclass(frozen=True)
class ImportPreview:
    valid_row_count: int
    error_rows: list[dict]
    rows: list[dict]
    rate_errors: list[dict] = None


def validate_purchase_rows(rows):
    errors = []
    valid_rows = []
    for row_number, row in enumerate(rows, start=2):
        missing = next(
            (aliases[0] for aliases in PURCHASE_COLUMNS if all(row.get(alias) in (None, "") for alias in aliases)),
            None,
        )
        if missing:
            errors.append({"row_number": row_number, "field": missing, "message": "不能为空"})
            continue
        supplier_name = next(row[alias] for alias in PURCHASE_COLUMNS[0] if row.get(alias) not in (None, ""))
        buyer_name = next(row[alias] for alias in PURCHASE_COLUMNS[1] if row.get(alias) not in (None, ""))
        type_value = next(row[alias] for alias in PURCHASE_COLUMNS[2] if row.get(alias) not in (None, ""))
        date_value = next(row[alias] for alias in PURCHASE_COLUMNS[3] if row.get(alias) not in (None, ""))
        purchase_type = str(type_value).strip()
        if purchase_type not in PURCHASE_TYPES:
            errors.append({"row_number": row_number, "field": "采购类型", "message": "仅支持国内采购或国外采购"})
            continue
        try:
            purchase_date = pd.to_datetime(date_value).date()
            quantity = int(Decimal(str(row["数量"])))
            amount = Decimal(str(row["金额"]))
            if quantity <= 0 or amount < 0:
                raise ValueError
        except (TypeError, ValueError, InvalidOperation):
            errors.append({"row_number": row_number, "field": "数量/金额/日期", "message": "格式或数值无效"})
            continue
        valid_rows.append(
            {
                "row_number": row_number,
                "supplier_name": str(supplier_name).strip(),
                "buyer_name": str(buyer_name).strip(),
                "purchase_type": PURCHASE_TYPES[purchase_type],
                "purchase_date": purchase_date,
                "quantity": quantity,
                "original_amount": amount,
            }
        )
    return ImportPreview(len(valid_rows), errors, valid_rows)


def validate_purchase_rates(rows, *, available_months):
    errors = []
    for row in rows:
        if row["purchase_type"] == "FOREIGN" and row["purchase_date"].replace(day=1) not in available_months:
            errors.append({"row_number": row["row_number"], "field": "汇率", "message": "缺少该月份美元兑人民币汇率"})
    return errors


def preview_purchase_import(path, *, sheet_name=0):
    dataframe = pd.read_excel(path, sheet_name=sheet_name, engine="xlrd")
    preview = validate_purchase_rows(dataframe.to_dict("records"))
    rate_errors = validate_purchase_rates(
        preview.rows,
        available_months=set(ExchangeRate.objects.values_list("month", flat=True)),
    )
    return ImportPreview(preview.valid_row_count, preview.error_rows, preview.rows, rate_errors)


def commit_purchase_import(preview, *, actor, source_file):
    if not is_administrator(actor):
        raise PermissionError("只有管理员可以正式导入")
    if preview.error_rows or preview.rate_errors:
        raise ValueError("导入预览存在错误，不能正式导入")
    batch = uuid.uuid4()
    with transaction.atomic():
        purchase_group = Group.objects.get(name="purchase")
        for row in preview.rows:
            buyer, _ = User.objects.get_or_create(username=row["buyer_name"])
            buyer.groups.add(purchase_group)
            supplier, _ = Supplier.objects.get_or_create(name=row["supplier_name"])
            PurchaseAssignment.objects.get_or_create(user=buyer, supplier=supplier)
            create_purchase_receipt(
                actor=actor,
                data={
                    "supplier": supplier,
                    "buyer": buyer,
                    "purchase_type": row["purchase_type"],
                    "purchase_date": row["purchase_date"],
                    "quantity": row["quantity"],
                    "original_amount": row["original_amount"],
                    "source": "HISTORY_IMPORT",
                    "source_file": source_file,
                    "import_batch": batch,
                    "source_row": row["row_number"],
                },
            )
    return preview.valid_row_count
