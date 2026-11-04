"""周/月度支出申请汇总：复用审批存储与报表快照，显式列出覆盖流程。"""

import hashlib
from decimal import Decimal

from django.db.models import Q

from integrations.models import DingtalkProcessConfig
from integrations.services.payment_report import analyze_payment_applications
from integrations.services.expense_fields import source_kind


def expense_processes(app):
    configs = list(
        DingtalkProcessConfig.objects.filter(app=app, is_active=True)
        .filter(Q(name__icontains="付款申请") | Q(name__in=["员工薪资发放申请A", "日常报销单据"]))
        .order_by("pk")
    )
    if len({config.process_code for config in configs}) != len(configs):
        raise ValueError("存在重复的支出审批流程配置")
    return configs


def expense_snapshot_key(configs):
    codes = sorted(config.process_code for config in configs)
    return codes[0] if len(codes) == 1 else "expense:" + hashlib.sha256("|".join(codes).encode()).hexdigest()[:40]


def analyze_expenses(company, start, end, configs):
    if not configs:
        raise ValueError("未配置启用的支出审批流程")
    data = analyze_payment_applications(company, start, end, [config.process_code for config in configs])
    source_rows = []
    details = [detail for group in data.get("by_recipient", []) for detail in group.get("details", [])]
    for config in configs:
        rows = [row for row in details if row.get("source") == config.name]
        source_rows.append(
            {
                "name": config.name,
                "kind": source_kind(config.name),
                "process_code": config.process_code,
                "count": len(rows),
                "amount": sum((Decimal(str(row["amount"])) for row in rows), Decimal(0)),
            }
        )
    if sum(row["count"] for row in source_rows) != data["summary"]["total_count"]:
        raise ValueError("支出来源汇总与明细笔数不一致")
    data["sources"] = source_rows
    data["summary"]["approved_amount"] = sum(
        (
            Decimal(str(row["amount"]))
            for row in details
            if row.get("status") == "COMPLETED" and row.get("result", "").lower() == "agree"
        ),
        Decimal(0),
    )
    data["summary"]["rejected_amount"] = sum(
        (
            Decimal(str(row["amount"]))
            for row in details
            if row.get("status") == "COMPLETED" and row.get("result", "").lower() == "refuse"
        ),
        Decimal(0),
    )
    data["summary"]["paid_amount"] = None
    return data
