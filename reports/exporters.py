from io import BytesIO

from openpyxl import Workbook


SALES_HEADERS = ["出货日期", "客户", "负责人", "销售类型", "数量", "币种", "原币金额", "汇率快照", "折算人民币金额"]
PURCHASE_HEADERS = ["采购日期", "供应商", "采购员", "采购类型", "数量", "币种", "原币金额", "汇率快照", "折算人民币金额"]


def sales_export_rows(queryset):
    rows = [
        [
            item.shipment_date,
            item.customer.name,
            item.owner.username,
            item.get_sale_type_display(),
            item.quantity,
            item.currency,
            item.original_amount,
            item.exchange_rate,
            item.amount_cny,
        ]
        for item in queryset.select_related("customer", "owner")
    ]
    return SALES_HEADERS, rows


def purchase_export_rows(queryset):
    rows = [
        [
            item.purchase_date,
            item.supplier.name,
            item.buyer.username,
            item.get_purchase_type_display(),
            item.quantity,
            item.currency,
            item.original_amount,
            item.exchange_rate,
            item.amount_cny,
        ]
        for item in queryset.select_related("supplier", "buyer")
    ]
    return PURCHASE_HEADERS, rows


def workbook_response(headers, rows):
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(headers)
    for row in rows:
        sheet.append(row)
    buffer = BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()
