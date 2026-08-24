from django.urls import path

from purchase import views

app_name = "purchase"

urlpatterns = [
    path("receipts/", views.receipt_list, name="receipt_list"),
    path("receipts/new/", views.receipt_create, name="receipt_create"),
    path("receipts/<int:pk>/edit/", views.receipt_edit, name="receipt_edit"),
    path("receipts/<int:pk>/delete/", views.receipt_delete, name="receipt_delete"),
    path("imports/", views.import_page, name="import_page"),
    path("imports/preview/", views.import_preview, name="import_preview"),
    path("imports/commit/", views.import_commit, name="import_commit"),
    path("imports/errors/", views.import_errors_export, name="import_errors_export"),
]
