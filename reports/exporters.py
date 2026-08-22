from io import BytesIO

from openpyxl import Workbook
from core.services.naming import display_name


SALES_HEADERS = ["出货日期", "客户", "负责人", "销售类型", "数量", "币种", "原币金额", "汇率快照", "折算人民币金额"]
PURCHASE_HEADERS = ["采购日期", "供应商", "采购员", "采购类型", "数量", "币种", "原币金额", "汇率快照", "折算人民币金额"]

# 超过这个行数就不给导了：openpyxl 每个单元格都是一个 Python 对象，
# 几十万行在目标机器（Core2 Duo）上必然把请求拖到超时，用户只会反复点击。
# 一年的日报量远低于这个数，触发说明筛选条件没设对。
MAX_EXPORT_ROWS = 50_000


class ExportTooLarge(Exception):
    """导出行数超限。消息直接给用户看，要说清怎么缩小范围。"""

    def __init__(self, row_count, limit=MAX_EXPORT_ROWS):
        self.row_count = row_count
        self.limit = limit
        super().__init__(
            f"本次导出有 {row_count:,} 行，超过 {limit:,} 行上限。"
            "请缩小日期范围（或用「本月」「本周」按钮）后再导出。"
        )


def _guard_size(queryset):
    row_count = queryset.count()
    if row_count > MAX_EXPORT_ROWS:
        raise ExportTooLarge(row_count)
    return row_count


def sales_export_rows(queryset):
    """返回 (表头, 行生成器)。生成器配合 write_only 工作簿流式写出，
    不把几十万行同时堆在内存里。"""
    _guard_size(queryset)

    def rows():
        for item in queryset.select_related("customer", "owner").iterator(chunk_size=2000):
            yield [
                item.shipment_date,
                item.customer.name,
                display_name(item.owner),
                item.get_sale_type_display(),
                item.quantity,
                item.currency,
                item.original_amount,
                item.exchange_rate,
                item.amount_cny,
            ]

    return SALES_HEADERS, rows()


def purchase_export_rows(queryset):
    _guard_size(queryset)

    def rows():
        for item in queryset.select_related("supplier", "buyer").iterator(chunk_size=2000):
            yield [
                item.purchase_date,
                item.supplier.name,
                display_name(item.buyer),
                item.get_purchase_type_display(),
                item.quantity,
                item.currency,
                item.original_amount,
                item.exchange_rate,
                item.amount_cny,
            ]

    return PURCHASE_HEADERS, rows()


COMPARISON_HEADERS = ["日期", "采购入库金额", "销售金额", "每天占比", "备注"]


def comparison_export_rows(report):
    """导出与页面同构的对比表，末行是月度合计。占比导出成百分数文本，避免 Excel 再乘 100。"""
    rows = [
        [
            row["date"],
            row["purchase_amount"],
            row["sales_amount"],
            f"{row['share']}%" if row["share"] is not None else "",
            "",
        ]
        for row in report["rows"]
    ]
    rows.append(
        [
            "月度合计",
            report["purchase_total"],
            report["sales_total"],
            f"{report['share_total']}%" if report["share_total"] is not None else "",
            "",
        ]
    )
    return COMPARISON_HEADERS, rows


def workbook_response(headers, rows):
    """write_only 模式：单元格不常驻内存，边写边落。
    rows 可以是列表也可以是生成器。"""
    workbook = Workbook(write_only=True)
    sheet = workbook.create_sheet()
    sheet.append(headers)
    for row in rows:
        sheet.append(row)
    buffer = BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()
