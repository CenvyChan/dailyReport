from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path
from django.views.generic import RedirectView

from core.auth_views import FirstLoginView


urlpatterns = [
    path("", RedirectView.as_view(pattern_name="sales:shipment_list", permanent=False)),
    path("admin/", admin.site.urls),
    path("accounts/login/", FirstLoginView.as_view(), name="login"),
    # 必须显式指定 next_page，否则注销后会落在 Django admin 的注销页，
    # 那个模板的链接指向 /admin/，用户再登录就被带去后台而不是日报。
    path("accounts/logout/", auth_views.LogoutView.as_view(next_page="login"), name="logout"),
    path("sales/", include("sales.urls")),
    path("api/sales/", include(("sales.urls", "sales"), namespace="sales_api")),
    path("purchase/", include("purchase.urls")),
    path("api/purchase/", include(("purchase.urls", "purchase"), namespace="purchase_api")),
    path("reports/", include("reports.urls")),
    path("core/", include("core.urls")),
    path("core/notifications/", include("notifications.urls")),
]
