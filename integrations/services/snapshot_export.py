"""报表快照 Excel 导出：生成多工作表 Excel 文件。

包含：
- 摘要：关键指标和覆盖率
- 次日更正：历史变化明细
- 销售对账：日报覆盖率、期间差异、金蝶明细分摊
- 采购对账：同上
"""

from io import BytesIO

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill


def export_snapshot_to_excel(snapshot) -> bytes:
    """导出报表快照为 Excel 二进制内容。

    Args:
        snapshot: ReportSnapshot 对象

    Returns:
        Excel 文件二进制内容（bytes）
    """
    wb = Workbook()

    # 删除默认工作表
    wb.remove(wb.active)

    # 创建摘要工作表
    _create_summary_sheet(wb, snapshot)

    # 创建次日更正工作表（如果有）
    if snapshot.data.get("corrections"):
        _create_corrections_sheet(wb, snapshot)

    # 创建销售对账工作表
    if snapshot.scope in ("BOTH", "SALES") and "sales" in snapshot.data:
        _create_sales_sheet(wb, snapshot)

    # 创建采购对账工作表
    if snapshot.scope in ("BOTH", "PURCHASE") and "purchase" in snapshot.data:
        _create_purchase_sheet(wb, snapshot)

    # 保存到字节流
    output = BytesIO()
    wb.save(output)
    return output.getvalue()


def _create_summary_sheet(wb, snapshot):
    """创建摘要工作表。"""
    ws = wb.create_sheet("摘要", 0)

    # 表头
    ws.append([f"{snapshot.company.name} - 经营日报"])
    ws.append([f"报表日期: {snapshot.report_date}"])
    ws.append([f"生成时间: {snapshot.generated_at.strftime('%Y-%m-%d %H:%M:%S')}"])
    ws.append([])

    # 设置表头样式
    for row in range(1, 4):
        ws[f"A{row}"].font = Font(bold=True, size=12)

    # 数据完整性
    if not snapshot.is_complete:
        ws.append(["数据完整性", "不完整"])
        ws["A5"].font = Font(bold=True, color="FF0000")
        ws["B5"].font = Font(color="FF0000")
        for warning in snapshot.sync_warnings:
            ws.append(["警告", warning])
    else:
        ws.append(["数据完整性", "完整"])
        ws["B5"].font = Font(color="00B050")

    ws.append([])

    # 销售摘要
    if "sales" in snapshot.data:
        sales = snapshot.data["sales"]
        ws.append(["销售对账"])
        ws[f"A{ws.max_row}"].font = Font(bold=True, size=11)
        ws.append(["日报笔数", sales["daily_coverage"]["total_reports"]])
        ws.append(["日报金额", sales["daily_coverage"]["total_amount"]])
        ws.append(["已关联金额", sales["daily_coverage"]["covered_amount"]])
        coverage = sales["daily_coverage"]["coverage_rate"]
        ws.append(["覆盖率", f"{coverage:.1f}%" if coverage else "—"])
        ws.append([])
        ws.append(["月度系统金额", sales["month_diff"]["system_amount"]])
        ws.append(["月度金蝶金额", sales["month_diff"]["k3_amount"]])
        ws.append(["月度差额", sales["month_diff"]["diff_amount"]])
        diff_rate = sales["month_diff"]["diff_rate"]
        ws.append(["差异率", f"{diff_rate:.2f}%" if diff_rate else "—"])
        ws.append([])

    # 采购摘要
    if "purchase" in snapshot.data:
        purchase = snapshot.data["purchase"]
        ws.append(["采购对账"])
        ws[f"A{ws.max_row}"].font = Font(bold=True, size=11)
        ws.append(["日报笔数", purchase["daily_coverage"]["total_reports"]])
        ws.append(["日报金额", purchase["daily_coverage"]["total_amount"]])
        ws.append(["已关联金额", purchase["daily_coverage"]["covered_amount"]])
        coverage = purchase["daily_coverage"]["coverage_rate"]
        ws.append(["覆盖率", f"{coverage:.1f}%" if coverage else "—"])
        ws.append([])
        ws.append(["月度系统金额", purchase["month_diff"]["system_amount"]])
        ws.append(["月度金蝶金额", purchase["month_diff"]["k3_amount"]])
        ws.append(["月度差额", purchase["month_diff"]["diff_amount"]])
        diff_rate = purchase["month_diff"]["diff_rate"]
        ws.append(["差异率", f"{diff_rate:.2f}%" if diff_rate else "—"])

    # 调整列宽
    ws.column_dimensions["A"].width = 20
    ws.column_dimensions["B"].width = 25


def _create_corrections_sheet(wb, snapshot):
    """创建次日更正工作表。"""
    ws = wb.create_sheet("次日更正")

    # 表头
    headers = ["原日期", "更正类型", "受影响报表", "原值", "新值", "差额", "原因", "检测时间"]
    ws.append(headers)

    # 设置表头样式
    header_fill = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")
    header_font = Font(bold=True, color="FFFFFF")
    for col in range(1, len(headers) + 1):
        cell = ws.cell(1, col)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center")

    # 数据行
    for corr in snapshot.data.get("corrections", []):
        ws.append([
            corr.get("detected_at", "")[:10],  # 只取日期部分
            corr.get("type", ""),
            corr.get("affected_report", ""),
            corr.get("original_value"),
            corr.get("new_value"),
            corr.get("diff_amount"),
            corr.get("reason", ""),
            corr.get("detected_at", "")[:19],  # 取日期时间
        ])

    # 调整列宽
    ws.column_dimensions["A"].width = 12
    ws.column_dimensions["B"].width = 15
    ws.column_dimensions["C"].width = 15
    ws.column_dimensions["D"].width = 15
    ws.column_dimensions["E"].width = 15
    ws.column_dimensions["F"].width = 15
    ws.column_dimensions["G"].width = 30
    ws.column_dimensions["H"].width = 20


def _create_sales_sheet(wb, snapshot):
    """创建销售对账工作表。"""
    ws = wb.create_sheet("销售对账")
    sales = snapshot.data["sales"]

    # 日报覆盖率明细
    ws.append(["日报关联覆盖率明细"])
    ws[f"A{ws.max_row}"].font = Font(bold=True, size=12)
    ws.append([])

    headers = ["日期", "客商名称", "日报金额", "已关联金额", "封顶分摊", "覆盖率"]
    ws.append(headers)

    # 表头样式
    for col in range(1, len(headers) + 1):
        cell = ws.cell(ws.max_row, col)
        cell.font = Font(bold=True)
        cell.fill = PatternFill(start_color="E7E6E6", end_color="E7E6E6", fill_type="solid")

    for detail in sales["daily_coverage"].get("details", []):
        coverage = detail.get("coverage")
        ws.append([
            detail.get("date", ""),
            detail.get("party_name", ""),
            detail.get("amount"),
            detail.get("allocated_amount"),
            detail.get("capped_allocated"),
            f"{coverage:.1f}%" if coverage is not None else "—",
        ])

    ws.append([])
    ws.append([])

    # 金蝶明细分摊情况
    ws.append(["金蝶明细分摊情况（前100条）"])
    ws[f"A{ws.max_row}"].font = Font(bold=True, size=12)
    ws.append([])

    headers = ["单据编号", "业务日期", "客商", "物料", "金额", "已分摊", "剩余", "超额", "跨日"]
    ws.append(headers)

    for col in range(1, len(headers) + 1):
        cell = ws.cell(ws.max_row, col)
        cell.font = Font(bold=True)
        cell.fill = PatternFill(start_color="E7E6E6", end_color="E7E6E6", fill_type="solid")

    for line in sales["k3_allocation"].get("details", [])[:100]:
        ws.append([
            line.get("bill_no", ""),
            line.get("biz_date", ""),
            line.get("party_name", ""),
            line.get("material_name", ""),
            line.get("amount"),
            line.get("allocated"),
            line.get("remaining"),
            line.get("over_allocated"),
            "是" if line.get("is_cross_date") else "",
        ])

    # 调整列宽
    for col, width in enumerate([20, 12, 25, 35, 15, 15, 15, 15, 8], start=1):
        ws.column_dimensions[chr(64 + col)].width = width


def _create_purchase_sheet(wb, snapshot):
    """创建采购对账工作表（结构同销售）。"""
    ws = wb.create_sheet("采购对账")
    purchase = snapshot.data["purchase"]

    # 日报覆盖率明细
    ws.append(["日报关联覆盖率明细"])
    ws[f"A{ws.max_row}"].font = Font(bold=True, size=12)
    ws.append([])

    headers = ["日期", "供应商名称", "日报金额", "已关联金额", "封顶分摊", "覆盖率"]
    ws.append(headers)

    for col in range(1, len(headers) + 1):
        cell = ws.cell(ws.max_row, col)
        cell.font = Font(bold=True)
        cell.fill = PatternFill(start_color="E7E6E6", end_color="E7E6E6", fill_type="solid")

    for detail in purchase["daily_coverage"].get("details", []):
        coverage = detail.get("coverage")
        ws.append([
            detail.get("date", ""),
            detail.get("party_name", ""),
            detail.get("amount"),
            detail.get("allocated_amount"),
            detail.get("capped_allocated"),
            f"{coverage:.1f}%" if coverage is not None else "—",
        ])

    ws.append([])
    ws.append([])

    # 金蝶明细分摊情况
    ws.append(["金蝶明细分摊情况（前100条）"])
    ws[f"A{ws.max_row}"].font = Font(bold=True, size=12)
    ws.append([])

    headers = ["单据编号", "业务日期", "供应商", "物料", "金额", "已分摊", "剩余", "超额", "跨日"]
    ws.append(headers)

    for col in range(1, len(headers) + 1):
        cell = ws.cell(ws.max_row, col)
        cell.font = Font(bold=True)
        cell.fill = PatternFill(start_color="E7E6E6", end_color="E7E6E6", fill_type="solid")

    for line in purchase["k3_allocation"].get("details", [])[:100]:
        ws.append([
            line.get("bill_no", ""),
            line.get("biz_date", ""),
            line.get("party_name", ""),
            line.get("material_name", ""),
            line.get("amount"),
            line.get("allocated"),
            line.get("remaining"),
            line.get("over_allocated"),
            "是" if line.get("is_cross_date") else "",
        ])

    # 调整列宽
    for col, width in enumerate([20, 12, 25, 35, 15, 15, 15, 15, 8], start=1):
        ws.column_dimensions[chr(64 + col)].width = width
