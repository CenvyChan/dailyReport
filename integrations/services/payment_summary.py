"""付款申请在线报表的页面模型：指标、构成、趋势、收款人与明细。

在线页与钉钉 A2UI 卡片读同一份快照数据（analyze_payment_applications 的输出）。
金额在快照里以字符串保存，这里统一转 Decimal 再展示，避免浮点误差；
指标口径与卡片保持一一对应，便于群里点开链接后核对同一组数字。
"""

from integrations.services.expense_reporting import expense_report_title, expense_scope_note, sorted_expense_details, source_description

import math
from datetime import timedelta
from decimal import Decimal, InvalidOperation

STATUS_TEXT = {
    "COMPLETED": "已完成",
    "RUNNING": "审批中",
    "TERMINATED": "已终止",
    "NEW": "新建",
}
STATUS_COLORS = {
    "COMPLETED": "#059669",
    "RUNNING": "#2563eb",
    "TERMINATED": "#e11d48",
    "NEW": "#94a3b8",
}
UNKNOWN_STATUS_COLOR = "#64748b"

# 与 operations_chart.html 的 viewBox(0 0 700 220) 对齐，两个报表图形一致。
CHART_LEFT = 52
CHART_RIGHT = 676
CHART_TOP = 28
CHART_BOTTOM = 168

SCOPE_NOTE = "口径：按付款申请创建日期汇总，包含各审批状态。审批完成不代表实际付款。"
UNIT_NOTE = "图表金额单位：万元；明细金额单位：人民币元。"


def _amount(value):
    """快照里的金额是字符串；脏值按 0 处理，页面不能因为一条坏数据整页 500。"""
    try:
        return Decimal(str(value)) if value not in (None, "") else Decimal("0")
    except (InvalidOperation, ValueError):
        return Decimal("0")


def _money(value):
    return f"¥{_amount(value):,.2f}"


def _wan(value):
    # 不逐点四舍五入：合计口径必须与卡片图表一致，展示时才交给模板处理。
    return float(_amount(value) / Decimal("10000"))


def _wan_text(value):
    """万元展示：小额申请也能看出差异，同时避免 0.012345 这种长尾。"""
    text = f"{_wan(value):,.4f}".rstrip("0").rstrip(".")
    return text or "0"


def _percent(part, total):
    if not total:
        return None
    return round(float(part / total * 100), 1)


def _daily_rows(details, start, end):
    """按自然日铺满整个周期：没有申请的日期也要出现在趋势图横轴上。"""
    rows = {}
    day = start
    while day <= end:
        rows[day.isoformat()] = {
            "date": day.isoformat(),
            "label": day.strftime("%m-%d"),
            "count": 0,
            "amount": Decimal("0"),
        }
        day += timedelta(days=1)
    for detail in details:
        row = rows.get(detail.get("create_date"))
        if row is None:
            # analyze 已按创建时间过滤；区间外日期不静默混入图表。
            continue
        row["count"] += 1
        row["amount"] += _amount(detail.get("amount"))
    return list(rows.values())


def _line_chart(rows, *, label="申请金额", color="#2563eb"):
    """单序列折线图，结构复用 operations_chart.html 的渲染约定。"""
    if not rows:
        return {"has_data": False}
    values = [row["amount"] for row in rows]
    low = min([Decimal("0")] + values)
    high = max([Decimal("0")] + values)
    span = high - low or Decimal("1")

    def y(value):
        return round(
            CHART_TOP + float((high - value) / span) * (CHART_BOTTOM - CHART_TOP), 2
        )

    def x(index):
        return round(
            CHART_LEFT + index * (CHART_RIGHT - CHART_LEFT) / max(len(rows) - 1, 1),
            2,
        )

    points_list = [
        {
            "x": x(index),
            "y": y(row["amount"]),
            "date": row["date"],
            "value": _wan(row["amount"]),
            "value_text": _wan_text(row["amount"]),
            "count": row["count"],
        }
        for index, row in enumerate(rows)
    ]

    tick_count = 5
    tick_span_wan = float((high - low) / Decimal("10000")) / (tick_count - 1)
    if tick_span_wan >= 10:
        decimals = 0
    elif tick_span_wan >= 1:
        decimals = 1
    else:
        decimals = max(1, int(-math.floor(math.log10(max(tick_span_wan, 1e-9)))))
    y_ticks = []
    for index in range(tick_count):
        value = low + (high - low) * Decimal(index) / Decimal(tick_count - 1)
        y_ticks.append(
            {"y": y(value), "label": f"{float(value / Decimal('10000')):,.{decimals}f}"}
        )

    x_tick_count = min(6, len(rows))
    x_labels = []
    for index in range(x_tick_count):
        row_index = round(index * (len(rows) - 1) / max(x_tick_count - 1, 1))
        x_labels.append({"x": x(row_index), "label": rows[row_index]["label"]})

    return {
        "series": [
            {
                "name": "amount",
                "label": label,
                "color": color,
                "points": " ".join(
                    f"{point['x']},{point['y']}" for point in points_list
                ),
                "points_list": points_list,
            }
        ],
        "y_ticks": y_ticks,
        "x_labels": x_labels,
        "zero_y": y(Decimal("0")),
        "has_negative": low < 0,
        "has_data": True,
        "high": float(high / Decimal("10000")),
        "low": float(low / Decimal("10000")),
    }


def _status_rows(status_counts, status_amounts, total_amount, total_count):
    """状态构成 + 一行合计。

    「新建」是钉钉的草稿瞬时态，同步按时间窗批量拉取时永远采不到，恒为 0；
    与其留一行无信息量的 0，不如用合计行收口。若将来真的出现 NEW，仍会列出。
    """
    order = [
        status
        for status in ("COMPLETED", "RUNNING", "TERMINATED", "NEW")
        if status != "NEW" or status_counts.get("NEW")
    ]
    rows = []
    for status in [*order, *sorted(set(status_counts) - set(STATUS_TEXT))]:
        amount = status_amounts.get(status, Decimal("0"))
        rows.append(
            {
                "status": status,
                "label": STATUS_TEXT.get(status, f"其他（{status}）"),
                "count": status_counts.get(status, 0),
                "amount": amount,
                "amount_text": _money(amount),
                "percent": _percent(amount, total_amount),
                "color": STATUS_COLORS.get(status, UNKNOWN_STATUS_COLOR),
            }
        )
    rows.append(
        {
            "status": "TOTAL",
            "label": "发起的流程数",
            "count": total_count,
            "amount": total_amount,
            "amount_text": _money(total_amount),
            "percent": 100.0 if total_amount > 0 else None,
            "color": "#334155",
            "is_total": True,
        }
    )
    return rows


def _payee_rows(recipients, total_amount):
    """前 5 名收款人 + 其他汇总，宽度按最大金额归一（至少保留 1 位小数）。"""
    rows = [
        {
            "name": row.get("recipient") or "未知收款人",
            "count": int(row.get("count") or 0),
            "amount": _amount(row.get("amount")),
        }
        for row in recipients[:5]
    ]
    if len(recipients) > 5:
        remaining = recipients[5:]
        rows.append(
            {
                "name": f"其他 {len(remaining)} 家",
                "count": sum(int(row.get("count") or 0) for row in remaining),
                "amount": sum(
                    (_amount(row.get("amount")) for row in remaining), Decimal("0")
                ),
            }
        )
    largest = max((row["amount"] for row in rows), default=Decimal("0")) or Decimal("1")
    for row in rows:
        row["width"] = round(float(row["amount"] / largest) * 100, 1)
        row["amount_text"] = _money(row["amount"])
        row["amount_wan"] = _wan(row["amount"])
        row["amount_wan_text"] = _wan_text(row["amount"])
        row["percent"] = _percent(row["amount"], total_amount)
    return rows


def _focus_items(status_counts, status_amounts, total_amount, daily, recipients):
    focus = []
    running_count = status_counts.get("RUNNING", 0)
    if running_count:
        running_amount = status_amounts.get("RUNNING", Decimal("0"))
        share = _percent(running_amount, total_amount)
        focus.append(
            {
                "title": f"审批中：{running_count} 笔 · {_money(running_amount)}",
                "desc": "请结合审批进度核对后续付款计划"
                + (f"，占申请总额 {share:.1f}%" if share is not None else "")
                + "；审批中金额不等于已付款金额。",
            }
        )
    if total_amount > 0 and daily:
        peak = max(daily, key=lambda row: row["amount"])
        focus.append(
            {
                "title": f"{peak['label']} 申请金额最高",
                "desc": f"当日 {peak['count']} 笔，合计 {_money(peak['amount'])}，"
                f"占本期 {_percent(peak['amount'], total_amount):.1f}%。",
            }
        )
    if total_amount > 0 and recipients:
        top_rows = recipients[:5]
        top_amount = sum((_amount(row.get("amount")) for row in top_rows), Decimal("0"))
        remaining = len(recipients) - len(top_rows)
        desc = f"占申请总额 {_percent(top_amount, total_amount):.1f}%"
        if remaining > 0:
            desc += (
                f"，其余 {remaining} 家合计 {_money(total_amount - top_amount)}"
            )
        focus.append(
            {
                "title": f"前 {len(top_rows)} 名收款人合计 {_money(top_amount)}",
                "desc": desc + "。",
            }
        )
    unknown = next(
        (row for row in recipients if row.get("recipient") == "未知收款人"), None
    )
    if unknown:
        focus.append(
            {
                "title": f"收款人待核对：{unknown.get('count')} 笔",
                "desc": f"合计 {_money(unknown.get('amount'))}；"
                "请核对审批表单中的收款人字段。",
            }
        )
    return focus


def _detail_groups(recipients):
    groups = []
    for row in recipients:
        details = []
        for detail in row.get("details") or []:
            status = detail.get("status") or ""
            details.append(
                {
                    "create_date": detail.get("create_date") or "",
                    "amount_text": _money(detail.get("amount")),
                    "reason": detail.get("reason") or "",
                    "expected_date": detail.get("expected_date") or "",
                    "status_text": STATUS_TEXT.get(status, status or "未知"),
                    "originator": detail.get("originator") or "",
                    "title": detail.get("title") or "",
                }
            )
        # 明细按申请日期倒序：先看最近一笔，和用户翻群的顺序一致。
        details.sort(key=lambda detail: detail["create_date"], reverse=True)
        groups.append(
            {
                "recipient": row.get("recipient") or "未知收款人",
                "count": int(row.get("count") or 0),
                "amount_text": _money(row.get("amount")),
                "details": details,
            }
        )
    return groups


def payment_context(snapshot):
    """把快照数据整理成在线页 / PDF 模板所需的全部上下文。"""
    data = snapshot.data or {}
    summary = data.get("summary") or {}
    recipients = list(data.get("by_recipient") or [])
    total_count = int(summary.get("total_count") or 0)
    total_amount = _amount(summary.get("total_amount"))
    details = [
        detail for row in recipients for detail in (row.get("details") or [])
    ]

    status_counts = {}
    status_amounts = {}
    for detail in details:
        status = detail.get("status") or "UNKNOWN"
        status_counts[status] = status_counts.get(status, 0) + 1
        status_amounts[status] = status_amounts.get(
            status, Decimal("0")
        ) + _amount(detail.get("amount"))

    warning = ""
    if total_count != len(details) or total_amount != sum(
        status_amounts.values(), Decimal("0")
    ):
        warning = "快照汇总与明细不一致，请用 --force-snapshot 重建快照后再对外发送。"

    completed_count = status_counts.get("COMPLETED", 0)
    completion_rate = (
        f"{completed_count / total_count * 100:.1f}%" if total_count else "—"
    )
    average = _money(total_amount / total_count) if total_count else "—"
    daily = _daily_rows(details, snapshot.period_start, snapshot.period_end)
    metrics = [
        {
            "label": "申请总额",
            "value": _money(total_amount),
            "hint": f"共 {total_count} 笔",
        },
        {
            "label": "审批中金额",
            "value": _money(status_amounts.get("RUNNING", 0)),
            "hint": f"{status_counts.get('RUNNING', 0)} 笔",
        },
        {
            "label": "已完成金额",
            "value": _money(status_amounts.get("COMPLETED", 0)),
            "hint": f"{completed_count} 笔 · 完成率 {completion_rate}",
        },
        {
            "label": "已终止金额",
            "value": _money(status_amounts.get("TERMINATED", 0)),
            "hint": f"{status_counts.get('TERMINATED', 0)} 笔",
        },
        {
            "label": "收款人数量",
            "value": f"{len(recipients)} 家",
            "hint": "按申请金额倒序",
        },
        {
            "label": "平均单笔",
            "value": average,
            "hint": "总金额 ÷ 申请笔数",
        },
    ]
    return {
        "snapshot": snapshot,
        "report": data,
        "company_name": data.get("company_name") or snapshot.company.name,
        "report_title": expense_report_title(snapshot.report_type),
        "period_label": snapshot.period_label,
        "period_display": f"{snapshot.period_start:%Y.%m.%d}—{snapshot.period_end:%Y.%m.%d}",
        "total_count": total_count,
        "total_amount_text": _money(total_amount),
        "metrics": metrics,
        "status_rows": _status_rows(
            status_counts, status_amounts, total_amount, total_count
        ),
        # 与卡片一致：本期没有申请时不画一条零值折线，直接提示暂无数据。
        "daily_chart": _line_chart(daily) if total_count else {"has_data": False},
        "payee_rows": _payee_rows(recipients, total_amount),
        "focus_items": _focus_items(
            status_counts, status_amounts, total_amount, daily, recipients
        ),
        "detail_groups": _detail_groups(recipients),
        "details": [dict(row, amount_text=_money(row.get("amount")), status_text=STATUS_TEXT.get(row.get("status"), row.get("status") or "未知")) for row in sorted_expense_details(data)],
        "source_note": source_description(data),
        "source_rows": [dict(row, amount_text=_money(row.get("amount")), percent=_percent(_amount(row.get("amount", 0)), total_amount)) for row in data.get("sources", [])],
        "warning": warning,
        "scope_note": expense_scope_note(data),
        "unit_note": UNIT_NOTE,
    }
