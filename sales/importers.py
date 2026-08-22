import re
import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation

import pandas as pd
import xlrd
from django.contrib.auth.models import Group, User
from django.db import transaction

from core.errors import MissingExchangeRate
from core.excel import read_rows, require_columns
from core.models import Customer, ExchangeRate, SalesAssignment
from core.services.audit import record_audit
from core.services.companies import grant_company_access
from core.services.permissions import is_administrator
from sales.models import SalesShipment


# 每列的别名，第一个是模板里用的标准列名，后面是兼容的历史写法。
# 与 purchase.importers.PURCHASE_COLUMNS 结构一致。
SALES_COLUMNS = (
    ("客户名称", "客户", "客户简称"),
    ("业务跟单", "销售跟单", "业务员"),
    ("销售类型", "币别"),
    ("出货日期", "发货日期", "日期"),
    ("数量",),
    ("金额", "金额（含税）", "金额(含税)"),
)
SALE_TYPES = {
    "内销": "DOMESTIC",
    "外销": "EXPORT",
    # 源表用「币别」列表达内外销，人民币即内销、美元即外销。
    "人民币": "DOMESTIC",
    "美元": "EXPORT",
}


@dataclass(frozen=True)
class ImportPreview:
    valid_row_count: int
    error_rows: list[dict]
    rows: list[dict]
    rate_errors: list[dict] = None
    exchange_rates: tuple = ()


def _excel_serial_if_datetime(value):
    if isinstance(value, (pd.Timestamp, date)) and not isinstance(value, str):
        if isinstance(value, date) and not hasattr(value, "hour"):
            return value
    if hasattr(value, "year") and hasattr(value, "hour"):
        return xlrd.xldate.xldate_from_datetime_tuple(
            (value.year, value.month, value.day, value.hour, value.minute, value.second), 0
        )
    return value


def validate_sales_rows(rows):
    errors = []
    valid_rows = []
    for row_number, row in enumerate(rows, start=2):
        missing = next(
            (aliases[0] for aliases in SALES_COLUMNS if all(row.get(alias) in (None, "") for alias in aliases)),
            None,
        )
        if missing:
            errors.append({"row_number": row_number, "field": missing, "message": "不能为空"})
            continue
        customer_name = next(row[alias] for alias in SALES_COLUMNS[0] if row.get(alias) not in (None, ""))
        owner_name = next(row[alias] for alias in SALES_COLUMNS[1] if row.get(alias) not in (None, ""))
        type_value = next(row[alias] for alias in SALES_COLUMNS[2] if row.get(alias) not in (None, ""))
        date_value = next(row[alias] for alias in SALES_COLUMNS[3] if row.get(alias) not in (None, ""))
        quantity_value = next(row[alias] for alias in SALES_COLUMNS[4] if row.get(alias) not in (None, ""))
        amount_value = next(row[alias] for alias in SALES_COLUMNS[5] if row.get(alias) not in (None, ""))
        if str(type_value).strip() not in SALE_TYPES:
            errors.append({"row_number": row_number, "field": "销售类型", "message": "仅支持内销或外销"})
            continue
        try:
            shipment_date = pd.to_datetime(date_value).date()
            quantity = Decimal(str(_excel_serial_if_datetime(quantity_value)).strip())
            amount = Decimal(str(_excel_serial_if_datetime(amount_value)).strip())
            if quantity <= 0 or amount < 0:
                raise ValueError
        except (TypeError, ValueError, InvalidOperation):
            errors.append({"row_number": row_number, "field": "数量/金额/日期", "message": "格式或数值无效"})
            continue
        valid_rows.append(
            {
                "row_number": row_number,
                "customer_name": str(customer_name).strip(),
                "owner_name": str(owner_name).strip(),
                "sale_type": SALE_TYPES[str(type_value).strip()],
                "shipment_date": shipment_date,
                "quantity": quantity,
                "original_amount": amount,
            }
        )
    return ImportPreview(len(valid_rows), errors, valid_rows)


def validate_exchange_rate_rows(rows):
    errors = []
    valid = []
    for row_number, row in enumerate(rows, start=2):
        try:
            match = re.search(r"(\d{4})年(\d{1,2})月", str(row.get("日期", "")))
            rate = Decimal(str(row.get("汇率", "")))
            if not match or rate <= 0:
                raise ValueError
            valid.append({"month": date(int(match.group(1)), int(match.group(2)), 1), "usd_to_cny": rate, "row_number": row_number})
        except (TypeError, ValueError, InvalidOperation):
            errors.append({"row_number": row_number, "field": "汇率", "message": "月份或汇率无效"})
    return errors, tuple(valid)


def preview_sales_import(path):
    rows = read_rows(path, "数据表")
    require_columns(rows, SALES_COLUMNS, sheet_label="工作表「数据表」")
    preview = validate_sales_rows(rows)
    rate_errors, rates = validate_exchange_rate_rows(read_rows(path, "汇率"))
    return ImportPreview(preview.valid_row_count, preview.error_rows, preview.rows, rate_errors, rates)


def import_exchange_rates(path, *, actor, company):
    errors, rates = validate_exchange_rate_rows(read_rows(path, "汇率"))
    if errors:
        raise ValueError("汇率表存在无效行")
    from core.services.master_data import save_exchange_rate
    for rate in rates:
        existing = ExchangeRate.objects.filter(company=company, month=rate["month"]).first()
        save_exchange_rate(
            actor=actor,
            company=company,
            instance=existing,
            data={"month": rate["month"], "usd_to_cny": rate["usd_to_cny"]},
        )


def commit_sales_import(preview, *, actor, company, source_file, people=None):
    """people 可选：{源表里的姓名: User}。不传就按姓名当用户名自动建号（页面导入的行为），
    传了就用指定账号，用于源表写中文姓名、系统里却要用工号/拼音登录的场景。

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
        # 汇率要先落库：外销行的折算金额依赖当月汇率。
        from core.services.master_data import save_exchange_rate

        for rate in preview.exchange_rates:
            existing = ExchangeRate.objects.filter(company=company, month=rate["month"]).first()
            save_exchange_rate(
                actor=actor,
                company=company,
                instance=existing,
                data={"month": rate["month"], "usd_to_cny": rate["usd_to_cny"]},
            )

        sales_group = Group.objects.get(name="sales")
        owners = _resolve_owners(rows, people or {}, sales_group, company)
        customers = _resolve_customers(rows, company)
        _ensure_assignments(rows, owners, customers)
        rates = _rate_lookup(company)

        shipments = [
            SalesShipment(
                company=company,
                customer=customers[row["customer_name"]],
                owner=owners[row["owner_name"]],
                sale_type=row["sale_type"],
                shipment_date=row["shipment_date"],
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
        SalesShipment.objects.bulk_create(shipments, batch_size=500)
        # 审计写一条批次级记录，而不是每行一条：明细可由 import_batch 反查。
        record_audit(
            actor=actor,
            instance=company,
            action="IMPORT",
            before={},
            after={
                "model": SalesShipment._meta.label,
                "import_batch": str(batch),
                "source_file": source_file,
                "row_count": len(shipments),
            },
        )
    return preview.valid_row_count


def _resolve_owners(rows, people, sales_group, company):
    """一次性把姓名映射成账号。没有的按姓名建号（保持原有页面导入行为）。"""
    names = {row["owner_name"] for row in rows}
    resolved = {name: people[name] for name in names if name in people}
    missing = names - set(resolved)
    if missing:
        existing = {user.username: user for user in User.objects.filter(username__in=missing)}
        for name in missing:
            resolved[name] = existing.get(name) or User.objects.create(username=name)
    for user in resolved.values():
        user.groups.add(sales_group)
        grant_company_access(user, [company])
    return resolved


def _resolve_customers(rows, company):
    names = {row["customer_name"] for row in rows}
    existing = {
        customer.name: customer
        for customer in Customer.objects.filter(company=company, name__in=names)
    }
    created = Customer.objects.bulk_create(
        [Customer(company=company, name=name) for name in names - set(existing)]
    )
    return {**existing, **{customer.name: customer for customer in created}}


def _ensure_assignments(rows, owners, customers):
    """补齐业务员与客户的归属。日报的 owner 就是按归属带出来的，缺了会被服务层拒绝。"""
    wanted = {(owners[row["owner_name"]].pk, customers[row["customer_name"]].pk) for row in rows}
    existing = set(
        SalesAssignment.objects.filter(
            user_id__in={user_id for user_id, _ in wanted},
            customer_id__in={customer_id for _, customer_id in wanted},
        ).values_list("user_id", "customer_id")
    )
    SalesAssignment.objects.bulk_create(
        [
            SalesAssignment(user_id=user_id, customer_id=customer_id)
            for user_id, customer_id in wanted - existing
        ]
    )


def _rate_lookup(company):
    return dict(
        ExchangeRate.objects.filter(company=company).values_list("month", "usd_to_cny")
    )


def _amounts(company, row, rates):
    """与 sales.services._amount_fields 同口径，但汇率从预取的字典里拿。"""
    if row["sale_type"] == SalesShipment.SaleType.DOMESTIC:
        return {
            "currency": "CNY",
            "exchange_rate": Decimal("1"),
            "amount_cny": Decimal(str(row["original_amount"])),
        }
    month = row["shipment_date"].replace(day=1)
    rate = rates.get(month)
    if rate is None:
        raise MissingExchangeRate(company, month)
    return {
        "currency": "USD",
        "exchange_rate": rate,
        "amount_cny": Decimal(str(row["original_amount"])) * rate,
    }


def import_sales_history(path, *, actor, company):
    preview = preview_sales_import(path)
    if preview.error_rows or preview.rate_errors:
        return preview
    commit_sales_import(preview, actor=actor, company=company, source_file=str(path))
    return preview
