"""六类经营分析的纯计算。取数与呈现分离，口径来自移植包 Calculator。"""

from .common import ZERO, cards, count_distinct, groups, month, number, rate, report, rounded, table, total


def purchase(rows, entries, reference):
    rows = [dict(row, unreceived=max(number(row["qty"]) - number(row["received"]), ZERO)) for row in rows]
    overdue = sorted(
        [
            dict(row, overdue_days=(reference - row["due"]).days)
            for row in rows
            if row["due"] and row["due"] < reference and row["unreceived"] > 0
        ],
        key=lambda row: (row["overdue_days"], row["unreceived"]),
        reverse=True,
    )
    summary = {
        key: total(rows, key) for key in ("qty", "received", "stockin", "amount", "payable", "settled", "unsettled")
    }
    summary.update(
        line_count=len(rows),
        order_count=count_distinct(rows, "bill"),
        supplier_count=count_distinct(rows, "supplier"),
        material_count=count_distinct(rows, "material"),
        receive_rate=rate(summary["received"], summary["qty"], undefined=ZERO),
        stockin_rate=rate(summary["stockin"], summary["qty"], undefined=ZERO),
        settlement_rate=rate(summary["settled"], summary["payable"], undefined=ZERO),
        unsettled_rate=rate(summary["unsettled"], summary["payable"], undefined=ZERO),
        overdue_count=len(overdue),
        overdue_qty=total(overdue, "unreceived"),
    )
    monthly = []
    for label, items in sorted(groups([dict(row, month=month(row["date"])) for row in rows], "month").items()):
        item = {key: total(items, key) for key in ("amount", "payable", "settled", "unsettled", "qty", "received")}
        monthly.append(dict(item, month=label, settlement_rate=rate(item["settled"], item["payable"], undefined=ZERO)))
    rankings = {}
    for key in ("supplier", "material", "org"):
        ranking = []
        for label, items in groups(rows, key).items():
            item = {
                field: total(items, field)
                for field in ("qty", "received", "stockin", "amount", "payable", "settled", "unsettled", "unreceived")
            }
            ranking.append(
                dict(
                    item,
                    name=label,
                    order_count=count_distinct(items, "bill"),
                    line_count=len(items),
                    unsettled_rate=rate(item["unsettled"], item["payable"], undefined=ZERO),
                    receive_rate=rate(item["received"], item["qty"], undefined=ZERO),
                )
            )
        rankings[key] = sorted(ranking, key=lambda item: item["unsettled"], reverse=True)[:50]
    delivery = {
        "entry_count": len(entries),
        "exact_count": sum(row["remaining"] == 0 for row in entries),
        "short_count": sum(row["remaining"] > 0 for row in entries),
        "over_count": sum(row["remaining"] < 0 for row in entries),
        "short_qty": sum((row["remaining"] for row in entries if row["remaining"] > 0), ZERO),
        "over_qty": -sum((row["remaining"] for row in entries if row["remaining"] < 0), ZERO),
    }
    for key in ("exact", "short", "over"):
        delivery[key + "_rate"] = rate(delivery[key + "_count"], len(entries), undefined=ZERO)
    short = sorted([row for row in entries if row["remaining"] > 0], key=lambda row: row["remaining"], reverse=True)
    scope = rankings["supplier"]
    concentration = {
        "supplier_count": len(scope),
        "amount": total(scope, "amount"),
        "top5_share": rate(total(scope[:5], "amount"), total(scope, "amount"), undefined=ZERO),
        "top10_share": rate(total(scope[:10], "amount"), total(scope, "amount"), undefined=ZERO),
    }
    columns = [
        ("name", "名称"),
        ("order_count", "订单数"),
        ("amount", "订单金额"),
        ("payable", "应付金额"),
        ("settled", "已结算"),
        ("unsettled", "未结算"),
        ("unreceived", "未收数量"),
        ("unsettled_rate", "未结算率 %"),
    ]
    sections = [
        table(
            "月度采购与结算趋势",
            monthly,
            [
                ("month", "月份"),
                ("amount", "订单金额"),
                ("payable", "应付金额"),
                ("settled", "已结算"),
                ("unsettled", "未结算"),
                ("settlement_rate", "结算率 %"),
            ],
        ),
        *[
            table(title, rankings[key], columns)
            for key, title in (
                ("supplier", "供应商未结算排行 TOP 50"),
                ("material", "物料未结算排行 TOP 50"),
                ("org", "采购组织排行"),
            )
        ],
        table(
            "逾期未收清单 TOP 50",
            overdue,
            [
                ("bill", "订单号"),
                ("date", "订单日期"),
                ("supplier", "供应商"),
                ("material", "物料"),
                ("due", "交货日期"),
                ("unreceived", "未收数量"),
                ("unsettled", "未结算金额"),
            ],
            50,
        ),
        table(
            "订单分录交付分布",
            [
                {
                    "name": label,
                    "count": delivery[key + "_count"],
                    "qty": delivery.get(key + "_qty", ZERO),
                    "ratio": delivery[key + "_rate"],
                }
                for key, label in (("exact", "已交齐"), ("short", "欠交"), ("over", "超交"))
            ],
            [("name", "状态"), ("count", "分录数"), ("qty", "差量"), ("ratio", "分录占比 %")],
        ),
        table(
            "欠交分录 TOP 50（独立单据口径）",
            short,
            [
                ("bill", "订单号"),
                ("entry", "分录ID"),
                ("date", "订单日期"),
                ("supplier", "供应商"),
                ("material", "物料"),
                ("qty", "订购数量"),
                ("remaining", "欠交数量"),
                ("due", "交货日期"),
            ],
            50,
        ),
        table(
            "供应商集中度（未结算排行 TOP 50 样本）",
            [concentration],
            [
                ("supplier_count", "样本供应商数"),
                ("amount", "样本订单金额"),
                ("top5_share", "前5家金额占比 %"),
                ("top10_share", "前10家金额占比 %"),
            ],
        ),
    ]
    return report(
        {
            "summary": summary,
            "monthly": monthly,
            "rankings": rankings,
            "delivery": delivery,
            "overdue": overdue,
            "short_delivery": short,
            "concentration": concentration,
        },
        cards(
            summary,
            [
                ("amount", "订单金额", ""),
                ("payable", "应付金额", ""),
                ("unsettled", "未结算金额", ""),
                ("settlement_rate", "结算率", "%"),
                ("order_count", "订单数", ""),
                ("overdue_count", "逾期未收行数", ""),
            ],
        ),
        sections,
        [
            "金额与结算来自采购报表；交付分布来自采购订单分录，两侧不做行级匹配。",
            "报表行数不是订单分录数；收料率可能超过 100%。未结算金额逐行 max(应付−已结算, 0)。",
            "供应商集中度沿用原包未结算排行 TOP 50 样本，不代表全体供应商集中度。",
        ],
    )


def receivable(heads, plans):
    plan_groups = groups(plans, "bill")
    rows = [
        dict(
            head,
            settled=total(plan_groups.get(head["bill"], []), "settled"),
            unsettled=total(plan_groups.get(head["bill"], []), "unsettled"),
        )
        for head in heads
    ]
    summary = {key: total(rows, key) for key in ("amount", "settled", "unsettled")}
    summary.update(
        bill_count=len(rows),
        customer_count=count_distinct(rows, "customer"),
        customers_with_debt=sum(total(items, "unsettled") > 0 for items in groups(rows, "customer").values()),
        settlement_rate=rate(summary["settled"], summary["amount"]),
        head_plan_diff=summary["amount"] - summary["settled"] - summary["unsettled"],
    )
    customers = []
    for label, items in groups(rows, "customer").items():
        dates = [item["date"] for item in items if item["date"]]
        customers.append(
            {
                "name": label,
                "amount": total(items, "amount"),
                "settled": total(items, "settled"),
                "unsettled": total(items, "unsettled"),
                "bill_count": len(items),
                "earliest": min(dates) if dates else None,
                "latest": max(dates) if dates else None,
                "unsettled_rate": rate(total(items, "unsettled"), total(items, "amount")),
            }
        )
    customers.sort(key=lambda row: row["unsettled"], reverse=True)
    monthly = []
    for label, items in sorted(groups([dict(row, month=month(row["date"])) for row in rows], "month").items()):
        monthly.append(
            {
                "month": label,
                "amount": total(items, "amount"),
                "settled": total(items, "settled"),
                "unsettled": total(items, "unsettled"),
                "settlement_rate": rate(total(items, "settled"), total(items, "amount")),
            }
        )
    sections = [
        table(
            "客户欠款排行 TOP 50",
            customers,
            [
                ("name", "客户"),
                ("bill_count", "应收单数"),
                ("amount", "应收总额"),
                ("settled", "已收"),
                ("unsettled", "未收"),
                ("unsettled_rate", "欠款比例 %"),
                ("earliest", "最早单据日期"),
                ("latest", "最近单据日期"),
            ],
            50,
        ),
        table(
            "月度应收与结算趋势",
            monthly,
            [
                ("month", "月份"),
                ("amount", "应收总额"),
                ("settled", "已收"),
                ("unsettled", "未收"),
                ("settlement_rate", "结算率 %"),
            ],
        ),
        table(
            "应收单与收款计划核对",
            [summary],
            [
                ("amount", "表头总额"),
                ("settled", "计划已收"),
                ("unsettled", "计划未收"),
                ("head_plan_diff", "表头−计划总额"),
            ],
        ),
    ]
    return report(
        {"summary": summary, "customers": customers, "monthly": monthly, "bills": rows},
        cards(
            summary,
            [
                ("amount", "应收总额", ""),
                ("settled", "已收金额", ""),
                ("unsettled", "未收金额", ""),
                ("settlement_rate", "结算率", "%"),
                ("bill_count", "应收单数", ""),
                ("customers_with_debt", "欠款客户数", ""),
            ],
        ),
        sections,
        [
            "应收表头按单号去重；相同单号、已收、未收的重复计划行去重，再按单号汇总。",
            "未收取收款计划原值，不用表头金额减已收推算。没有到期日字段，不输出逾期账龄。",
            "收款计划是查询时当前状态，不是分析月末的历史余额；原包固定关联方和期初日期不用于认定本公司的关联方或期初。",
        ],
    )


def sales(rows):
    summary = {key: total(rows, key) for key in ("out", "receivable", "settled", "unsettled")}
    summary.update(
        line_count=len(rows),
        bill_count=count_distinct(rows, "bill"),
        customer_count=count_distinct(rows, "customer"),
        material_count=count_distinct(rows, "material"),
        receivable_rate=rate(summary["receivable"], summary["out"]),
        settlement_rate=rate(summary["settled"], summary["out"]),
    )
    rankings = {}
    for key in ("month", "customer", "salesperson"):
        ranking = []
        data = [dict(row, month=month(row["date"])) for row in rows] if key == "month" else rows
        for label, items in groups(data, key).items():
            item = {field: total(items, field) for field in ("out", "receivable", "settled", "unsettled")}
            ranking.append(
                dict(
                    item,
                    name=label,
                    bill_count=count_distinct(items, "bill"),
                    customer_count=count_distinct(items, "customer"),
                    settlement_rate=rate(item["settled"], item["receivable"]),
                )
            )
        rankings[key] = sorted(
            ranking,
            key=lambda item: (
                item["name"] if key == "month" else -(item["unsettled"] if key == "customer" else item["out"])
            ),
        )
    columns = [
        ("name", "名称"),
        ("out", "出库金额"),
        ("receivable", "应收金额"),
        ("settled", "实收金额"),
        ("unsettled", "未结算金额"),
        ("settlement_rate", "实收 / 应收 %"),
    ]
    sections = [
        table(
            "整体出库—应收—实收漏斗",
            [summary],
            [
                ("out", "出库金额"),
                ("receivable", "应收金额"),
                ("settled", "实收金额"),
                ("receivable_rate", "应收 / 出库 %"),
                ("settlement_rate", "实收 / 出库 %"),
            ],
        ),
        table("月度销售漏斗", rankings["month"], columns),
        table("客户欠款排行", rankings["customer"], columns),
        table("业务员销售漏斗", rankings["salesperson"], columns),
    ]
    return report(
        {
            "summary": summary,
            "monthly": rankings["month"],
            "customers": rankings["customer"],
            "salespersons": rankings["salesperson"],
        },
        cards(
            summary,
            [
                ("out", "出库金额", ""),
                ("receivable", "应收金额", ""),
                ("settled", "实收金额", ""),
                ("unsettled", "未结算金额", ""),
                ("settlement_rate", "整体实收 / 出库", "%"),
                ("bill_count", "出库单数", ""),
            ],
        ),
        sections,
        [
            "整体漏斗比率以出库金额为分母；月份、客户、业务员结算率以应收金额为分母。",
            "未结算=应收−实收，负值原样保留；分母为零显示 —。报表金额是原字段口径，不自动换汇。",
        ],
    )


def inventory(rows):
    periods = sorted({row["period"] for row in rows})
    latest = periods[-1] if periods else None
    materials = []
    for code, items in groups(rows, "code").items():
        current = [row for row in items if row["period"] == latest]
        avg = rounded(total(items, "out_qty") / len(periods)) if periods else ZERO
        end_qty, end_amount = total(current, "end_qty"), total(current, "end_amount")
        zero_ratio = number(sum(row["end_qty"] == 0 for row in items)) / len({row["period"] for row in items})
        direct = zero_ratio >= number("0.8")
        cover = rounded(end_qty / avg, 6) if avg > 0 else None
        if avg <= 0:
            bucket = "无消耗（滞压）"
        elif direct:
            bucket = "直发型（零库存运作）"
        else:
            bucket = next(
                (
                    label
                    for threshold, label in ((1, "不足 1 月"), (3, "1-3 月"), (6, "3-6 月"), (12, "6-12 月"))
                    if cover < threshold
                ),
                "超过 12 月",
            )
        materials.append(
            {
                "code": code,
                "name": items[0]["name"],
                "group": items[0]["group"],
                "out_qty": total(items, "out_qty"),
                "out_amount": total(items, "out_amount"),
                "end_qty": end_qty,
                "end_amount": end_amount,
                "avg_out": avg,
                "cover": cover,
                "direct": direct,
                "zero_end_rate": rounded(zero_ratio * 100, 1),
                "bucket": bucket,
            }
        )
    dead = sorted(
        [row for row in materials if row["out_qty"] <= 0 and row["end_qty"] > 0],
        key=lambda row: row["end_amount"],
        reverse=True,
    )
    active = [row for row in materials if row["avg_out"] > 0]
    direct_active = [row for row in active if row["direct"]]
    shortage = sorted(
        [row for row in active if not row["direct"] and row["cover"] < 1],
        key=lambda row: row["out_amount"],
        reverse=True,
    )
    summary = {
        "period_count": len(periods),
        "first_period": periods[0] if periods else None,
        "latest_period": latest,
        "material_count": len(materials),
        "end_amount": total(materials, "end_amount"),
        "out_amount": total(materials, "out_amount"),
        "dead_count": len(dead),
        "dead_amount": total(dead, "end_amount"),
        "dead_rate": rate(total(dead, "end_amount"), total(materials, "end_amount")),
        "direct_count": len(direct_active),
        "direct_rate": rate(len(direct_active), len(active)),
        "active_count": len(active),
        "shortage_count": len(shortage),
        "shortage_rate": rate(len(shortage), len(active) - len(direct_active)),
    }
    current = [row for row in rows if row["period"] == latest]
    stocked = [row for row in current if row["end_qty"] > 0]
    missing = [row for row in stocked if row["end_amount"] <= 0]
    priced = [row for row in stocked if row["end_amount"] > 0]
    avg_price = rounded(total(priced, "end_amount") / total(priced, "end_qty"), 4) if total(priced, "end_qty") else ZERO
    quality = {
        "latest_period": latest,
        "stock_rows": len(stocked),
        "missing_price_rows": len(missing),
        "missing_price_qty": total(missing, "end_qty"),
        "missing_price_rate": rate(len(missing), len(stocked)),
        "estimated_missing_value": rounded(total(missing, "end_qty") * avg_price),
        "qty_broken": sum(
            abs(row["end_qty"] - row["init_qty"] - row["in_qty"] + row["out_qty"]) > number("0.01") for row in current
        ),
        "amount_broken": sum(
            abs(row["end_amount"] - row["init_amount"] - row["in_amount"] + row["out_amount"]) > number("0.01")
            for row in current
        ),
    }
    monthly = [
        {
            "month": label,
            "in_amount": total(items, "in_amount"),
            "out_amount": total(items, "out_amount"),
            "end_amount": total(items, "end_amount"),
            "material_count": count_distinct(items, "code"),
        }
        for label, items in sorted(groups(rows, "period").items())
    ]
    bucket_groups = groups(materials, "bucket")
    buckets = [
        {
            "name": label,
            "count": len(bucket_groups.get(label, [])),
            "amount": total(bucket_groups.get(label, []), "end_amount"),
            "ratio": rate(total(bucket_groups.get(label, []), "end_amount"), summary["end_amount"]),
        }
        for label in (
            "无消耗（滞压）",
            "直发型（零库存运作）",
            "不足 1 月",
            "1-3 月",
            "3-6 月",
            "6-12 月",
            "超过 12 月",
        )
    ]
    columns = [
        ("code", "物料编码"),
        ("name", "物料名称"),
        ("group", "物料组"),
        ("end_qty", "最新期末数量"),
        ("end_amount", "最新期末金额"),
        ("avg_out", "月均消耗数量"),
        ("cover", "覆盖月数"),
        ("bucket", "分层"),
    ]
    sections = [
        table(
            "月度收发存金额",
            monthly,
            [
                ("month", "月份"),
                ("in_amount", "收入金额"),
                ("out_amount", "发出金额"),
                ("end_amount", "期末金额"),
                ("material_count", "物料数"),
            ],
        ),
        table(
            "库存覆盖分层",
            buckets,
            [("name", "类别"), ("count", "物料数"), ("amount", "期末金额"), ("ratio", "金额占比 %")],
        ),
        table("滞压物料", dead, columns),
        table("短缺风险（排除直发）", shortage, columns),
        table("物料库存健康度全表", sorted(materials, key=lambda row: row["end_amount"], reverse=True), columns),
        table(
            "最新期间数据质量",
            [quality],
            [
                ("latest_period", "实际库存末期"),
                ("stock_rows", "有库存行数"),
                ("missing_price_rows", "缺价行数"),
                ("missing_price_rate", "缺价比例 %"),
                ("estimated_missing_value", "缺价估值（仅提示）"),
                ("qty_broken", "数量不平衡行"),
                ("amount_broken", "金额不平衡行"),
            ],
        ),
    ]
    return report(
        {"summary": summary, "materials": materials, "monthly": monthly, "quality": quality, "buckets": buckets},
        cards(
            summary,
            [
                ("end_amount", "最新期末库存金额", ""),
                ("dead_amount", "滞压金额", ""),
                ("dead_rate", "滞压金额占比", "%"),
                ("shortage_count", "短缺风险物料", ""),
                ("direct_count", "直发型物料", ""),
                ("period_count", "有数据期间数", ""),
            ],
        ),
        sections,
        [
            f"实际有数据期间：{summary['first_period'] or '—'} ~ {latest or '—'}。期末库存只汇总最新有数据期间；月均消耗分母为共同有数据期间数。",
            "零库存行数 / 该物料出现期间数 ≥ 80% 为直发，短缺率分母排除直发物料。维度含物料、仓库，沿用原包行/期间比。",
            "没有实际消耗不等于可用账龄；覆盖月数不是库龄。缺价估值仅为质量提示，不修正账面金额。",
        ],
    )


def execution(rows, reference, *, subcontract_mode=False):
    if reference is None:
        raise ValueError("必须显式传入分析期间参照日期")
    group_key = "supplier" if subcontract_mode else "workshop"
    rows = [dict(row, finished=row["finish"] is not None) for row in rows]

    def summarize(items):
        cycles = [
            (row["finish"] - row["plan_start" if subcontract_mode else "start"]).days
            for row in items
            if row["finish"] and row.get("plan_start" if subcontract_mode else "start")
        ]
        overdue = [row for row in items if row["due"] and row["due"] < reference and not row["finished"]]
        result = {
            "line_count": len(items),
            "bill_count": count_distinct(items, "bill"),
            "material_count": count_distinct(items, "material"),
            "group_count": count_distinct(items, group_key),
            "qty": total(items, "qty"),
            "stockin": total(items, "stockin"),
            "remaining": total(items, "remaining"),
            "finished_count": sum(row["finished"] for row in items),
            "not_finished_count": sum(not row["finished"] for row in items),
            "overdue_count": len(overdue),
            "overdue_qty": total(overdue, "remaining"),
            "avg_days": rounded(sum(max(days, 0) for days in cycles) / number(len(cycles)), 1) if cycles else ZERO,
            "cycle_samples": len(cycles),
        }
        result.update(
            stockin_rate=rate(result["stockin"], result["qty"], undefined=ZERO),
            finish_rate=rate(result["finished_count"], len(items), undefined=ZERO),
            overdue_rate=rate(len(overdue), len(items), undefined=ZERO),
        )
        if not subcontract_mode:
            result.update(
                in_progress=sum(row["start"] is not None and not row["finished"] for row in items),
                not_started=sum(row["start"] is None for row in items),
            )
        return result

    summary = summarize(rows)
    monthly = [
        dict(summarize(items), name=label)
        for label, items in sorted(groups([dict(row, month=month(row["date"])) for row in rows], "month").items())
    ]
    ranks = {
        key: sorted(
            [dict(summarize(items), name=label) for label, items in groups(rows, key).items()],
            key=lambda row: row["remaining"],
            reverse=True,
        )[:50]
        for key in (group_key, "material")
    }
    status = [
        {
            "name": label,
            "count": len(items),
            "qty": total(items, "qty"),
            "remaining": total(items, "remaining"),
            "ratio": rate(len(items), len(rows), undefined=ZERO),
        }
        for label, items in groups(rows, "status").items()
    ]
    overdue = sorted(
        [
            dict(row, days=(reference - row["due"]).days)
            for row in rows
            if row["due"] and row["due"] < reference and not row["finished"]
        ],
        key=lambda row: (row["days"], row["remaining"]),
        reverse=True,
    )
    backlog = sorted([row for row in rows if row["remaining"] > 0], key=lambda row: row["remaining"], reverse=True)
    columns = [
        ("name", "名称"),
        ("line_count", "分录数"),
        ("qty", "计划数量"),
        ("stockin", "入库数量"),
        ("remaining", "未入库数量"),
        ("finished_count", "完工分录"),
        ("stockin_rate", "入库率 %"),
        ("finish_rate", "完工率 %"),
        ("avg_days", "计划开工至完工天数" if subcontract_mode else "实际平均工期"),
        ("cycle_samples", "有效工期样本数"),
    ]
    details = [
        ("bill", "订单号"),
        ("entry", "分录ID"),
        ("date", "订单日期"),
        ("material", "物料"),
        (group_key, "供应商" if subcontract_mode else "车间"),
        ("due", "计划完工日期"),
        ("qty", "计划数量"),
        ("stockin", "入库数量"),
        ("remaining", "未入库数量"),
    ]
    sections = [
        table("月度执行趋势", monthly, columns),
        table(
            "状态分布",
            status,
            [
                ("name", "状态编码"),
                ("count", "分录数"),
                ("qty", "计划数量"),
                ("remaining", "未入库数量"),
                ("ratio", "占比 %"),
            ],
        ),
        table("供应商执行排行 TOP 50" if subcontract_mode else "车间执行排行 TOP 50", ranks[group_key], columns),
        table("物料执行排行 TOP 50", ranks["material"], columns),
        table("逾期未完工 TOP 50", overdue, details + [("days", "逾期天数")], 50),
        table("未入库积压 TOP 50", backlog, details + [("status", "状态编码")], 50),
    ]
    return {
        "summary": summary,
        "monthly": monthly,
        "rankings": ranks,
        "status": status,
        "overdue": overdue,
        "backlog": backlog,
    }, sections


def production(orders, reports, reference):
    metrics, sections = execution(orders, reference)
    quality = {key: total(reports, key) for key in ("inspected", "qualified", "failed", "scrap", "rework")}
    quality.update(
        report_count=count_distinct(reports, "bill"),
        line_count=len(reports),
        qualified_rate=rate(quality["qualified"], quality["inspected"], undefined=ZERO),
        failed_rate=rate(quality["failed"], quality["inspected"], undefined=ZERO),
    )
    monthly_quality = [
        {
            "month": label,
            "inspected": total(items, "inspected"),
            "qualified": total(items, "qualified"),
            "failed": total(items, "failed"),
            "qualified_rate": rate(total(items, "qualified"), total(items, "inspected"), undefined=ZERO),
        }
        for label, items in sorted(groups([dict(row, month=month(row["date"])) for row in reports], "month").items())
    ]
    bill_types = [
        {
            "name": label,
            "count": len(items),
            "qty": total(items, "qty"),
            "ratio": rate(len(items), len(orders), undefined=ZERO),
        }
        for label, items in groups(orders, "bill_type").items()
    ]
    metrics["summary"]["workshop_count"] = count_distinct(orders, "workshop")
    metrics.update(quality=quality, monthly_quality=monthly_quality, bill_types=bill_types)
    sections.extend(
        [
            table(
                "生产质量汇总",
                [quality],
                [
                    ("report_count", "汇报单数"),
                    ("inspected", "报检数量"),
                    ("qualified", "合格数量"),
                    ("failed", "不合格数量"),
                    ("scrap", "报废数量"),
                    ("rework", "返工数量"),
                    ("qualified_rate", "合格率 %"),
                    ("failed_rate", "不合格率 %"),
                ],
            ),
            table(
                "月度质量趋势",
                monthly_quality,
                [
                    ("month", "月份"),
                    ("inspected", "报检数量"),
                    ("qualified", "合格数量"),
                    ("failed", "不合格数量"),
                    ("qualified_rate", "合格率 %"),
                ],
            ),
            table(
                "单据类型占比",
                bill_types,
                [("name", "单据类型"), ("count", "分录数"), ("qty", "计划数量"), ("ratio", "分录占比 %")],
            ),
        ]
    )
    return report(
        metrics,
        cards(
            metrics["summary"],
            [
                ("qty", "计划数量", ""),
                ("stockin", "入库数量", ""),
                ("remaining", "未入库数量", ""),
                ("finish_rate", "完工率", "%"),
                ("overdue_count", "逾期分录数", ""),
                ("avg_days", "平均实际工期", "天"),
            ],
        ),
        sections,
        [
            "完工依据实际完工日期，不按状态编码猜测。逾期依据计划完工日期和分析期间次月首日。",
            "工期使用实际开工—实际完工的有效日期对，负天数按零计；样本数量一并展示。",
            "生产订单无可靠金额字段，不输出产值；合格率 / 不合格率均以报检数量为分母。",
        ],
    )


def subcontract(orders, picks, wips, reference):
    metrics, sections = execution(orders, reference, subcontract_mode=True)
    finished = [row for row in orders if row["finish"]]
    judged = [row for row in finished if row["due"]]
    late = [(row["finish"] - row["due"]).days for row in judged if row["finish"] > row["due"]]
    delivery = {
        "finished_count": len(finished),
        "on_time_count": len(judged) - len(late),
        "late_count": len(late),
        "no_plan_count": len(finished) - len(judged),
        "on_time_rate": rate(len(judged) - len(late), len(judged), undefined=ZERO),
        "avg_late_days": rounded(sum(late) / number(len(late)), 1) if late else ZERO,
        "max_late_days": max(late, default=0),
    }
    issue = {
        "bill_count": count_distinct(picks, "bill"),
        "line_count": len(picks),
        "supplier_count": count_distinct(picks, "supplier"),
        "material_count": count_distinct(picks, "material"),
        "app_qty": total(picks, "app_qty"),
        "actual_qty": total(picks, "actual_qty"),
        "return_qty": total(picks, "return_qty"),
        "issue_rate": rate(total(picks, "actual_qty"), total(picks, "app_qty"), undefined=ZERO),
        "short_count": sum(row["actual_qty"] < row["app_qty"] for row in picks),
    }
    monthly_issue = [
        {
            "month": label,
            "app_qty": total(items, "app_qty"),
            "actual_qty": total(items, "actual_qty"),
            "issue_rate": rate(total(items, "actual_qty"), total(items, "app_qty"), undefined=ZERO),
        }
        for label, items in sorted(groups([dict(row, month=month(row["date"])) for row in picks], "month").items())
    ]
    wip = {
        key: total(wips, key)
        for key in ("must", "picked", "consumed", "defect_return", "good_return", "wip", "not_picked")
    }
    wip.update(
        line_count=len(wips),
        bill_count=count_distinct(wips, "bill"),
        supplier_count=count_distinct(wips, "supplier"),
        nonzero_count=sum(row["wip"] != 0 for row in wips),
        negative_count=sum(row["wip"] < 0 for row in wips),
        unbalanced_count=sum(
            abs(row["wip"] - row["picked"] + row["consumed"] + row["defect_return"] + row["good_return"])
            > number("0.000001")
            for row in wips
        ),
    )
    wip_ranking = sorted(
        [
            {
                "name": label,
                "line_count": len(items),
                "picked": total(items, "picked"),
                "consumed": total(items, "consumed"),
                "defect_return": total(items, "defect_return"),
                "good_return": total(items, "good_return"),
                "wip": total(items, "wip"),
            }
            for label, items in groups(wips, "supplier").items()
        ],
        key=lambda row: row["wip"],
        reverse=True,
    )
    metrics["summary"]["supplier_count"] = count_distinct(orders, "supplier")
    metrics.update(delivery=delivery, issue=issue, monthly_issue=monthly_issue, wip=wip, wip_ranking=wip_ranking)
    sections.extend(
        [
            table(
                "已完工委外交付",
                [delivery],
                [
                    ("finished_count", "完工分录"),
                    ("on_time_count", "准时"),
                    ("late_count", "延期"),
                    ("no_plan_count", "缺少计划日期"),
                    ("on_time_rate", "准时率 %"),
                    ("avg_late_days", "平均延期天数"),
                    ("max_late_days", "最大延期天数"),
                ],
            ),
            table(
                "委外领料执行",
                [issue],
                [
                    ("bill_count", "领料单数"),
                    ("app_qty", "申请数量"),
                    ("actual_qty", "实领数量"),
                    ("return_qty", "选单退料数量"),
                    ("issue_rate", "领料执行率 %"),
                    ("short_count", "少领行数"),
                ],
            ),
            table(
                "月度领料趋势",
                monthly_issue,
                [("month", "月份"), ("app_qty", "申请数量"), ("actual_qty", "实领数量"), ("issue_rate", "执行率 %")],
            ),
            table(
                "当前在制快照（不按期间过滤）",
                [wip],
                [
                    ("line_count", "用料清单行数"),
                    ("must", "应领"),
                    ("picked", "已领"),
                    ("consumed", "已耗"),
                    ("defect_return", "不良退料"),
                    ("good_return", "良品退料"),
                    ("wip", "ERP在制原值"),
                    ("not_picked", "未领"),
                    ("negative_count", "负在制行数"),
                    ("unbalanced_count", "平衡式不一致行数"),
                ],
            ),
            table(
                "供应商在制排行 TOP 50",
                wip_ranking,
                [
                    ("name", "供应商"),
                    ("line_count", "行数"),
                    ("picked", "已领"),
                    ("consumed", "已耗"),
                    ("defect_return", "不良退料"),
                    ("good_return", "良品退料"),
                    ("wip", "在制原值"),
                ],
                50,
            ),
        ]
    )
    return report(
        metrics,
        cards(
            metrics["summary"],
            [
                ("qty", "委外计划数量", ""),
                ("stockin", "入库数量", ""),
                ("remaining", "未入库数量", ""),
                ("finish_rate", "完工率", "%"),
                ("overdue_count", "逾期分录数", ""),
                ("avg_days", "计划开工至完工", "天"),
            ],
        ),
        sections,
        [
            "委外组织字段是 FSubOrgId；SUB_PPBOM 无业务日期，显示生成时的当前快照而非历史期末在制。",
            "在制直接累计 ERP FWipQty；已领−已耗−不良退料−良品退料仅作平衡校验，负在制原样保留。",
            "委外无实际开工日期，计划开工至完工天数不等于实际加工周期；不输出加工金额或结案分析。",
        ],
    )
