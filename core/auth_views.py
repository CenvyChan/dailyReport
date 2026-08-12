from django.contrib.auth import views as auth_views
from django.shortcuts import redirect
from django.urls import reverse, reverse_lazy

from core.models import UserProfile


class FirstLoginView(auth_views.LoginView):
    template_name = "registration/login.html"

    def form_valid(self, form):
        response = super().form_valid(form)
        profile, _ = UserProfile.objects.get_or_create(user=form.get_user())
        if profile.must_change_password:
            return redirect("core:password_change")
        return response


class RequiredPasswordChangeView(auth_views.PasswordChangeView):
    template_name = "core/password_change.html"
    success_url = reverse_lazy("sales:shipment_list")

    def form_valid(self, form):
        response = super().form_valid(form)
        profile, _ = UserProfile.objects.get_or_create(user=self.request.user)
        profile.must_change_password = False
        profile.save(update_fields=["must_change_password"])
        return response
