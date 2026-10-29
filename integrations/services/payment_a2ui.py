"""付款申请 A2UI 卡片：真实数据绑定与应用机器人原生发送通道。"""

import json
from collections import defaultdict
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

from django.conf import settings

from integrations.services.a2ui_robot import DingtalkA2UIClient


STATUS_LABELS = {
    "COMPLETED": "✅ 已完成审批",
    "RUNNING": "🔄 审批中",
    "TERMINATED": "❌ 已终止",
    "NEW": "📝 新建",
}


def _money(value):
    return f"¥{value:,.2f}"


def build_payment_a2ui_messages(data, period_info, company_name, report_type="week"):
    """复用已校验的卡片布局，整树替换示例数据，避免混入演示值。"""
    template_path = Path(settings.BASE_DIR) / "docs/templates/payment_application_report.a2ui.json"
    frames = json.loads(template_path.read_text(encoding="utf-8"))
    surface_id = f"payment-report-{uuid4().hex}"
    recipients = sorted(data["by_recipient"], key=lambda row: row["amount"], reverse=True)
    total_count = data["summary"]["total_count"]
    total_amount = Decimal(str(data["summary"]["total_amount"]))
    start, end = period_info["start"].date(), period_info["end"].date()
    status_counts = defaultdict(int)
    status_amounts = defaultdict(Decimal)
    daily = {}
    day = start
    while day <= end:
        daily[day.isoformat()] = {
            "date": day.isoformat(), "label": day.strftime("%m-%d"),
            "count": 0, "amount": Decimal("0"),
        }
        day += timedelta(days=1)

    for recipient in recipients:
        for detail in recipient["details"]:
            status = detail.get("status") or "UNKNOWN"
            amount = Decimal(str(detail["amount"] or 0))
            status_counts[status] += 1
            status_amounts[status] += amount
            # create_date 在聚合层按项目时区生成；不能静默丢弃区间外的数据。
            daily[detail["create_date"]]["count"] += 1
            daily[detail["create_date"]]["amount"] += amount

    if sum(status_counts.values()) != total_count or sum(status_amounts.values()) != total_amount:
        raise ValueError("付款申请汇总与明细不一致，不能生成 A2UI 图表")

    completed_count = status_counts["COMPLETED"]
    completion_rate = Decimal(completed_count) / total_count * 100 if total_count else None
    average = total_amount / total_count if total_count else None
    top_five = recipients[:5]
    top_amount = sum((row["amount"] for row in top_five), Decimal("0"))
    top_percent = top_amount / total_amount * 100 if total_amount else None
    payees = [
        {
            "name": row["recipient"], "label": row["recipient"],
            "count": row["count"], "amount": float(row["amount"]),
        }
        for row in top_five
    ]
    if len(recipients) > 5:
        remaining = recipients[5:]
        payees.append({
            "name": f"其他 {len(remaining)} 家收款人", "label": "其他",
            "count": sum(row["count"] for row in remaining),
            "amount": float(sum((row["amount"] for row in remaining), Decimal("0"))),
        })
    top_label = f"前 {len(top_five)} 名收款人合计 {_money(top_amount)}"
    top_summary = top_label + (f"，占申请总额 {top_percent:.1f}%。" if top_percent is not None else "。")
    daily_rows = [{**row, "amount": float(row["amount"])} for row in daily.values()]
    statuses = [
        {
            "status": status,
            "label": STATUS_LABELS.get(status, f"其他状态（{status}）"),
            "count": status_counts[status],
            "amount": float(status_amounts[status]),
            "countText": f"{status_counts[status]} 笔",
            "amountText": _money(status_amounts[status]),
            "detailText": f"{status_counts[status]} 笔 · {_money(status_amounts[status])}",
        }
        for status in [*STATUS_LABELS, *sorted(set(status_counts) - set(STATUS_LABELS))]
    ]

    focus = []
    if status_counts["RUNNING"]:
        focus.append({
            "title": f"审批中：{status_counts['RUNNING']} 笔 · {_money(status_amounts['RUNNING'])}",
            "desc": "请结合审批进度核对后续付款计划；审批中金额不等于已付款金额。",
        })
    if total_amount > 0:
        peak = max(daily.values(), key=lambda row: row["amount"])
        focus.extend([
            {
                "title": f"{peak['label']} 申请金额最高",
                "desc": f"当日 {peak['count']} 笔，合计 {_money(peak['amount'])}，占本期 {peak['amount'] / total_amount * 100:.1f}%。",
            },
            {"title": "收款人金额集中度", "desc": top_summary},
        ])
    unknown = next((row for row in recipients if row["recipient"] == "未知收款人"), None)
    if unknown:
        focus.append({
            "title": f"收款人待核对：{unknown['count']} 笔",
            "desc": f"合计 {_money(unknown['amount'])}；请核对审批表单中的收款人字段。",
        })

    model = {
        "companyName": company_name,
        "reportTitle": f"付款申请{dict(day='日报', week='周报', month='月报')[report_type]}",
        "period": period_info["label"],
        "periodLabel": f"{period_info['label']} · {start:%Y.%m.%d}—{end:%Y.%m.%d}",
        "dataLabel": "实际申请数据",
        "reportMeta": {
            "dataMode": "live", "currency": "CNY", "amountUnit": "元", "chartAmountUnit": "万元",
            "periodStart": start.isoformat(), "periodEnd": end.isoformat(),
        },
        "summary": {
            "totalAmount": float(total_amount), "totalAmountText": _money(total_amount),
            "totalCount": total_count, "totalCountText": f"{total_count} 笔",
            "recipientCount": len(recipients), "recipientCountText": f"{len(recipients)} 家",
            "averageAmount": float(average) if average is not None else None,
            "averageAmountText": _money(average) if average is not None else "—",
            "completedCount": completed_count,
            "completedAmount": float(status_amounts["COMPLETED"]),
            "completedAmountText": _money(status_amounts["COMPLETED"]),
            "completionRate": float(completion_rate) if completion_rate is not None else None,
            "completionRateText": f"{completion_rate:.1f}%" if completion_rate is not None else "—",
            "runningCount": status_counts["RUNNING"],
            "runningAmount": float(status_amounts["RUNNING"]),
            "runningAmountText": _money(status_amounts["RUNNING"]),
            "terminatedCount": status_counts["TERMINATED"],
            "terminatedAmount": float(status_amounts["TERMINATED"]),
            "amountChangeText": "按申请创建日期统计 · 人民币",
            "top5Amount": float(top_amount),
            "top5Percent": float(top_percent) if top_percent is not None else None,
            "top5SummaryText": top_summary if total_count else "本期暂无收款人申请数据。",
        },
        "statusBreakdown": statuses,
        "dailyApplications": daily_rows,
        "payeeApplications": payees,
        "charts": {
            "dailyAmount": {
                "type": "lineChart",
                "data": [
                    {"x": row["label"], "y": float(row["amount"] / Decimal("10000"))}
                    for row in daily.values()
                ] if total_count else [],
            },
            "payeeAmount": {
                "type": "histogram",
                "data": [
                    {"x": row["label"], "y": float(Decimal(str(row["amount"])) / Decimal("10000"))}
                    for row in payees
                ],
            },
        },
        "focusItems": focus,
        "chartUnitNote": "图表金额单位：万元；卡片明细金额单位：人民币元。",
        "scopeNote": "口径：按付款申请创建日期汇总，包含各审批状态。审批完成不代表实际付款。",
        "demoNote": "数据来源：已同步的钉钉付款申请。",
    }
    for frame in frames:
        operation = next(key for key in frame if key != "version")
        frame[operation]["surfaceId"] = surface_id
        if operation == "updateDataModel":
            frame[operation]["value"] = model
        elif operation == "updateComponents":
            heading = next(c for c in frame[operation]["components"] if c["id"] == "focus-heading")
            heading["text"] = dict(day="当日关注", week="本周关注", month="本月关注")[report_type]
    return frames


