from django.contrib.auth.models import Group, User
from django.db.models import Q

from core.models import UserProfile
from core.services.audit import record_audit
from core.services.companies import grant_company_access
from core.services.permissions import is_administrator


ROLE_LABELS = {
    "administrator": "管理员",
    "sales": "销售",
    "purchase": "采购",
    "report_viewer": "报表查看者",
}
ROLE_NAMES = tuple(ROLE_LABELS)
ROLE_CHOICES = tuple(ROLE_LABELS.items())


def role_label(role_name):
    return ROLE_LABELS.get(role_name, role_name)


def normalize_roles(data):
    """角色是多选。保持 ROLE_LABELS 的顺序去重，让审计日志和界面展示口径一致。"""
    roles = data.get("roles") or []
    if isinstance(roles, str):
        roles = [roles]
    selected = set(roles)
    ordered = [name for name in ROLE_NAMES if name in selected]
    if not ordered:
        raise ValueError("至少需要选择一个角色")
    return ordered


def create_user_account(*, actor, data, action="CREATE"):
    if not is_administrator(actor):
        raise PermissionError("只有管理员可以创建用户")
    user = User.objects.create_user(
        username=data["username"],
        password=data["password"],
        first_name=data.get("first_name", ""),
    )
    roles = normalize_roles(data)
    user.groups.set(Group.objects.filter(name__in=roles))
    user.is_staff = "administrator" in roles
    user.save(update_fields=["is_staff"])
    companies = list(data.get("companies") or [])
    grant_company_access(user, companies)
    profile, _ = UserProfile.objects.get_or_create(user=user)
    profile.must_change_password = True
    profile.save(update_fields=["must_change_password"])
    record_audit(
        actor=actor,
        instance=user,
        action=action,
        before={},
        after={
            "username": user.username,
            "first_name": user.first_name,
            "roles": roles,
            "companies": [company.code for company in companies],
        },
    )
    return user


def reset_user_password(*, actor, user, password):
    if not is_administrator(actor):
        raise PermissionError("只有管理员可以重置密码")
    user.set_password(password)
    user.save(update_fields=["password"])
    profile, _ = UserProfile.objects.get_or_create(user=user)
    profile.must_change_password = True
    profile.save(update_fields=["must_change_password"])
    record_audit(actor=actor, instance=user, action="PASSWORD_RESET", before={}, after={"must_change_password": True})


def can_toggle_active(*, actor, user):
    """界面据此决定要不要显示停用按钮，与 set_user_active 的拒绝条件同一套规则。
    已停用的账号总是可以启用回来。"""
    if not is_administrator(actor):
        return False
    if not user.is_active:
        return True
    return user != actor and not _is_last_active_administrator(user)


def set_user_active(*, actor, user, is_active):
    """停用/启用账号。离职是日常动作，不该要求管理员会用 Django admin。

    停用而不是删除：日报的 owner/buyer 是 PROTECT，删账号会被数据库挡住，
    而且历史数据需要保留归属人。
    """
    if not is_administrator(actor):
        raise PermissionError("只有管理员可以停用或启用账号")
    if not is_active:
        if user == actor:
            raise PermissionError("不能停用自己的账号")
        if _is_last_active_administrator(user):
            raise PermissionError("这是最后一个启用的管理员账号，停用后就没人能管理系统了")
    if user.is_active == is_active:
        return user
    user.is_active = is_active
    user.save(update_fields=["is_active"])
    record_audit(
        actor=actor,
        instance=user,
        action="ACTIVATE" if is_active else "DEACTIVATE",
        before={"is_active": not is_active},
        after={"is_active": is_active},
    )
    return user


def _is_last_active_administrator(user):
    """superuser 也算管理员（见 permissions.is_administrator），两边都要数。"""
    if not is_administrator(user):
        return False
    others = User.objects.filter(is_active=True).exclude(pk=user.pk)
    return not others.filter(Q(is_superuser=True) | Q(groups__name="administrator")).exists()
