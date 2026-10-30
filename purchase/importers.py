import uuid
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

import pandas as pd
from django.contrib.auth.models import Group
from django.db import transaction

from core.errors import MissingExchangeRate
from core.excel import is_blank, read_rows, require_columns
from core.models import ExchangeRate, PurchaseAssignment, Supplier
from core.services.audit import record_audit
from core.services.companies import grant_company_access
from core.services.permissions import is_administrator
from core.services.users import describe_import_people, resolve_import_people
from purchase.models import PurchaseReceipt


# 每列的别名，第一个是模板里用的标准列名，后面是兼容的历史写法。
PURCHASE_COLUMNS = (
    ("供应商", "供应商名称", "客户名称"),
    ("采购员", "采购跟单", "业务跟单"),
    ("采购类型", "币别", "销售类型"),
    ("采购日期", "入库日期", "出货日期"),
    ("数量",),
    ("金额", "金额（含税）", "金额(含税)"),
)
PURCHASE_TYPES = {
    "国内采购": "DOMESTIC",
    "国外采购": "FOREIGN",
    "内销": "DOMESTIC",
    "外销": "FOREIGN",
    # 源表用「币别」列表达内外采购，人民币即国内、美元即国外。
    "人民币": "DOMESTIC",
    "美元": "FOREIGN",
}


@dataclass(frozen=True)
class ImportPreview:
    valid_row_count: int
    error_rows: list[dict]
    rows: list[dict]
    rate_errors: list[dict] = None
    people: dict = None


def validate_purchase_rows(rows):
    errors = []
    valid_rows = []
    for row_number, row in enumerate(rows, start=2):
        missing = next(
            (aliases[0] for aliases in PURCHASE_COLUMNS if all(is_blank(row.get(alias)) for alias in aliases)),
            None,
        )
        if missing:
            errors.append({"row_number": row_number, "field": missing, "message": "不能为空"})
            continue
        supplier_name = next(row[alias] for alias in PURCHASE_COLUMNS[0] if not is_blank(row.get(alias)))
        buyer_name = next(row[alias] for alias in PURCHASE_COLUMNS[1] if not is_blank(row.get(alias)))
        type_value = next(row[alias] for alias in PURCHASE_COLUMNS[2] if not is_blank(row.get(alias)))
        date_value = next(row[alias] for alias in PURCHASE_COLUMNS[3] if not is_blank(row.get(alias)))
        quantity_value = next(row[alias] for alias in PURCHASE_COLUMNS[4] if not is_blank(row.get(alias)))
        amount_value = next(row[alias] for alias in PURCHASE_COLUMNS[5] if not is_blank(row.get(alias)))
        purchase_type = str(type_value).strip()
        if purchase_type not in PURCHASE_TYPES:
            errors.append({"row_number": row_number, "field": "采购类型", "message": "仅支持国内采购或国外采购"})
            continue
        try:
            purchase_date = pd.to_datetime(date_value).date()
            quantity = Decimal(str(quantity_value).strip())
            amount = Decimal(str(amount_value).strip())
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


def preview_purchase_import(path, *, company, sheet_name=0, people=None):
    rows = read_rows(path, sheet_name)
    require_columns(rows, PURCHASE_COLUMNS)
    preview = validate_purchase_rows(rows)
    rate_errors = validate_purchase_rates(
        preview.rows,
        available_months=set(
            ExchangeRate.objects.filter(company=company).values_list("month", flat=True)
        ),
    )
    # 人员解析只作为预览提示，不进 error_rows：正式导入时才会强制。
    people_info = describe_import_people(
        (row["buyer_name"] for row in preview.rows), provided=people
    )
    return ImportPreview(
        preview.valid_row_count,
        preview.error_rows,
        preview.rows,
        rate_errors,
        people_info,
    )


def commit_purchase_import(preview, *, actor, company, source_file, people=None, create_missing=False):
    """people 可选：{源表里的姓名: User}，用于源表写中文姓名、系统里却用
    工号/拼音登录的场景。不传时按登录名和 first_name 自动匹配（历史拼音
    账号能命中）；仍匹配不到的姓名默认报错而不是建号——按姓名建号会造出
    无法登录的重复账号。create_missing=True 才允许为这些姓名新建账号。

    整批一次性写入：逐行 get_or_create 时 3000 行要跑近 3 万次查询，全都压在
    一个 atomic() 里独占 SQLite 写锁，浏览器先超时、用户再重复点击。
    """
    if not is_administrator(actor):
        raise PermissionError("只有管理员可以正式导入")
    if preview.error_rows or preview.rate_errors:
        raise ValueError("导入预览存在错误，不能正式导入")
    batch = uuid.uuid4()
    rows = preview.rows
    with transaction.atomic():
        purchase_group = Group.objects.get(name="purchase")
        buyers = _resolve_buyers(
            rows, people or {}, purchase_group, company, create_missing=create_missing
        )
        suppliers = _resolve_suppliers(rows, company)
        _ensure_assignments(rows, buyers, suppliers)
        rates = _rate_lookup(company)

        receipts = [
            PurchaseReceipt(
                company=company,
                supplier=suppliers[row["supplier_name"]],
                buyer=buyers[row["buyer_name"]],
                purchase_type=row["purchase_type"],
                purchase_date=row["purchase_date"],
                quantity=row["quantity"],
                source="HISTORY_IMPORT",
                source_file=source_file,
                import_batch=batch,
                source_row=row["row_number"],
                original_amount=row["original_amount"],
                **_amounts(company, row, rates),
            )
            for row in rows
        ]
        PurchaseReceipt.objects.bulk_create(receipts, batch_size=500)
        # 审计写一条批次级记录，而不是每行一条：明细可由 import_batch 反查。
        record_audit(
            actor=actor,
            instance=company,
            action="IMPORT",
            before={},
            after={
                "model": PurchaseReceipt._meta.label,
                "import_batch": str(batch),
                "source_file": source_file,
                "row_count": len(receipts),
            },
        )
    return preview.valid_row_count


def _resolve_buyers(rows, people, purchase_group, company, *, create_missing=False):
    """一次性把姓名映射成账号。登录名和 first_name 都参与匹配，避免把
    已有拼音账号当成新人再建一遍。"""
    resolved = resolve_import_people(
        (row["buyer_name"] for row in rows),
        provided=people,
        create_missing=create_missing,
    )
    for user in resolved.values():
        user.groups.add(purchase_group)
        grant_company_access(user, [company])
    return resolved


def _resolve_suppliers(rows, company):
    names = {row["supplier_name"] for row in rows}
    existing = {
        supplier.name: supplier
        for supplier in Supplier.objects.filter(company=company, name__in=names)
    }
    created = Supplier.objects.bulk_create(
        [Supplier(company=company, name=name) for name in names - set(existing)]
    )
    return {**existing, **{supplier.name: supplier for supplier in created}}


def _ensure_assignments(rows, buyers, suppliers):
    """补齐采购员与供应商的归属。日报的 buyer 就是按归属带出来的，缺了会被服务层拒绝。"""
    wanted = {(buyers[row["buyer_name"]].pk, suppliers[row["supplier_name"]].pk) for row in rows}
    existing = set(
        PurchaseAssignment.objects.filter(
            user_id__in={user_id for user_id, _ in wanted},
            supplier_id__in={supplier_id for _, supplier_id in wanted},
        ).values_list("user_id", "supplier_id")
    )
    PurchaseAssignment.objects.bulk_create(
        [
            PurchaseAssignment(user_id=user_id, supplier_id=supplier_id)
            for user_id, supplier_id in wanted - existing
        ]
    )


def _rate_lookup(company):
    return dict(
        ExchangeRate.objects.filter(company=company).values_list("month", "usd_to_cny")
    )


def _amounts(company, row, rates):
    """与 purchase.services._amount_fields 同口径，但汇率从预取的字典里拿。"""
    if row["purchase_type"] == PurchaseReceipt.PurchaseType.DOMESTIC:
        return {"currency": "CNY", "exchange_rate": Decimal("1"), "amount_cny": Decimal(str(row["original_amount"]))}
    month = row["purchase_date"].replace(day=1)
    rate = rates.get(month)
    if rate is None:
        raise MissingExchangeRate(company, month)
    return {
        "currency": "USD",
        "exchange_rate": rate,
        "amount_cny": Decimal(str(row["original_amount"])) * rate,
    }
