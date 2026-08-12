from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path
from django.views.generic import RedirectView

from core.auth_views import FirstLoginView


urlpatterns = [
    path("", RedirectView.as_view(pattern_name="sales:shipment_list", permanent=False)),
    path("admin/", admin.site.urls),
    path("accounts/login/", FirstLoginView.as_view(), name="login"),
    path("accounts/logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("sales/", include("sales.urls")),
    path("api/sales/", include(("sales.urls", "sales"), namespace="sales_api")),
    path("purchase/", include("purchase.urls")),
    path("api/purchase/", include(("purchase.urls", "purchase"), namespace="purchase_api")),
    path("reports/", include("reports.urls")),
    path("core/", include("core.urls")),
]
