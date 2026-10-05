"""日报关联视图：为销售/采购日报提供金蝶明细检索、选单、分摊接口。

接口规范：
- GET/POST /integrations/search-kingdee-lines/: 检索金蝶明细
  （前端表单用 GET 查询串；也兼容 POST JSON body）
- POST /integrations/suggest-historical-matches/: 历史候选确认
- GET /integrations/daily-links/{report_type}/{report_id}/: 读取日报已关联明细
- DELETE /integrations/daily-links/{report_type}/{report_id}/: 解除关联
- 日报与关联的保存由日报表单提交（隐藏字段 kingdee_links）完成，无独立接口
"""

import json
import logging
from decimal import Decimal

from django.contrib.auth.decorators import login_required
from django.db.models import Sum
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods

from core.services.permissions import can_access_purchase, can_access_sales, is_read_only
from integrations.models import DailyReportKingdeeLink
from integrations.services.daily_link import (
    remove_links,
    save_daily_with_links,
    search_kingdee_lines,
    suggest_historical_matches,
)
from purchase.models import PurchaseReceipt
from sales.models import SalesShipment

logger = logging.getLogger("integrations")


def _company_access_denied(user, company, business_type):
    """按业务类型校验用户对公司的访问权限，越权时返回 403 响应，通过返回 None。"""
    allowed = (
        can_access_sales(user, company)
        if business_type == "SALES_OUT"
        else can_access_purchase(user, company)
    )
    if not allowed:
        return JsonResponse({"ok": False, "error": "无权访问该公司数据"}, status=403)
    return None


def _as_bool(value) -> bool:
    """查询参数布尔值兼容：GET 传字符串，JSON 传真布尔，缺省开启。"""
    if isinstance(value, bool):
        return value
    if value is None:
        return True
    return str(value).strip().lower() not in ("false", "0")


def _as_int(value, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


@login_required
def search_kingdee_lines_view(request):
    """检索金蝶明细行接口（前端 fetch 为 GET 查询串，也兼容 POST JSON body）。

    Request body / query:
        {
            "company_id": int,
            "business_type": "SALES_OUT" | "PURCHASE_IN",
            "bill_no": str (optional),
            "party_name": str (optional),
            "date_from": "YYYY-MM-DD" (optional),
            "date_to": "YYYY-MM-DD" (optional),
            "material_name": str (optional),
            "only_recent": bool (optional, default: true),
            "limit": int (optional, default: 100)
        }

    Response:
        {
            "ok": true,
            "lines": [
                {
                    "line_id": int,
                    "entry_id": str,
                    "bill_no": str,
                    "biz_date": "YYYY-MM-DD",
                    "k3_party_name": str,
                    "system_party_id": int | null,
                    "system_party_name": str | null,
                    "mapping_status": str | null,
                    "material_name": str,
                    "quantity": float,
                    "amount": float,
                    "allocated_amount": float,
                    "remaining_amount": float,
                    "over_allocated": float,
                    ...
                }
            ]
        }
    """
    try:
        from core.models import Company

        # 前端表单用 GET 查询串发起搜索；文档约定的 POST JSON body 也兼容
        if request.method == "POST":
            try:
                data = json.loads(request.body or "{}")
            except json.JSONDecodeError:
                return JsonResponse({"ok": False, "error": "请求体不是合法 JSON"}, status=400)
        else:
            data = request.GET.dict()

        company_id = data.get("company_id")
        business_type = data.get("business_type")

        if not company_id or not business_type:
            return JsonResponse({"ok": False, "error": "缺少必要参数"}, status=400)

        company = Company.objects.get(id=company_id)

        denied = _company_access_denied(request.user, company, business_type)
        if denied:
            return denied

        lines = search_kingdee_lines(
            company=company,
            business_type=business_type,
            query=data.get("query", ""),
            bill_no=data.get("bill_no", ""),
            party_name=data.get("party_name", ""),
            date_from=data.get("date_from", ""),
            date_to=data.get("date_to", ""),
            material_name=data.get("material_name", ""),
            only_recent=_as_bool(data.get("only_recent")),
            limit=_as_int(data.get("limit"), 100),
        )

        # 补充前端使用的字段别名（shipment_form/receipt_form 读取 party_name/allocated/remaining）
        for line in lines:
            line["party_name"] = line.get("system_party_name") or line.get("k3_party_name") or ""
            line["allocated"] = line.get("allocated_amount", 0)
            line["remaining"] = line.get("remaining_amount", 0)

        return JsonResponse({"ok": True, "lines": lines})

    except Company.DoesNotExist:
        return JsonResponse({"ok": False, "error": "公司不存在"}, status=404)
    except Exception as e:
        logger.exception("检索金蝶明细失败")
        return JsonResponse({"ok": False, "error": str(e)}, status=500)


@login_required
@require_http_methods(["POST"])
def suggest_historical_matches_view(request):
    """历史候选确认接口。

    Request body:
        {
            "company_id": int,
            "business_type": "SALES_OUT" | "PURCHASE_IN",
            "party_id": int,
            "date_from": "YYYY-MM-DD",
            "date_to": "YYYY-MM-DD",
            "amount_min": float (optional),
            "amount_max": float (optional),
            "limit": int (optional, default: 50)
        }

    Response:
        {
            "ok": true,
            "candidates": [...]
        }
    """
    try:
        from core.models import Company
        import json

        data = json.loads(request.body)
        company_id = data.get("company_id")
        business_type = data.get("business_type")
        party_id = data.get("party_id")
        date_from = data.get("date_from")
        date_to = data.get("date_to")

        if not all([company_id, business_type, party_id, date_from, date_to]):
            return JsonResponse({"ok": False, "error": "缺少必要参数"}, status=400)

        company = Company.objects.get(id=company_id)

        denied = _company_access_denied(request.user, company, business_type)
        if denied:
            return denied

        candidates = suggest_historical_matches(
            company=company,
            business_type=business_type,
            party_id=party_id,
            date_from=date_from,
            date_to=date_to,
            amount_min=data.get("amount_min"),
            amount_max=data.get("amount_max"),
            limit=data.get("limit", 50),
        )

        return JsonResponse({"ok": True, "candidates": candidates})

    except Company.DoesNotExist:
        return JsonResponse({"ok": False, "error": "公司不存在"}, status=404)
    except Exception as e:
        logger.exception("历史匹配失败")
        return JsonResponse({"ok": False, "error": str(e)}, status=500)


@login_required
def daily_links_view(request, report_type, report_id):
    """日报关联明细集合接口：GET 读取已关联明细，DELETE 解除关联。"""
    if request.method == "DELETE":
        return remove_daily_links_view(request, report_type, report_id)
    if request.method != "GET":
        return JsonResponse({"ok": False, "error": "不支持的请求方法"}, status=405)
    return _list_daily_links(request, report_type, report_id)


def _list_daily_links(request, report_type, report_id):
    """返回某张日报已关联的金蝶明细及分摊情况（前端 loadExistingLinks 使用）。"""
    try:
        rt = "SALES" if report_type.lower() == "sales" else "PURCHASE"
        if rt == "SALES":
            daily_report = SalesShipment.objects.get(id=report_id)
        else:
            daily_report = PurchaseReceipt.objects.get(id=report_id)

        biz_type = "SALES_OUT" if rt == "SALES" else "PURCHASE_IN"
        denied = _company_access_denied(request.user, daily_report.company, biz_type)
        if denied:
            return denied

        links = DailyReportKingdeeLink.objects.filter(report_type=rt).select_related(
            "transaction_line__transaction__party"
        )
        links = (
            links.filter(sales_shipment=daily_report)
            if rt == "SALES"
            else links.filter(purchase_receipt=daily_report)
        )

        out = []
        for lk in links:
            line = lk.transaction_line
            txn = line.transaction
            total_allocated = (
                DailyReportKingdeeLink.objects.filter(transaction_line=line)
                .aggregate(total=Sum("allocated_amount"))["total"]
                or Decimal("0")
            )
            system_name = None
            if txn.party:
                party = txn.party.customer if rt == "SALES" else txn.party.supplier
                system_name = party.name if party else None
            out.append({
                "id": lk.id,
                "line_id": line.id,
                "bill_no": txn.bill_no,
                "biz_date": txn.biz_date.isoformat(),
                "party_name": system_name or txn.k3_party_name,
                "material_name": line.material_name,
                "quantity": float(line.quantity),
                "unit": line.unit,
                "amount": float(line.amount),
                "total_allocated": float(total_allocated),
                "allocated_amount": float(lk.allocated_amount),
                "remaining": float(line.amount - total_allocated),
            })

        return JsonResponse({"ok": True, "links": out})

    except (SalesShipment.DoesNotExist, PurchaseReceipt.DoesNotExist):
        return JsonResponse({"ok": False, "error": "日报不存在"}, status=404)
    except Exception as e:
        logger.exception("读取日报关联失败")
        return JsonResponse({"ok": False, "error": str(e)}, status=500)


@login_required
@require_http_methods(["DELETE"])
def remove_daily_links_view(request, report_type, report_id):
    """解除日报关联接口。

    Args:
        report_type: "sales" | "purchase"
        report_id: 日报主键

    Query params:
        line_ids: 逗号分隔的明细ID，留空表示解除全部

    Response:
        {
            "ok": true,
            "removed": int
        }
    """
    try:
        report_type_upper = "SALES" if report_type.lower() == "sales" else "PURCHASE"

        if report_type_upper == "SALES":
            daily_report = SalesShipment.objects.get(id=report_id)
        else:
            daily_report = PurchaseReceipt.objects.get(id=report_id)

        # 只读角色不能变更关联（实施计划阶段 2 的权限边界）
        if is_read_only(request.user):
            return JsonResponse({"ok": False, "error": "只读角色不能变更关联"}, status=403)

        biz_type = "SALES_OUT" if report_type_upper == "SALES" else "PURCHASE_IN"
        denied = _company_access_denied(request.user, daily_report.company, biz_type)
        if denied:
            return denied

        line_ids_str = request.GET.get("line_ids", "")
        line_ids = [int(x.strip()) for x in line_ids_str.split(",") if x.strip()] if line_ids_str else None

        removed = remove_links(
            daily_report=daily_report,
            report_type=report_type_upper,
            line_ids=line_ids,
        )

        return JsonResponse({"ok": True, "removed": removed})

    except (SalesShipment.DoesNotExist, PurchaseReceipt.DoesNotExist):
        return JsonResponse({"ok": False, "error": "日报不存在"}, status=404)
    except Exception as e:
        logger.exception("解除关联失败")
        return JsonResponse({"ok": False, "error": str(e)}, status=500)
