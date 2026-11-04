"""已探查的三类支出审批字段；报销套件按组件 ID 解析并核对表内合计。"""

import json
from decimal import Decimal, InvalidOperation

SOURCE_NAMES = ("付款申请", "员工薪资发放申请A", "日常报销单据")


def source_kind(name):
    if name == "员工薪资发放申请A":
        return "salary"
    if name == "日常报销单据":
        return "reimbursement"
    return "payment" if "付款申请" in name else None


def decode(value):
    if isinstance(value, str) and value.strip().startswith(("[", "{")):
        try:
            return json.loads(value)
        except ValueError as exc:
            raise ValueError("支出审批嵌套组件不是有效 JSON") from exc
    return value


def money(value):
    try:
        amount = Decimal(str(value).strip().replace(",", ""))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError("支出审批金额为空或无法识别，拒绝当零汇总") from exc
    if not amount.is_finite():
        raise ValueError("支出审批金额不接受 NaN / Infinity")
    return amount


def normalize_expense_form(process, values):
    form = (
        dict(values)
        if isinstance(values, dict)
        else {item["name"]: item.get("value") for item in values or [] if isinstance(item, dict) and item.get("name")}
    )
    kind = source_kind(process.name)
    if kind not in ("salary", "reimbursement"):
        return form
    if not isinstance(form.get("申请公司"), str) or not form["申请公司"].strip():
        raise ValueError("薪资/报销审批缺少申请公司，不能回退到应用公司")
    if kind == "salary":
        amount = money(form.get(process.amount_component or "付款总额"))
        form["__expense"] = {"kind": kind, "source": process.name, "amount": str(amount), "lines": []}
        return form
    # 不具名 DDBizSuite 会被普通 flatten_form 丢掉，必须从原始组件列表提取。
    suites = (
        [
            decode(item.get("value"))
            for item in values or []
            if isinstance(item, dict) and item.get("component_type", item.get("componentType")) == "DDBizSuite"
        ]
        if isinstance(values, list)
        else []
    )
    if not suites and isinstance(form.get("__expense"), dict):
        return form
    tables = [
        node
        for suite in suites
        if isinstance(suite, list)
        for node in suite
        if isinstance(node, dict)
        and node.get("componentType", node.get("componentName")) == "TableField"
        and node.get("props", {}).get("label") == "报销明细"
    ]
    if len(tables) != 1:
        raise ValueError("报销审批未找到唯一的报销明细表，拒绝按表头金额猜测")
    table = tables[0]
    fields = {item.get("props", {}).get("label"): item.get("props", {}).get("id") for item in table.get("children", [])}
    amount_id = fields.get(process.amount_component or "报销金额（元）")
    if not amount_id:
        raise ValueError("报销金额组件名与实际明细字段不一致")
    rows = decode(table.get("value"))
    if not isinstance(rows, list) or not rows:
        raise ValueError("报销明细为空，拒绝当零汇总")
    lines = []
    for index, row in enumerate(rows, 1):
        cells = {cell.get("key"): decode(cell.get("value")) for cell in row.get("rowValue", [])}
        amount = money(cells.get(amount_id))

        def value(label, cells=cells):
            return cells.get(fields.get(label), "")

        lines.append(
            {
                "line": index,
                "amount": str(amount),
                "expense_date": value("费用发生日期"),
                "reason": value("费用说明"),
                "category": value("费用类型"),
                "tax": str(money(value("税额（元）"))) if value("税额（元）") not in (None, "") else None,
            }
        )
    total = sum((Decimal(line["amount"]) for line in lines), Decimal(0))
    stats = decode(table.get("extValue", {}).get("statValue")) or []
    matches = [stat for stat in stats if stat.get("id") == amount_id]
    if len(matches) != 1 or money(matches[0].get("num")) != total:
        raise ValueError("报销明细求和与审批组件合计不一致，拒绝落库和汇总")
    posting = next(
        (node.get("value") for suite in suites for node in suite if node.get("props", {}).get("label") == "入账时间"),
        "",
    )
    form["__expense"] = {
        "kind": kind,
        "source": process.name,
        "amount": str(total),
        "lines": lines,
        "posting_time": posting,
    }
    return form
