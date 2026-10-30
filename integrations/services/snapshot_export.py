"""统一采销日报 Excel：金蝶汇总 / 逐日金额，另附原有手工月度对比表。"""

import math
import os
from io import BytesIO
from decimal import Decimal
from openpyxl import Workbook
from openpyxl.drawing.image import Image as WorkbookImage
from openpyxl.styles import Alignment, Font, PatternFill
from integrations.services.operations_summary import (
    snapshot_operations,
    snapshot_detail_context,
)

COMPARISON_SHEET = "采购入库金额与销售金额对比表"

# 手机端钉钉/WPS 的 Excel 预览器普遍不渲染 openpyxl 原生折线图，只认图片。
# 这里统一把折线图画成 PNG 嵌进工作表，电脑和手机看到的都是同一张静态图。
_FONT_PATHS = (
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "C:/Windows/Fonts/msyh.ttc",
    "C:/Windows/Fonts/arial.ttf",
)


def _font(size):
    from PIL import ImageFont

    for path in _FONT_PATHS:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                continue
    return ImageFont.load_default()


def _chart_png(rows, names):
    """把当月采销趋势画成静态 PNG；没有数据时返回 None。"""
    from PIL import Image, ImageDraw

    if not rows:
        return None

    width, height = 1000, 380
    left, right, top, bottom = 84, 28, 56, 62
    plot_w, plot_h = width - left - right, height - top - bottom
    canvas = Image.new("RGB", (width, height), "#ffffff")
    draw = ImageDraw.Draw(canvas)
    title_font, label_font, tick_font = _font(24), _font(16), _font(14)

    draw.text((left, 14), "当月采销对比折线图", fill="#0f172a", font=title_font)
    draw.text((left, 44), "金额单位：万元", fill="#64748b", font=tick_font)

    series = []
    for name in names:
        values = []
        for row in rows:
            try:
                values.append(float(row.get(name + "_amount") or 0) / 10000)
            except (TypeError, ValueError):
                values.append(0.0)
        series.append((name, values))

    peak = max([max(values) if values else 0.0 for _, values in series] + [0.0])
    step = 1.0
    if peak > 0:
        rough = peak / 5
        magnitude = 10 ** math.floor(math.log10(rough))
        step = math.ceil(rough / magnitude) * magnitude
    peak = step * 5
    decimals = 0 if step >= 1 else max(1, int(-math.floor(math.log10(step))))

    for index in range(6):
        value = step * index
        y = top + plot_h - plot_h * index / 5
        draw.line((left, y, left + plot_w, y), fill="#e2e8f0", width=1)
        draw.text(
            (left - 10, y),
            f"{value:,.{decimals}f}",
            fill="#64748b",
            font=tick_font,
            anchor="rm",
        )
    draw.line((left, top, left, top + plot_h), fill="#cbd5e1", width=1)
    draw.line((left, top + plot_h, left + plot_w, top + plot_h), fill="#cbd5e1", width=1)

    x_step = plot_w / max(len(rows) - 1, 1)
    colors = {"purchase": "#b45309", "sales": "#2563eb"}
    labels = {"purchase": "采购入库", "sales": "销售"}
    for name, values in series:
        color = colors.get(name, "#334155")
        points = [
            (left + x_step * index, top + plot_h - (value / peak) * plot_h)
            for index, value in enumerate(values)
        ]
        if len(points) > 1:
            draw.line(points, fill=color, width=3, joint="curve")
        for x, y in points:
            draw.ellipse((int(x) - 3, int(y) - 3, int(x) + 3, int(y) + 3), fill=color)

    tick_count = min(6, len(rows))
    for index in range(tick_count):
        row_index = round(index * (len(rows) - 1) / max(tick_count - 1, 1))
        x = left + x_step * row_index
        draw.text(
            (int(x), top + plot_h + 10),
            rows[row_index]["date"][5:],
            fill="#64748b",
            font=tick_font,
            anchor="ma",
        )

    legend_x, legend_y = left + 8, top + 10
    for name, _ in series:
        color = colors.get(name, "#334155")
        draw.line((legend_x, legend_y + 8, legend_x + 26, legend_y + 8), fill=color, width=3)
        draw.text((legend_x + 34, legend_y), labels.get(name, name), fill="#334155", font=label_font)
        legend_x += 112

    buffer = BytesIO()
    canvas.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


def _number(value):
    number = Decimal(str(value or 0))
    if not number.is_finite():
        raise ValueError("日报金额必须为有限数值。")
    return float(number)


def _style(ws, header_row):
    ws.freeze_panes = f"B{header_row+1}"
    ws.column_dimensions["A"].width = 24
    for key in ("B", "C", "D", "E"):
        ws.column_dimensions[key].width = 24
    for cell in ws[header_row]:
        cell.fill = PatternFill("solid", fgColor="243C5A")
        cell.font = Font(bold=True, color="FFFFFF")
        cell.alignment = Alignment(horizontal="center")
    for row in ws.iter_rows(min_row=header_row + 1):
        for cell in row:
            if isinstance(cell.value, (float, int)):
                cell.number_format = "#,##0.00;[Red]-#,##0.00"
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.page_setup.orientation = "landscape"
    ws.page_setup.paperSize = ws.PAPERSIZE_A4
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    ws.print_title_rows = f"1:{header_row}"


def _daily_sheet(wb, title, rows, names):
    ws = wb.create_sheet(title)
    ws.append(
        ["日期"]
        + [("采购入库金额" if name == "purchase" else "销售金额") for name in names]
    )
    for row in rows:
        ws.append(
            [row["date"]] + [_number(row.get(name + "_amount")) for name in names]
        )
    _style(ws, 1)
    return ws


def _detail_sheet(wb, snapshot, title, source, headers, records, empty_message, total):
    ws = wb.create_sheet(title)
    ws.append([title])
    ws.append(["报表日期", snapshot.report_date.isoformat()])
    ws.append(["来源", source])
    ws.append(headers)
    for row in records:
        ws.append(row)
    if not records:
        ws.append([empty_message])
    ws.append(["合计"] + [None] * (len(headers) - 4) + total)
    _style(ws, 4)
    ws.column_dimensions["C"].width = 30
    ws.column_dimensions["D"].width = 30
    ws.column_dimensions["E"].width = 20
    ws.column_dimensions["F"].width = 24
    ws.column_dimensions["G"].width = 24
    for row in ws.iter_rows(min_row=5):
        row[4].number_format = "#,##0.######;[Red]-#,##0.######"
    ws["A3"].alignment = Alignment(wrap_text=False)
    ws["B3"].alignment = Alignment(wrap_text=True)
    ws.row_dimensions[3].height = 42
    ws.auto_filter.ref = f"A4:{ws.cell(ws.max_row - 1, len(headers)).coordinate}"
    return ws


def _create_detail_sheets(wb, snapshot, details):
    _detail_sheet(
        wb,
        snapshot,
        "日报提交明细",
        "人员填报日报 / 历史导入；仅报表当日，不以金蝶单据代填",
        ["业务类型", "日期", "客户/供应商", "提报人", "数量", "单位", "日报金额（元）"],
        [
            [
                row["business_label"],
                row.get("date", ""),
                row.get("party_name", ""),
                row.get("reporter", ""),
                _number(row["quantity"]) if row.get("quantity") is not None else None,
                row.get("unit") or "未记录单位",
                _number(row.get("amount")),
            ]
            for row in details["manual_rows"]
        ],
        "暂无提交记录（保留日报字段，未用金蝶数据代填）",
        [
            (
                _number(details["manual_quantity_total"])
                if details["manual_quantity_total"] is not None
                else None
            ),
            details["manual_quantity_unit"],
            _number(details["manual_total"]),
        ],
    )
    missing = details["kingdee_details_missing"]
    kingdee_sheet = _detail_sheet(
        wb,
        snapshot,
        "当日金蝶单据明细",
        "金蝶 K3Cloud 有效"
        + " / ".join(row["label"] for row in details["manual_ledgers"])
        + "单据；报表当日全量单据，不截断，退货保留负数。数量为源单据算术合计，混合单位未折算，不代表统一实物数量。",
        [
            "业务类型",
            "业务日期",
            "单据编号",
            "客户/供应商",
            "数量",
            "单位",
            "金蝶金额（元）",
        ],
        [
            [
                row["business_label"],
                row["date"],
                row["bill_no"],
                row.get("party_name", ""),
                _number(row["quantity"]) if row.get("quantity") is not None else None,
                row.get("unit") or "未记录单位",
                _number(row["amount"]),
            ]
            for row in details["kingdee_documents"]
        ],
        "历史快照未冻结金蝶单据明细，请重新生成" if missing else "当日暂无金蝶单据",
        [
            (
                _number(details["kingdee_quantity_total"])
                if not missing and details["kingdee_quantity_total"] is not None
                else None
            ),
            details["kingdee_quantity_unit"],
            None if missing else _number(details["kingdee_document_total"]),
        ],
    )

    kingdee_sheet.column_dimensions["C"].width = 38
    for row in kingdee_sheet.iter_rows(min_row=4, min_col=3, max_col=3):
        row[0].alignment = Alignment(wrap_text=False)


def export_snapshot_to_excel(snapshot) -> bytes:
    """只读取快照；导出/投递重试不会重新查询实时业务数据。"""
    data = snapshot_operations(snapshot)
    details = snapshot_detail_context(snapshot)
    names = [
        name
        for name, key in [("purchase", "PURCHASE"), ("sales", "SALES")]
        if snapshot.scope in ("BOTH", key)
    ]
    wb = Workbook()
    ws = wb.active
    ws.title = "采销汇总"
    ws.append([snapshot.company.name + " · 采销汇总日报"])
    ws.append(["报表日期", snapshot.report_date.isoformat()])
    business_label = " / ".join(
        "采购入库" if name == "purchase" else "销售出库" for name in names
    )
    ws.append(["来源", "金蝶 K3Cloud · 有效" + business_label + "单，退货保留负数"])
    ws.append(
        ["统计期间", data.get("period_start", "") + "—" + data.get("period_end", "")]
    )
    ws.append(["指标", "金额 / 占比"])
    for name in names:
        label = "采购" if name == "purchase" else "销售"
        ws.append(["当月" + label + "日报合计", _number(data.get(name + "_total"))])
        ws.append(["当日" + label + "金额", _number(data.get(name + "_daily"))])
    if len(names) == 2:
        ws.append(
            [
                "合计占比",
                (
                    float(data["share_total"]) / 100
                    if data.get("share_total") is not None
                    else None
                ),
            ]
        )
        ws.cell(ws.max_row, 2).number_format = "0.00%"
    if len(names) == 2:
        ws.append(
            ["口径", "合计占比 = 当月采购 ÷ 当月销售；销售为 0 时留空。不代表利润率。"]
        )
    if data.get("source") != "KINGDEE":
        ws.append(["提示", "历史快照无金蝶逐日汇总，请重新生成，不能用手工日报替代。"])
    _style(ws, 5)
    for row in ws:
        if row[0].value == "合计占比":
            row[1].number_format = "0.00%"
    for ledger in details["manual_ledgers"]:
        ws.append(["当日" + ledger["label"] + "日报提交笔数", ledger["count"]])
        ws.append(["当日" + ledger["label"] + "日报提交金额", _number(ledger["total"])])
    ws.append(
        [
            "日报提交口径",
            "仅人员填报 / 历史导入的报表当日记录；没有提交时保留表头和空状态，不以金蝶数据代填。",
        ]
    )
    for row in ws.iter_rows(min_row=6):
        if str(row[0].value).endswith("提交笔数"):
            row[1].number_format = "0"
        elif str(row[0].value).endswith("提交金额"):
            row[1].number_format = "#,##0.00;[Red]-#,##0.00"
    _create_detail_sheets(wb, snapshot, details)
    daily = _daily_sheet(wb, "当月金蝶采销", data.get("month_rows", []), names)
    _daily_sheet(wb, "近15天金蝶趋势", data.get("trend_rows", []), names)
    chart_png = _chart_png(data.get("month_rows", []), names)
    if chart_png:
        chart_image = WorkbookImage(BytesIO(chart_png))
        chart_image.width, chart_image.height = 820, 312
        ws.add_image(chart_image, "D2")
        ws.append(
            [
                "图表说明",
                "「当月采销对比折线图」为静态图片，手机端和电脑端都能直接显示；逐日数据见「当月金蝶采销」。",
            ]
        )
    comparison = (snapshot.data or {}).get("monthly_comparison")
    if comparison:
        title = (
            COMPARISON_SHEET
            if len(names) == 2
            else ("采购入库金额对比表" if names == ["purchase"] else "销售金额对比表")
        )
        manual = wb.create_sheet(title)
        manual.append([title])
        manual.append(["月份", f"{comparison['year']}-{comparison['month']:02d}"])
        manual.append(
            [
                "来源",
                "原有对比表 · 手工录入 / 历史导入 · 未税人民币金额；不是金蝶单据金额",
            ]
        )
        headers = ["日期"] + [
            ("采购入库金额" if name == "purchase" else "销售金额") for name in names
        ]
        if len(names) == 2:
            headers += ["每天占比"]
        headers += ["备注"]
        manual.append(headers)
        for row in comparison["rows"]:
            values = [row["date"]] + [
                _number(row.get(name + "_amount")) for name in names
            ]
            if len(names) == 2:
                values += [
                    float(row["share"]) / 100 if row.get("share") is not None else None
                ]
            manual.append(values + [""])
        totals = ["月度合计"] + [
            _number(comparison.get(name + "_total")) for name in names
        ]
        if len(names) == 2:
            totals += [
                (
                    float(comparison["share_total"]) / 100
                    if comparison.get("share_total") is not None
                    else None
                )
            ]
        manual.append(totals + [""])
        _style(manual, 4)
        if len(names) == 2:
            for row in manual.iter_rows(min_row=5):
                row[3].number_format = "0.00%"
        manual.auto_filter.ref = (
            f"A4:{manual.cell(manual.max_row-1,manual.max_column).coordinate}"
        )
    output = BytesIO()
    wb.save(output)
    return output.getvalue()
