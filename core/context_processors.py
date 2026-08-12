from core.services.permissions import can_access_purchase, can_access_sales, is_administrator


def navigation_permissions(request):
    return {
        "nav_is_administrator": is_administrator(request.user),
        "nav_can_sales": can_access_sales(request.user) if request.user.is_authenticated else False,
        "nav_can_purchase": can_access_purchase(request.user) if request.user.is_authenticated else False,
    }
