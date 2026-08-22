from django.urls import path

from notifications import views

app_name = "notifications"

urlpatterns = [
    path("", views.mailing_list_index, name="mailing_list_index"),
    path("new/", views.mailing_list_create, name="mailing_list_create"),
    path("<int:pk>/edit/", views.mailing_list_edit, name="mailing_list_edit"),
    path("<int:pk>/send/", views.mailing_list_send_now, name="mailing_list_send_now"),
]
