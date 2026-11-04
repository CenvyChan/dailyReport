from django.urls import path

from reports import views, views_erp_analysis

app_name = "reports"

urlpatterns = [
    path("erp-analysis/tasks/<int:task_id>/public/", views_erp_analysis.public_snapshot, name="erp_analysis_public"),
    path("erp-analysis/tasks/<int:task_id>/public/reports/<str:kind>/", views_erp_analysis.public_snapshot, name="erp_analysis_public_report"),
    path("erp-analysis/", views_erp_analysis.index, name="erp_analysis"),
    path("erp-analysis/generate/", views_erp_analysis.generate, name="erp_analysis_generate"),
    path("erp-analysis/tasks/<int:task_id>/", views_erp_analysis.task_detail, name="erp_analysis_task"),
    path("erp-analysis/tasks/<int:task_id>/status/", views_erp_analysis.task_status, name="erp_analysis_status"),
    path("erp-analysis/tasks/<int:task_id>/download/", views_erp_analysis.download, name="erp_analysis_download"),
    path("erp-analysis/tasks/<int:task_id>/reports/<str:kind>/", views_erp_analysis.report_view, name="erp_analysis_report"),
    path("sales/", views.sales_dashboard_view, name="sales_dashboard"),
    path("purchase/", views.purchase_dashboard_view, name="purchase_dashboard"),
    path("api/sales/", views.sales_dashboard_api, name="sales_dashboard_api"),
    path("api/purchase/", views.purchase_dashboard_api, name="purchase_dashboard_api"),
    path("sales/export/", views.sales_export, name="sales_export"),
    path("purchase/export/", views.purchase_export, name="purchase_export"),
    path("comparison/", views.monthly_comparison_view, name="monthly_comparison"),
    path("comparison/export/", views.monthly_comparison_export, name="monthly_comparison_export"),
]
