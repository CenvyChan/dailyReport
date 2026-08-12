from django.shortcuts import redirect
from django.urls import reverse

from core.models import UserProfile


class PasswordChangeRequiredMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated:
            profile, _ = UserProfile.objects.get_or_create(user=request.user)
            allowed = {reverse("core:password_change"), reverse("logout")}
            if profile.must_change_password and request.path not in allowed and not request.path.startswith("/static/"):
                return redirect("core:password_change")
        return self.get_response(request)
