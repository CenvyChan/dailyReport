import re
import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation

import pandas as pd
import xlrd
from django.contrib.auth.models import Group, User
from django.db import transaction

from core.models import Customer, ExchangeRate, SalesAssignment
from core.services.permissions import is_administrator
from sales.services import create_sales_shipment


SALES_COLUMNS = ("客户名称", "业务跟单", "销售类型", "出货日期", "数量", "金额")
SALE_TYPES = {"内销": "DOMESTIC", "外销": "EXPORT"}


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
        missing = next((column for column in SALES_COLUMNS if row.get(column) in (None, "")), None)
        if missing:
            errors.append({"row_number": row_number, "field": missing, "message": "不能为空"})
            continue
        if str(row["销售类型"]).strip() not in SALE_TYPES:
            errors.append({"row_number": row_number, "field": "销售类型", "message": "仅支持内销或外销"})
            continue
        try:
            shipment_date = pd.to_datetime(row["出货日期"]).date()
            quantity = int(Decimal(str(_excel_serial_if_datetime(row["数量"]))))
            amount = Decimal(str(_excel_serial_if_datetime(row["金额"])))
            if quantity <= 0 or amount < 0:
                raise ValueError
        except (TypeError, ValueError, InvalidOperation):
            errors.append({"row_number": row_number, "field": "数量/金额/日期", "message": "格式或数值无效"})
            continue
        valid_rows.append(
            {
                "row_number": row_number,
                "customer_name": str(row["客户名称"]).strip(),
                "owner_name": str(row["业务跟单"]).strip(),
                "sale_type": SALE_TYPES[str(row["销售类型"]).strip()],
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
    dataframe = pd.read_excel(path, sheet_name="数据表", engine="xlrd")
    preview = validate_sales_rows(dataframe.to_dict("records"))
    rate_dataframe = pd.read_excel(path, sheet_name="汇率", engine="xlrd")
    rate_errors, rates = validate_exchange_rate_rows(rate_dataframe.to_dict("records"))
    return ImportPreview(preview.valid_row_count, preview.error_rows, preview.rows, rate_errors, rates)


def import_exchange_rates(path, *, actor):
    dataframe = pd.read_excel(path, sheet_name="汇率", engine="xlrd")
    errors, rates = validate_exchange_rate_rows(dataframe.to_dict("records"))
    if errors:
        raise ValueError("汇率表存在无效行")
    from core.services.master_data import save_exchange_rate
    for rate in rates:
        existing = ExchangeRate.objects.filter(month=rate["month"]).first()
        save_exchange_rate(actor=actor, instance=existing, data={"month": rate["month"], "usd_to_cny": rate["usd_to_cny"]})


def commit_sales_import(preview, *, actor, source_file):
    if not is_administrator(actor):
        raise PermissionError("只有管理员可以正式导入")
    if preview.error_rows or preview.rate_errors:
        raise ValueError("导入预览存在错误，不能正式导入")
    batch = uuid.uuid4()
    with transaction.atomic():
        from core.services.master_data import save_exchange_rate
        for rate in preview.exchange_rates:
            existing = ExchangeRate.objects.filter(month=rate["month"]).first()
            save_exchange_rate(actor=actor, instance=existing, data={"month": rate["month"], "usd_to_cny": rate["usd_to_cny"]})
        sales_group = Group.objects.get(name="sales")
        for row in preview.rows:
            owner, _ = User.objects.get_or_create(username=row["owner_name"])
            owner.groups.add(sales_group)
            customer, _ = Customer.objects.get_or_create(name=row["customer_name"])
            SalesAssignment.objects.get_or_create(user=owner, customer=customer)
            create_sales_shipment(
                actor=actor,
                data={
                    "customer": customer,
                    "owner": owner,
                    "sale_type": row["sale_type"],
                    "shipment_date": row["shipment_date"],
                    "quantity": row["quantity"],
                    "original_amount": row["original_amount"],
                    "source": "HISTORY_IMPORT",
                    "source_file": source_file,
                    "import_batch": batch,
                    "source_row": row["row_number"],
                },
            )
    return preview.valid_row_count


def import_sales_history(path, *, actor):
    preview = preview_sales_import(path)
    if preview.error_rows or preview.rate_errors:
        return preview
    commit_sales_import(preview, actor=actor, source_file=str(path))
    return preview
