from django.urls import path

from integrations import views, views_links

app_name = "integrations"

urlpatterns = [
    path("reconciliation/", views.reconciliation_view, name="reconciliation"),
    path("reconciliation/export/", views.reconciliation_export, name="reconciliation_export"),
    path("stock/", views.stock_list_view, name="stock_list"),
    path("stock/<int:pk>/", views.stock_detail_view, name="stock_detail"),
    path("approvals/", views.approval_list_view, name="approval_list"),
    path("party-mapping/", views.party_mapping_view, name="party_mapping"),
    path("search-kingdee-lines/", views_links.search_kingdee_lines_view, name="search_kingdee_lines"),
    path("suggest-historical-matches/", views_links.suggest_historical_matches_view, name="suggest_historical_matches"),
    path("daily-links/<str:report_type>/<int:report_id>/", views_links.daily_links_view, name="daily_links"),
]
