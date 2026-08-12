from django.urls import path

from core import views
from core.auth_views import RequiredPasswordChangeView

app_name = "core"

urlpatterns = [
    path("rates/", views.rate_list, name="rate_list"),
    path("rates/new/", views.rate_create, name="rate_create"),
    path("rates/<int:pk>/edit/", views.rate_edit, name="rate_edit"),
    path("users/", views.user_list, name="user_list"),
    path("users/new/", views.user_create, name="user_create"),
    path("users/<int:pk>/reset-password/", views.user_password_reset, name="user_password_reset"),
    path("users/imports/", views.user_import_page, name="user_import_page"),
    path("users/imports/preview/", views.user_import_preview, name="user_import_preview"),
    path("users/imports/commit/", views.user_import_commit, name="user_import_commit"),
    path("customers/imports/", views.customer_import_page, name="customer_import_page"),
    path("customers/imports/preview/", views.customer_import_preview, name="customer_import_preview"),
    path("customers/imports/commit/", views.customer_import_commit, name="customer_import_commit"),
    path("suppliers/imports/", views.supplier_import_page, name="supplier_import_page"),
    path("suppliers/imports/preview/", views.supplier_import_preview, name="supplier_import_preview"),
    path("suppliers/imports/commit/", views.supplier_import_commit, name="supplier_import_commit"),
    path("password/change/", RequiredPasswordChangeView.as_view(), name="password_change"),
]
