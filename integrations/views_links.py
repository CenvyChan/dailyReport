"""日报关联视图：为销售/采购日报提供金蝶明细检索、选单、分摊接口。

接口规范：
- POST /integrations/search-kingdee-lines/: 检索金蝶明细
- POST /integrations/suggest-historical-matches/: 历史候选确认
- POST /sales/shipments/{id}/save-with-links/: 保存销售日报与关联
- POST /purchase/receipts/{id}/save-with-links/: 保存采购日报与关联
- DELETE /integrations/daily-links/{report_type}/{report_id}/: 解除关联
"""

import logging
from decimal import Decimal

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods

from core.services.permissions import can_access_company
from integrations.services.daily_link import (
    remove_links,
    save_daily_with_links,
    search_kingdee_lines,
    suggest_historical_matches,
)
from purchase.models import PurchaseReceipt
from sales.models import SalesShipment

logger = logging.getLogger("integrations")


@login_required
@require_http_methods(["POST"])
def search_kingdee_lines_view(request):
    """检索金蝶明细行接口。

    Request body:
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
        import json

        data = json.loads(request.body)
        company_id = data.get("company_id")
        business_type = data.get("business_type")

        if not company_id or not business_type:
            return JsonResponse({"ok": False, "error": "缺少必要参数"}, status=400)

        company = Company.objects.get(id=company_id)

        if not can_access_company(request.user, company):
            return JsonResponse({"ok": False, "error": "无权访问该公司数据"}, status=403)

        lines = search_kingdee_lines(
            company=company,
            business_type=business_type,
            bill_no=data.get("bill_no", ""),
            party_name=data.get("party_name", ""),
            date_from=data.get("date_from", ""),
            date_to=data.get("date_to", ""),
            material_name=data.get("material_name", ""),
            only_recent=data.get("only_recent", True),
            limit=data.get("limit", 100),
        )

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

        if not can_access_company(request.user, company):
            return JsonResponse({"ok": False, "error": "无权访问该公司数据"}, status=403)

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

        if not can_access_company(request.user, daily_report.company):
            return JsonResponse({"ok": False, "error": "无权访问该公司数据"}, status=403)

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
