from core.services.companies import company_queryset_for
from core.services.permissions import (
    can_access_purchase,
    can_access_sales,
    can_view_comparison,
    is_administrator,
)


def navigation_permissions(request):
    if not request.user.is_authenticated:
        return {
            "nav_is_administrator": False,
            "nav_can_sales": False,
            "nav_can_purchase": False,
            "nav_can_comparison": False,
            "nav_company": None,
            "nav_companies": [],
        }
    return {
        "nav_is_administrator": is_administrator(request.user),
        "nav_can_sales": can_access_sales(request.user),
        "nav_can_purchase": can_access_purchase(request.user),
        # 对比表是全公司口径，门禁与 reports 视图共用同一条规则。
        "nav_can_comparison": can_view_comparison(request.user),
        "nav_company": getattr(request, "company", None),
        "nav_companies": company_queryset_for(request.user),
    }
