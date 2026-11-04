"""周/月度支出报表的统一对外名称和日期降序明细。"""

from datetime import date, datetime

REPORT_TITLES = {"day": "付款申请日报", "week": "周度支出报表", "month": "月度支出报表"}


def expense_report_title(report_type):
    return REPORT_TITLES[report_type]


def expense_card_title(report_type):
    """消息卡片名称；在线报表和附件继续使用原报表名称。"""
    return {"day": REPORT_TITLES["day"], "week": "支出项目周报", "month": "支出项目月报"}[report_type]


def sorted_expense_details(data):
    rows = [
        dict(detail, recipient=group.get("recipient", ""))
        for group in data.get("by_recipient", [])
        for detail in group.get("details", [])
    ]

    def sort_key(row):
        value = row.get("create_time") or row.get("create_date") or ""
        if isinstance(value, (date, datetime)):
            value = value.isoformat()
        return str(value).replace("/", "-"), str(row.get("process_instance_id", ""))

    return sorted(rows, key=sort_key, reverse=True)


def source_description(data):
    sources = data.get("sources") or [{"name": "付款申请"}]
    return "、".join(source.get("name", "") for source in sources)


def expense_scope_note(data=None):
    return (
        "口径：按申请发起日期汇总支出申请，包含各审批状态；审批完成不代表实际已支付。当前覆盖："
        + source_description(data or {})
        + "。"
    )
