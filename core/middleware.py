from django.shortcuts import redirect
from django.urls import reverse

from core.models import UserProfile
from core.services.companies import active_company_for


class PasswordChangeRequiredMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated:
            profile, _ = UserProfile.objects.get_or_create(user=request.user)
            # 使用指南要放行，否则首次登录被困在改密页时看不了帮助。
            allowed = {reverse("core:password_change"), reverse("logout"), reverse("core:user_guide")}
            if profile.must_change_password and request.path not in allowed and not request.path.startswith("/static/"):
                return redirect("core:password_change")
        return self.get_response(request)


class ActiveCompanyMiddleware:
    """把当前登录会话选中的公司挂到 request.company，作为全站数据隔离入口。"""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.company = active_company_for(request) if request.user.is_authenticated else None
        return self.get_response(request)
