from django.urls import path

from sales import views

app_name = "sales"

urlpatterns = [
    path("shipments/", views.shipment_list, name="shipment_list"),
    path("shipments/new/", views.shipment_create, name="shipment_create"),
    path("shipments/<int:pk>/edit/", views.shipment_edit, name="shipment_edit"),
    path("shipments/<int:pk>/delete/", views.shipment_delete, name="shipment_delete"),
    path("customers/", views.customer_options, name="customer_options"),
    path("imports/", views.import_page, name="import_page"),
    path("imports/preview/", views.import_preview, name="import_preview"),
    path("imports/commit/", views.import_commit, name="import_commit"),
    path("imports/errors/", views.import_errors_export, name="import_errors_export"),
]
