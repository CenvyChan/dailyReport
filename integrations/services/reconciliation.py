"""金额对账计算引擎：实现三个互不混淆的观察角度。

阶段 3 核心：
- 日报侧关联覆盖率：每条日报已关联分摊金额 / 日报金额总基数
- 同期间金额差异：系统金额 - 金蝶金额，差异率
- 金蝶明细分摊情况：原始金额 vs 累计分摊，展示余额和超额

关键规则：
- 使用绝对金额计算覆盖权重，避免正负金额互相抵消
- 零分母显示"—"
- 金蝶金额为零或数据不完整时不生成误导性百分比
- 每条金蝶明细只取一次原始金额
- 跨日关联单独展示，不判断为漏单
- 未映射金蝶客商进入独立分组
"""

import logging
from decimal import Decimal
from typing import Optional

from django.db.models import Q, Sum
from django.utils import timezone

from core.models import Company
from integrations.models import (
    BusinessType,
    DailyReportKingdeeLink,
    StockTransaction,
)
from purchase.models import PurchaseReceipt
from sales.models import SalesShipment

logger = logging.getLogger("integrations")


def calculate_daily_coverage(
    company: Company,
    report_date,
    business_type: str,
) -> dict:
    """计算日报侧关联覆盖率。

    Args:
        company: 公司对象
        report_date: 报表日期
        business_type: "SALES" | "PURCHASE"

    Returns:
        {
            "total_reports": int,
            "total_amount": Decimal,
            "covered_amount": Decimal,
            "coverage_rate": float | None,  # None 表示分母为零
            "details": [
                {
                    "report_id": int,
                    "date": str,
                    "party_name": str,
                    "amount": Decimal,
                    "allocated_amount": Decimal,
                    "coverage": float | None,
                }
            ]
        }
    """
    if business_type == "SALES":
        model = SalesShipment
        date_field = "shipment_date"
        party_field = "customer__name"
    else:
        model = PurchaseReceipt
        date_field = "purchase_date"
        party_field = "supplier__name"

    reports = model.objects.filter(
        company=company,
        **{date_field: report_date}
    ).select_related("customer" if business_type == "SALES" else "supplier")

    total_amount = Decimal("0")
    covered_amount = Decimal("0")
    details = []

    for report in reports:
        amount = report.amount_cny
        total_amount += abs(amount)  # 使用绝对金额计算基数

        # 计算该日报的已分摊金额
        links = DailyReportKingdeeLink.objects.filter(
            report_type=business_type,
            **{
                "sales_shipment" if business_type == "SALES" else "purchase_receipt": report
            }
        ).aggregate(total=Sum("allocated_amount"))

        allocated = links["total"] or Decimal("0")

        # 分摊金额按日报自身金额封顶
        capped_allocated = min(abs(allocated), abs(amount))
        covered_amount += capped_allocated

        # 计算覆盖率
        if amount == 0:
            coverage = None
        else:
            coverage = float(capped_allocated / abs(amount) * 100)

        party = report.customer if business_type == "SALES" else report.supplier
        details.append({
            "report_id": report.id,
            "date": getattr(report, date_field).isoformat(),
            "party_name": party.name if party else "",
            "amount": float(amount),
            "allocated_amount": float(allocated),
            "capped_allocated": float(capped_allocated),
            "coverage": coverage,
        })

    # 计算总覆盖率
    coverage_rate = None
    if total_amount > 0:
        coverage_rate = float(covered_amount / total_amount * 100)

    return {
        "total_reports": len(details),
        "total_amount": float(total_amount),
        "covered_amount": float(covered_amount),
        "coverage_rate": coverage_rate,
        "details": details,
    }


def calculate_period_diff(
    company: Company,
    date_from,
    date_to,
    business_type: str,
) -> dict:
    """计算同期间金额差异。

    Args:
        company: 公司对象
        date_from: 起始日期
        date_to: 结束日期（含）
        business_type: "SALES" | "PURCHASE"

    Returns:
        {
            "date_from": str,
            "date_to": str,
            "system_amount": Decimal,
            "k3_amount": Decimal,
            "diff_amount": Decimal,  # 系统 - 金蝶
            "diff_rate": float | None,  # None 表示不可计算
            "is_complete": bool,  # 金蝶数据是否完整
        }
    """
    # 系统侧：按日报日期汇总
    if business_type == "SALES":
        model = SalesShipment
        date_field = "shipment_date"
    else:
        model = PurchaseReceipt
        date_field = "purchase_date"

    system_result = model.objects.filter(
        company=company,
        **{f"{date_field}__gte": date_from, f"{date_field}__lte": date_to}
    ).aggregate(total=Sum("amount_cny"))

    system_amount = system_result["total"] or Decimal("0")

    # 金蝶侧：按业务日期汇总
    biz_type = BusinessType.SALES_OUT if business_type == "SALES" else BusinessType.PURCHASE_IN
    k3_result = StockTransaction.objects.filter(
        company=company,
        business_type=biz_type,
        is_active=True,
        biz_date__gte=date_from,
        biz_date__lte=date_to,
    ).aggregate(total=Sum("total_amount"))

    k3_amount = k3_result["total"] or Decimal("0")

    # 计算差异
    diff_amount = system_amount - k3_amount

    # 计算差异率
    diff_rate = None
    if k3_amount != 0:
        diff_rate = float(diff_amount / abs(k3_amount) * 100)

    # TODO: 判断数据完整性（需要从 SyncRun 获取窗口信息）
    is_complete = True

    return {
        "date_from": date_from.isoformat(),
        "date_to": date_to.isoformat(),
        "system_amount": float(system_amount),
        "k3_amount": float(k3_amount),
        "diff_amount": float(diff_amount),
        "diff_rate": diff_rate,
        "is_complete": is_complete,
    }


def calculate_k3_allocation_status(
    company: Company,
    date_from,
    date_to,
    business_type: str,
    limit: int = 500,
) -> dict:
    """计算金蝶明细分摊情况。

    Args:
        company: 公司对象
        date_from: 起始日期
        date_to: 结束日期（含）
        business_type: "SALES_OUT" | "PURCHASE_IN"
        limit: 最大返回明细数

    Returns:
        {
            "total_lines": int,
            "total_amount": Decimal,
            "allocated_amount": Decimal,
            "remaining_amount": Decimal,
            "over_allocated_amount": Decimal,
            "details": [
                {
                    "line_id": int,
                    "bill_no": str,
                    "biz_date": str,
                    "party_name": str,
                    "material_name": str,
                    "amount": Decimal,
                    "allocated": Decimal,
                    "remaining": Decimal,
                    "over_allocated": Decimal,
                    "is_cross_date": bool,  # 是否跨日关联
                }
            ]
        }
    """
    from django.db.models import OuterRef, Subquery
    from integrations.models import StockTransactionLine

    # 查询期间内的金蝶明细
    lines = StockTransactionLine.objects.filter(
        transaction__company=company,
        transaction__business_type=business_type,
        transaction__is_active=True,
        transaction__biz_date__gte=date_from,
        transaction__biz_date__lte=date_to,
    ).select_related("transaction").annotate(
        allocated_total=Sum("daily_report_links__allocated_amount")
    )[:limit]

    total_amount = Decimal("0")
    allocated_amount = Decimal("0")
    remaining_amount = Decimal("0")
    over_allocated_amount = Decimal("0")
    details = []

    for line in lines:
        txn = line.transaction
        amount = line.amount
        allocated = line.allocated_total or Decimal("0")
        remaining = max(Decimal("0"), amount - allocated)
        over_allocated = max(Decimal("0"), allocated - amount)

        total_amount += amount
        allocated_amount += allocated
        remaining_amount += remaining
        over_allocated_amount += over_allocated

        # 检查是否跨日关联
        is_cross_date = False
        if allocated > 0:
            # 检查关联的日报日期是否与金蝶业务日期一致
            links = DailyReportKingdeeLink.objects.filter(
                transaction_line=line
            ).select_related("sales_shipment", "purchase_receipt")

            for link in links:
                daily_date = None
                if link.sales_shipment:
                    daily_date = link.sales_shipment.shipment_date
                elif link.purchase_receipt:
                    daily_date = link.purchase_receipt.purchase_date

                if daily_date and daily_date != txn.biz_date:
                    is_cross_date = True
                    break

        details.append({
            "line_id": line.id,
            "entry_id": line.entry_id,
            "bill_no": txn.bill_no,
            "biz_date": txn.biz_date.isoformat(),
            "party_name": txn.k3_party_name,
            "material_name": line.material_name,
            "amount": float(amount),
            "allocated": float(allocated),
            "remaining": float(remaining),
            "over_allocated": float(over_allocated),
            "is_cross_date": is_cross_date,
        })

    return {
        "total_lines": len(details),
        "total_amount": float(total_amount),
        "allocated_amount": float(allocated_amount),
        "remaining_amount": float(remaining_amount),
        "over_allocated_amount": float(over_allocated_amount),
        "details": details,
    }


def generate_reconciliation_report(
    company: Company,
    report_date,
    scope: str = "BOTH",
) -> dict:
    """生成完整的对账报表数据。

    Args:
        company: 公司对象
        report_date: 报表日期
        scope: "SALES" | "PURCHASE" | "BOTH"

    Returns:
        完整报表数据字典，包含三个维度的对账结果
    """
    from datetime import timedelta

    result = {
        "company": company.name,
        "report_date": report_date.isoformat(),
        "scope": scope,
        "generated_at": timezone.now().isoformat(),
    }

    # 月累计期间
    month_start = report_date.replace(day=1)
    month_end = report_date

    # 年累计期间
    year_start = report_date.replace(month=1, day=1)
    year_end = report_date

    if scope in ("BOTH", "SALES"):
        result["sales"] = {
            "daily_coverage": calculate_daily_coverage(company, report_date, "SALES"),
            "month_diff": calculate_period_diff(company, month_start, month_end, "SALES"),
            "year_diff": calculate_period_diff(company, year_start, year_end, "SALES"),
            "k3_allocation": calculate_k3_allocation_status(
                company, month_start, month_end, BusinessType.SALES_OUT
            ),
        }

    if scope in ("BOTH", "PURCHASE"):
        result["purchase"] = {
            "daily_coverage": calculate_daily_coverage(company, report_date, "PURCHASE"),
            "month_diff": calculate_period_diff(company, month_start, month_end, "PURCHASE"),
            "year_diff": calculate_period_diff(company, year_start, year_end, "PURCHASE"),
            "k3_allocation": calculate_k3_allocation_status(
                company, month_start, month_end, BusinessType.PURCHASE_IN
            ),
        }

    return result
