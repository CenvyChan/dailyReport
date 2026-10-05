"""日报-金蝶明细关联服务：选单、分摊、解除关联。

阶段 2 核心功能：
- 本地明细检索：支持单号、客商、日期查询
- 关联保存：同一事务内保存日报和关联
- 客商建议：自动带出系统客商或产生映射建议
- 历史匹配：按公司、业务类型、客商、日期及金额生成候选
"""

import logging
from decimal import Decimal
from typing import Optional

from django.db import transaction
from django.db.models import Q, Sum
from django.utils import timezone

from core.models import Company
from integrations.models import (
    BusinessType,
    DailyReportKingdeeLink,
    KingdeePartyMapping,
    StockTransaction,
    StockTransactionLine,
)

logger = logging.getLogger("integrations")


def search_kingdee_lines(
    company: Company,
    business_type: str,
    *,
    bill_no: str = "",
    party_name: str = "",
    date_from: str = "",
    date_to: str = "",
    material_name: str = "",
    only_recent: bool = True,
    limit: int = 100,
):
    """检索金蝶明细行，返回明细身份、客商、日期、金额、分摊情况及快照时间。

    Args:
        company: 公司对象
        business_type: 业务类型（SALES_OUT/PURCHASE_IN）
        bill_no: 单据编号（模糊匹配）
        party_name: 客商名称（模糊匹配）
        date_from: 起始日期 YYYY-MM-DD
        date_to: 结束日期 YYYY-MM-DD
        material_name: 物料名称（模糊匹配）
        only_recent: 仅展示近期数据（最近30天）
        limit: 最大返回行数

    Returns:
        list[dict]: 明细列表，每条包含：
            - line_id: 明细主键
            - entry_id: 金蝶明细内码
            - transaction_id: 单据主键
            - bill_no: 单据编号
            - biz_date: 业务日期
            - k3_party_name: 金蝶客商名称
            - system_party: 系统客商（已映射时）
            - material_name: 物料名称
            - quantity: 数量
            - amount: 金额
            - allocated_amount: 已分摊金额
            - remaining_amount: 剩余金额
            - over_allocated: 超额金额（>0 表示超额）
            - sync_time: 同步时间
    """
    from datetime import date, timedelta

    qs = StockTransactionLine.objects.filter(
        transaction__company=company,
        transaction__business_type=business_type,
        transaction__is_active=True,
    ).select_related("transaction", "transaction__party")

    if bill_no:
        qs = qs.filter(transaction__bill_no__icontains=bill_no)
    if party_name:
        qs = qs.filter(
            Q(transaction__k3_party_name__icontains=party_name)
            | Q(transaction__party__k3_name__icontains=party_name)
        )
    if date_from:
        qs = qs.filter(transaction__biz_date__gte=date_from)
    if date_to:
        qs = qs.filter(transaction__biz_date__lte=date_to)
    if material_name:
        qs = qs.filter(material_name__icontains=material_name)

    if only_recent and not date_from:
        recent = date.today() - timedelta(days=30)
        qs = qs.filter(transaction__biz_date__gte=recent)

    # 计算每条明细的已分摊金额
    qs = qs.annotate(
        allocated_total=Sum("daily_report_links__allocated_amount")
    )

    qs = qs.order_by("-transaction__biz_date", "-transaction__id", "seq")[:limit]

    results = []
    for line in qs:
        txn = line.transaction
        allocated = line.allocated_total or Decimal("0")
        remaining = line.amount - allocated
        over_allocated = max(Decimal("0"), allocated - line.amount)

        # 获取系统客商（已映射时）
        system_party = None
        if txn.party:
            if business_type == BusinessType.SALES_OUT:
                system_party = txn.party.customer
            else:
                system_party = txn.party.supplier

        results.append({
            "line_id": line.id,
            "entry_id": line.entry_id,
            "transaction_id": txn.id,
            "fid": txn.fid,
            "bill_no": txn.bill_no,
            "biz_date": txn.biz_date.isoformat(),
            "k3_party_number": txn.k3_party_number,
            "k3_party_name": txn.k3_party_name,
            "system_party_id": system_party.id if system_party else None,
            "system_party_name": system_party.name if system_party else None,
            "mapping_status": txn.party.match_status if txn.party else None,
            "material_number": line.material_number,
            "material_name": line.material_name,
            "quantity": float(line.quantity),
            "unit": line.unit,
            "amount": float(line.amount),
            "allocated_amount": float(allocated),
            "remaining_amount": float(remaining),
            "over_allocated": float(over_allocated),
            "sync_time": txn.updated_at.isoformat(),
        })

    return results


def save_daily_with_links(
    daily_report,
    report_type: str,
    link_data: list[dict],
    operator,
) -> tuple[int, list[str]]:
    """保存日报与关联在同一事务内。

    Args:
        daily_report: 销售日报或采购日报对象（已保存或新建）
        report_type: "SALES" 或 "PURCHASE"
        link_data: 关联明细列表，每条包含：
            - line_id: StockTransactionLine 主键
            - allocated_amount: 分摊金额
            - allocated_quantity: 分摊数量（可选）
        operator: 操作人

    Returns:
        (关联数, 警告列表)

    Raises:
        ValueError: 权限不足或数据不合法
    """
    warnings = []

    if not link_data:
        return 0, warnings

    with transaction.atomic():
        # 确保日报已保存
        if not daily_report.id:
            daily_report.save()

        # 获取所有待关联的明细
        line_ids = [item["line_id"] for item in link_data]
        lines = StockTransactionLine.objects.filter(
            id__in=line_ids
        ).select_related("transaction", "transaction__party")

        if len(lines) != len(line_ids):
            raise ValueError("部分明细不存在或已删除")

        # 检查公司一致性
        for line in lines:
            if line.transaction.company_id != daily_report.company_id:
                raise ValueError(f"金蝶明细 {line.entry_id} 不属于当前公司")

        # 检查业务类型一致性
        expected_biz = BusinessType.SALES_OUT if report_type == "SALES" else BusinessType.PURCHASE_IN
        for line in lines:
            if line.transaction.business_type != expected_biz:
                raise ValueError(f"金蝶明细 {line.entry_id} 业务类型不匹配")

        # 检查客商一致性（可选警告）
        unique_parties = set()
        for line in lines:
            if line.transaction.party:
                resolved = line.transaction.party.resolved
                if resolved:
                    unique_parties.add(resolved.id)

        if len(unique_parties) > 1:
            warnings.append("选中的明细对应多个系统客商，请确认是否正确")

        # 保存或更新关联
        link_count = 0
        for item in link_data:
            line = next(ln for ln in lines if ln.id == item["line_id"])
            allocated_amount = Decimal(str(item["allocated_amount"]))
            allocated_quantity = Decimal(str(item.get("allocated_quantity", 0)))

            # 获取参考值
            ref_k3_amount = line.amount
            ref_daily_amount = daily_report.amount_cny if hasattr(daily_report, "amount_cny") else None

            # 同一日报+同一明细只能有一条关联，存在则更新
            link_kwargs = {
                "report_type": report_type,
                "transaction_line": line,
            }
            if report_type == "SALES":
                link_kwargs["sales_shipment"] = daily_report
            else:
                link_kwargs["purchase_receipt"] = daily_report

            link, created = DailyReportKingdeeLink.objects.update_or_create(
                **link_kwargs,
                defaults={
                    "allocated_amount": allocated_amount,
                    "allocated_quantity": allocated_quantity,
                    "reference_k3_amount": ref_k3_amount,
                    "reference_daily_amount": ref_daily_amount,
                    "linked_by": operator,
                }
            )
            link_count += 1

            # 检查超额分摊
            total_allocated = DailyReportKingdeeLink.objects.filter(
                transaction_line=line
            ).aggregate(total=Sum("allocated_amount"))["total"] or Decimal("0")

            if total_allocated > line.amount:
                over = total_allocated - line.amount
                warnings.append(
                    f"明细 {line.entry_id} 超额分摊 {over:.2f} 元"
                )

    return link_count, warnings


def remove_links(
    daily_report,
    report_type: str,
    line_ids: Optional[list[int]] = None,
) -> int:
    """解除日报的关联。

    Args:
        daily_report: 销售日报或采购日报对象
        report_type: "SALES" 或 "PURCHASE"
        line_ids: 要解除的明细ID列表，None 表示解除全部

    Returns:
        解除的关联数
    """
    qs = DailyReportKingdeeLink.objects.filter(report_type=report_type)

    if report_type == "SALES":
        qs = qs.filter(sales_shipment=daily_report)
    else:
        qs = qs.filter(purchase_receipt=daily_report)

    if line_ids is not None:
        qs = qs.filter(transaction_line_id__in=line_ids)

    count = qs.count()
    qs.delete()

    return count


def suggest_historical_matches(
    company: Company,
    business_type: str,
    party_id: int,
    date_from: str,
    date_to: str,
    amount_min: Optional[float] = None,
    amount_max: Optional[float] = None,
    limit: int = 50,
):
    """按公司、业务类型、已确认客商、日期及金额生成候选。

    Args:
        company: 公司对象
        business_type: 业务类型（SALES_OUT/PURCHASE_IN）
        party_id: 系统客商ID（Customer 或 Supplier）
        date_from: 起始日期
        date_to: 结束日期
        amount_min: 最小金额（可选）
        amount_max: 最大金额（可选）
        limit: 最大返回数

    Returns:
        list[dict]: 候选明细列表
    """
    # 找到该系统客商的所有金蝶映射
    if business_type == BusinessType.SALES_OUT:
        mappings = KingdeePartyMapping.objects.filter(
            company=company,
            party_type=KingdeePartyMapping.PartyType.CUSTOMER,
            customer_id=party_id,
            match_status__in=[
                KingdeePartyMapping.MatchStatus.AUTO,
                KingdeePartyMapping.MatchStatus.MANUAL,
            ]
        )
    else:
        mappings = KingdeePartyMapping.objects.filter(
            company=company,
            party_type=KingdeePartyMapping.PartyType.SUPPLIER,
            supplier_id=party_id,
            match_status__in=[
                KingdeePartyMapping.MatchStatus.AUTO,
                KingdeePartyMapping.MatchStatus.MANUAL,
            ]
        )

    k3_numbers = list(mappings.values_list("k3_number", flat=True))

    if not k3_numbers:
        return []

    # 查询未关联或部分分摊的明细
    qs = StockTransactionLine.objects.filter(
        transaction__company=company,
        transaction__business_type=business_type,
        transaction__is_active=True,
        transaction__k3_party_number__in=k3_numbers,
        transaction__biz_date__gte=date_from,
        transaction__biz_date__lte=date_to,
    ).select_related("transaction")

    if amount_min is not None:
        qs = qs.filter(amount__gte=Decimal(str(amount_min)))
    if amount_max is not None:
        qs = qs.filter(amount__lte=Decimal(str(amount_max)))

    # 计算已分摊金额
    qs = qs.annotate(
        allocated_total=Sum("daily_report_links__allocated_amount")
    )

    # 只返回未完全分摊的
    results = []
    for line in qs[:limit]:
        allocated = line.allocated_total or Decimal("0")
        remaining = line.amount - allocated
        if remaining > 0:
            results.append({
                "line_id": line.id,
                "bill_no": line.transaction.bill_no,
                "biz_date": line.transaction.biz_date.isoformat(),
                "material_name": line.material_name,
                "amount": float(line.amount),
                "allocated_amount": float(allocated),
                "remaining_amount": float(remaining),
            })

    return results
