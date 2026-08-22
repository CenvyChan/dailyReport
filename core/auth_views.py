from django.contrib import messages
from django.contrib.auth import views as auth_views
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden
from django.shortcuts import redirect, render
from django.urls import reverse_lazy
from django.utils.http import url_has_allowed_host_and_scheme

from core.forms import CompanyAuthenticationForm, EmailChangeForm, FirstLoginPasswordChangeForm
from core.models import Company, UserProfile
from core.responses import forbidden_page
from core.services.companies import can_access_company, set_active_company


class FirstLoginView(auth_views.LoginView):
    template_name = "registration/login.html"
    authentication_form = CompanyAuthenticationForm

    def form_valid(self, form):
        response = super().form_valid(form)
        set_active_company(self.request.session, form.cleaned_data["company"])
        profile, _ = UserProfile.objects.get_or_create(user=form.get_user())
        if profile.must_change_password:
            return redirect("core:password_change")
        return response


class RequiredPasswordChangeView(auth_views.PasswordChangeView):
    template_name = "core/password_change.html"
    form_class = FirstLoginPasswordChangeForm
    success_url = reverse_lazy("sales:shipment_list")

    def form_valid(self, form):
        response = super().form_valid(form)
        profile, _ = UserProfile.objects.get_or_create(user=self.request.user)
        profile.must_change_password = False
        profile.save(update_fields=["must_change_password"])
        return response


@login_required
def profile_edit(request):
    """让用户自己维护邮箱，不用每次找管理员。"""
    form = EmailChangeForm(request.POST or None, instance=request.user)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "邮箱已更新")
        return redirect("core:profile_edit")
    return render(request, "core/profile.html", {"form": form})


@login_required
def switch_company(request):
    """登录后在导航栏切换公司，越权直接拒绝而不是静默回退。"""
    if request.method != "POST":
        return HttpResponseForbidden("只允许使用 POST 请求切换公司")
    company_id = request.POST.get("company")
    company = Company.objects.filter(pk=company_id, is_active=True).first() if str(company_id).isdigit() else None
    if company is None or not can_access_company(request.user, company):
        return forbidden_page(request, "没有该公司的访问权限")
    set_active_company(request.session, company)
    target = request.POST.get("next") or "/"
    if not url_has_allowed_host_and_scheme(target, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        target = "/"
    return redirect(target)
