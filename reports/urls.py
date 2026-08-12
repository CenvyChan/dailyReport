from django.urls import path

from reports import views

app_name = "reports"

urlpatterns = [
    path("sales/", views.sales_dashboard_view, name="sales_dashboard"),
    path("purchase/", views.purchase_dashboard_view, name="purchase_dashboard"),
    path("api/sales/", views.sales_dashboard_api, name="sales_dashboard_api"),
    path("api/purchase/", views.purchase_dashboard_api, name="purchase_dashboard_api"),
    path("sales/export/", views.sales_export, name="sales_export"),
    path("purchase/export/", views.purchase_export, name="purchase_export"),
]
