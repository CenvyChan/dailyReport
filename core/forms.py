import re
from datetime import date

from django import forms
from django.contrib.auth.forms import AuthenticationForm, PasswordChangeForm
from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError

from core.models import Company, Customer, ExchangeRate, Supplier
from core.services.companies import can_access_company
from core.services.users import ROLE_CHOICES


class CompanyAuthenticationForm(AuthenticationForm):
    company = forms.ModelChoiceField(
        label="公司",
        queryset=Company.objects.filter(is_active=True),
        empty_label=None,
        help_text="选择本次登录要进入的公司，登录后可在导航栏切换。",
    )

    field_order = ["company", "username", "password"]

    def clean(self):
        cleaned_data = super().clean()
        company = cleaned_data.get("company")
        user = self.get_user()
        if user is not None and company is not None and not can_access_company(user, company):
            raise forms.ValidationError("当前账号没有该公司的访问权限，请联系管理员授权")
        return cleaned_data


class MonthField(forms.DateField):
    """只让用户选年月（<input type="month"> 提交的是 2026-08），存库时补成当月 1 日。"""

    widget = forms.DateInput(attrs={"type": "month"}, format="%Y-%m")

    def to_python(self, value):
        if isinstance(value, str) and re.fullmatch(r"\d{4}-\d{1,2}", value.strip()):
            year, month = value.strip().split("-")
            try:
                return date(int(year), int(month), 1)
            except ValueError:
                raise forms.ValidationError("月份无效，请选择 2026-08 这样的年月") from None
        parsed = super().to_python(value)
        return parsed.replace(day=1) if parsed else parsed


class ExchangeRateForm(forms.ModelForm):
    month = MonthField(label="月份", help_text="只需选择年月，例如 2026-08；每个月只维护一条汇率。")

    class Meta:
        model = ExchangeRate
        fields = ["month", "usd_to_cny"]
        help_texts = {
            "usd_to_cny": "填写 1 美元可兑换的人民币金额，例如 7.1200。",
        }

    def __init__(self, *args, company, **kwargs):
        super().__init__(*args, **kwargs)
        self.company = company

    def clean_month(self):
        # MonthField 已经把日归一到 1 号，这里只查重。
        month = self.cleaned_data["month"]
        existing = ExchangeRate.objects.filter(company=self.company, month=month)
        if self.instance.pk:
            existing = existing.exclude(pk=self.instance.pk)
        if existing.exists():
            raise forms.ValidationError("该月份汇率已存在，请直接编辑原记录")
        return month


class UserCreateForm(forms.Form):
    username = forms.CharField(label="用户名", max_length=150, help_text="建议使用工号或姓名拼音，创建后不再重复使用。")
    first_name = forms.CharField(label="姓名", max_length=150, required=False)
    roles = forms.MultipleChoiceField(
        label="角色",
        choices=ROLE_CHOICES,
        widget=forms.CheckboxSelectMultiple,
        help_text="可多选。例如同时兼任销售和采购的人，勾选「销售」和「采购」两项。",
    )
    companies = forms.ModelMultipleChoiceField(
        label="可进入的公司",
        queryset=Company.objects.filter(is_active=True),
        widget=forms.CheckboxSelectMultiple,
        help_text="用户与角色在各公司之间共享，这里决定该账号登录时能选择哪几家公司。",
    )
    password = forms.CharField(
        label="初始密码",
        widget=forms.PasswordInput,
        help_text="至少 8 位，不能是纯数字或常见弱密码。此密码仅用于首次登录；用户首次登录后必须自行修改。",
    )

    def clean_username(self):
        username = self.cleaned_data["username"].strip()
        if User.objects.filter(username__iexact=username).exists():
            raise forms.ValidationError("用户名已存在，请更换后再保存")
        return username

    def clean_password(self):
        # AUTH_PASSWORD_VALIDATORS 只对 Django 自带的改密表单自动生效，
        # 管理员设初始密码这条路径要手工接上，否则能设成 "1"。
        return _validated_password(self.cleaned_data["password"])


class UserPasswordResetForm(forms.Form):
    password = forms.CharField(
        label="新初始密码",
        widget=forms.PasswordInput,
        help_text="至少 8 位，不能是纯数字或常见弱密码。重置后，用户下次登录会被要求自行修改密码。",
    )

    def clean_password(self):
        return _validated_password(self.cleaned_data["password"])


def _validated_password(password):
    try:
        validate_password(password)
    except ValidationError as error:
        raise forms.ValidationError(list(error.messages)) from None
    return password


class FirstLoginPasswordChangeForm(PasswordChangeForm):
    """首次登录顺带收集本人邮箱，否则后续没有地址可用于推送和通知。"""

    email = forms.EmailField(
        label="本人邮箱",
        help_text="用于接收日报推送和系统通知，请填写常用的公司邮箱。",
    )

    field_order = ["email", "old_password", "new_password1", "new_password2"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.user.email:
            self.fields["email"].initial = self.user.email

    def clean_email(self):
        email = self.cleaned_data["email"].strip()
        if User.objects.filter(email__iexact=email).exclude(pk=self.user.pk).exists():
            raise forms.ValidationError("该邮箱已被其他账号使用，请更换")
        return email

    def save(self, commit=True):
        user = super().save(commit=commit)
        user.email = self.cleaned_data["email"]
        if commit:
            user.save(update_fields=["email"])
        return user


class EmailChangeForm(forms.ModelForm):
    """让用户后续能自己改邮箱，不必找管理员。"""

    class Meta:
        model = User
        fields = ["email"]
        labels = {"email": "本人邮箱"}
        help_texts = {"email": "用于接收日报推送和系统通知。"}

    def clean_email(self):
        email = (self.cleaned_data.get("email") or "").strip()
        if not email:
            raise forms.ValidationError("邮箱不能为空")
        if User.objects.filter(email__iexact=email).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError("该邮箱已被其他账号使用，请更换")
        return email


class _NamedForm(forms.ModelForm):
    """客户/供应商共用：名称在同一公司内查重。"""

    def __init__(self, *args, company, **kwargs):
        super().__init__(*args, **kwargs)
        self.company = company

    def clean_name(self):
        name = self.cleaned_data["name"].strip()
        existing = self._meta.model.objects.filter(company=self.company, name=name)
        if self.instance.pk:
            existing = existing.exclude(pk=self.instance.pk)
        if existing.exists():
            raise forms.ValidationError("该名称在本公司已存在")
        return name


class CustomerForm(_NamedForm):
    class Meta:
        model = Customer
        fields = ["name", "is_active"]
        labels = {"name": "客户名称"}
        help_texts = {
            "name": "请使用公司统一的客户全称；同一公司内不能重复。",
            "is_active": "停用后保留历史数据，但不再出现在新增销售日报的候选里。",
        }


class SupplierForm(_NamedForm):
    class Meta:
        model = Supplier
        fields = ["name", "is_active"]
        labels = {"name": "供应商名称"}
        help_texts = {
            "name": "请使用公司统一的供应商全称；同一公司内不能重复。",
            "is_active": "停用后保留历史数据，但不再出现在新增采购日报的候选里。",
        }
