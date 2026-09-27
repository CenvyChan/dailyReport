from django.urls import path

from integrations import views

app_name = "integrations"

urlpatterns = [
    path("reconciliation/", views.reconciliation_view, name="reconciliation"),
    path("reconciliation/export/", views.reconciliation_export, name="reconciliation_export"),
    path("stock/", views.stock_list_view, name="stock_list"),
    path("stock/<int:pk>/", views.stock_detail_view, name="stock_detail"),
    path("approvals/", views.approval_list_view, name="approval_list"),
    path("party-mapping/", views.party_mapping_view, name="party_mapping"),
]
