"""六类取数编排与字段归一化，不在这里计算经营指标。"""

import re
from datetime import timedelta

from . import calculators
from .common import number, parse_date, period_window, reference_date
from .fields import (
    INVENTORYREPORTNORMALIZER,
    PRODUCTIONNORMALIZER,
    PURCHASEENTRYNORMALIZER,
    PURCHASEREPORTNORMALIZER,
    RECEIVABLENORMALIZER,
    SALESREPORTNORMALIZER,
    SUBCONTRACTNORMALIZER,
)


class Normalizer:
    def __init__(self):
        self.invalid_dates = []

    def rows(self, raw_rows, schema, *, header=(), detail=None):
        result, previous = [], {}
        for raw in raw_rows:
            fill = bool(header and not str(raw[1] if raw[1] is not None else "").strip())
            if detail is not None:
                fill = fill and any(str(raw[index] if raw[index] is not None else "").strip() for index in detail)
            if header == (0, 1, 2, 3, 4, 5):
                fill = fill and number(raw[9]) != 0
            data = list(raw)
            for index in header:
                value = str(data[index] if data[index] is not None else "").strip()
                if value:
                    previous[index] = value
                elif fill:
                    data[index] = previous.get(index, "")
            row = {}
            for key, index, kind in schema:
                value = data[index]
                if kind == "n":
                    row[key] = number(value)
                elif kind == "d":
                    row[key] = parse_date(value)
                    if value and row[key] is None:
                        self.invalid_dates.append(str(value)[:40])
                else:
                    row[key] = str(value if value is not None else "").strip()
            result.append(row)
        return result


def schema(text):
    return [
        (part.split(":")[0], index, part.split(":")[1] if ":" in part else "s")
        for index, part in enumerate(text.split(","))
    ]


PURCHASE_SCHEMA = [
    ("org", 0, "s"),
    ("bill", 1, "s"),
    ("date", 2, "d"),
    ("supplier", 3, "s"),
    ("material", 4, "s"),
    ("due", 5, "d"),
    ("currency", 6, "s"),
    ("qty", 7, "n"),
    ("amount", 8, "n"),
    ("received", 9, "n"),
    ("stockin", 11, "n"),
    ("payable", 16, "n"),
    ("settled", 22, "n"),
]
INVENTORY_SCHEMA = [
    ("code", 0, "s"),
    ("name", 1, "s"),
    ("group", 2, "s"),
    ("warehouse", 3, "s"),
    ("init_qty", 4, "n"),
    ("init_amount", 6, "n"),
    ("in_qty", 7, "n"),
    ("in_amount", 9, "n"),
    ("out_qty", 10, "n"),
    ("out_amount", 12, "n"),
    ("end_qty", 13, "n"),
    ("end_amount", 15, "n"),
]
SALES_SCHEMA = [
    ("org", 0, "s"),
    ("bill", 1, "s"),
    ("bill_type", 2, "s"),
    ("date", 3, "d"),
    ("salesperson", 4, "s"),
    ("customer", 5, "s"),
    ("material", 6, "s"),
    ("out", 9, "n"),
    ("receivable", 12, "n"),
    ("settled", 16, "n"),
]


def bill_months(query, config, prefix, windows, org, normalizer, row_schema):
    rows = []
    for start, end in windows:
        rows.extend(
            query.bill(
                config[prefix + "FORM_ID"],
                config[prefix + "FIELD_KEYS"],
                config[prefix + "FILTER_TEMPLATE"] % (start, end, org),
            )
        )
    return normalizer.rows(rows, row_schema)


def analyze(kind, query, org, period, months=12):
    windows, normalizer = period_window(period, months), Normalizer()
    start, end, ref = windows[0][0], windows[-1][1], reference_date(period)
    if kind == "purchase":
        config = PURCHASEREPORTNORMALIZER
        model = {
            "FPurchaseOrgIdList": org["id"],
            "FOrderStartDate": str(start),
            "FOrderEndDate": str(end),
            "FBeginBillNumber": "",
            "FEndBillNumber": "",
            "FBusinessType": "",
            "FDocumentStatus": "C",
            "FLineStatus": "A",
        }
        for key in (
            "FBeginSupplierId",
            "FEndSupplierId",
            "FBeginMaterialId",
            "FEndMaterialId",
            "FBeginPurchaser",
            "FEndFPurchaser",
        ):
            model[key] = {"FNumber": ""}
        rows = normalizer.rows(
            query.report(config["FORM_ID"], config["FIELD_KEYS"], model),
            PURCHASE_SCHEMA,
            header=(0, 1, 2, 3),
            detail=(4, 7, 8, 9, 11, 15, 19, 22),
        )
        for row in rows:
            row["unsettled"] = max(row["payable"] - row["settled"], number(0))
        entry_config, raw = PURCHASEENTRYNORMALIZER, []
        for first, last in windows:
            raw.extend(
                query.bill(
                    entry_config["FORM_ID"],
                    entry_config["FIELD_KEYS"],
                    entry_config["FILTER_TEMPLATE"] % (first, last + timedelta(days=1), org["number"]),
                )
            )
        entries = normalizer.rows(raw, schema("bill,entry,date:d,supplier,material,qty:n,remaining:n,due:d"))
        result = calculators.purchase(rows, entries, ref)
    elif kind == "receivable":
        if not re.fullmatch(r"\d{3,}", org["number"]):
            raise ValueError("应收销售组织编码须为至少三位数字，保留前导零，例如 001")
        config = RECEIVABLENORMALIZER
        filters = config["FILTER_TEMPLATE"] % (start, end, org["number"])
        heads = normalizer.rows(
            query.bill(config["FORM_ID"], config["HEAD_FIELD_KEYS"], filters), schema("bill,date:d,customer,amount:n")
        )
        plans = normalizer.rows(
            query.bill(config["FORM_ID"], config["PLAN_FIELD_KEYS"], filters), schema("bill,settled:n,unsettled:n")
        )
        seen, unique_heads = set(), []
        for row in heads:
            if row["bill"] and row["bill"] not in seen:
                unique_heads.append(row)
                seen.add(row["bill"])
        seen, unique_plans = set(), []
        for row in plans:
            key = (row["bill"], row["settled"], row["unsettled"])
            if row["bill"] and key not in seen:
                unique_plans.append(row)
                seen.add(key)
        result = calculators.receivable(unique_heads, unique_plans)
    elif kind == "inventory":
        config, rows = INVENTORYREPORTNORMALIZER, []
        for first, _last in windows:
            model = {
                "FACCTGSYSTEMID": {"FNumber": config["ACCT_SYSTEM_NUMBER"]},
                "FACCTGORGID": {"FNumber": org["number"]},
                "FACCTPOLICYID": {"FNumber": config["ACCT_POLICY_NUMBER"]},
                "FYear": str(first.year),
                "FPeriod": str(first.month),
                "FENDYEAR": str(first.year),
                "FEndPeriod": str(first.month),
                "FCOMBOTotalType": "不汇总",
                "FDimType": "FMATERIALID,FSTOCKID",
                "FIsDisplayPeriod": True,
            }
            current = normalizer.rows(query.report(config["FORM_ID"], config["FIELD_KEYS"], model), INVENTORY_SCHEMA)
            rows.extend(dict(row, period=first.strftime("%Y-%m")) for row in current if row["code"])
        result = calculators.inventory(rows)
    elif kind == "sales":
        config = SALESREPORTNORMALIZER
        model = {
            "FSaleOrgId": org["id"],
            "FMoneyType": {"FNumber": ""},
            "FStartDate": str(start),
            "FEndDate": str(end),
            "FFormStatus": "C",
            "FIsIncludeSerMat": "false",
            "FSuite": "",
            "FSettleOrgList": "",
        }
        for key in ("FCustomerFrom", "FCustomerTo", "FMaterialFrom", "FMaterialTo"):
            model[key] = {"FNumber": ""}
        for key in ("FSaleDeptFrom", "FSaleDeptTo"):
            model[key] = {"FNUMBER": ""}
        rows = normalizer.rows(
            query.report(config["FORM_ID"], config["FIELD_KEYS"], model), SALES_SCHEMA, header=(0, 1, 2, 3, 4, 5)
        )
        result = calculators.sales([dict(row, unsettled=row["receivable"] - row["settled"]) for row in rows])
    elif kind == "production":
        config = PRODUCTIONNORMALIZER
        orders = bill_months(
            query,
            config,
            "ORDER_",
            windows,
            org["number"],
            normalizer,
            schema(
                "bill,entry,date:d,status,bill_type,material,workshop,qty:n,stockin:n,remaining:n,plan_start:d,due:d,start:d,finish:d"
            ),
        )
        reports = bill_months(
            query,
            config,
            "REPORT_",
            windows,
            org["number"],
            normalizer,
            schema("bill,date:d,order,order_entry,material,inspected:n,qualified:n,failed:n,scrap:n,rework:n"),
        )
        result = calculators.production(orders, reports, ref)
    elif kind == "subcontract":
        config = SUBCONTRACTNORMALIZER
        orders = bill_months(
            query,
            config,
            "ORDER_",
            windows,
            org["number"],
            normalizer,
            schema(
                "bill,entry,date:d,status,bill_type,supplier,material,qty:n,stockin:n,remaining:n,plan_start:d,due:d,finish:d"
            ),
        )
        picks = bill_months(
            query,
            config,
            "PICK_",
            windows,
            org["number"],
            normalizer,
            schema("bill,entry,date:d,supplier,material,parent,order,app_qty:n,actual_qty:n,return_qty:n"),
        )
        wips = normalizer.rows(
            query.bill(config["WIP_FORM_ID"], config["WIP_FIELD_KEYS"], config["WIP_FILTER_TEMPLATE"] % org["number"]),
            schema(
                "bill,entry,supplier,parent,material,order,must:n,picked:n,consumed:n,defect_return:n,good_return:n,wip:n,not_picked:n"
            ),
        )
        result = calculators.subcontract(orders, picks, wips, ref)
    else:
        raise ValueError("未知的经营分析种类")
    result["window"] = f"{start} ~ {end}"
    result["reference_date"] = str(ref)
    if normalizer.invalid_dates:
        result["notes"].append(
            f"日期解析失败 {len(normalizer.invalid_dates)} 项（示例：{', '.join(normalizer.invalid_dates[:3])}），保留未识别，不伪造日期。"
        )
    result["notes"].append("金额保持 ERP 原报表字段口径；未统一税口径或币种，不应跨币种直接对账。")
    return result
