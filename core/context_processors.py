from core.services.companies import company_queryset_for
from core.services.permissions import (
    can_access_purchase,
    can_access_sales,
    can_view_comparison,
    is_administrator,
    is_read_only,
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
    company = getattr(request, "company", None)
    return {
        "nav_is_administrator": is_administrator(request.user),
        # 带上 company：绑定关系没有公司字段，不限定的话 A 公司的客户绑定会让这个人
        # 在 B 公司也看到销售菜单。
        "nav_can_sales": can_access_sales(request.user, company),
        "nav_can_purchase": can_access_purchase(request.user, company),
        # 对比表是全公司口径，门禁与 reports 视图共用同一条规则。
        "nav_can_comparison": can_view_comparison(request.user, company),
        "nav_is_read_only": is_read_only(request.user),
        "nav_company": company,
        "nav_companies": company_queryset_for(request.user),
    }
