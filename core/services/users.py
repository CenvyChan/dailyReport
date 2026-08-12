from django.contrib.auth.models import Group, User

from core.models import UserProfile
from core.services.audit import record_audit
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


def create_user_account(*, actor, data, action="CREATE"):
    if not is_administrator(actor):
        raise PermissionError("只有管理员可以创建用户")
    user = User.objects.create_user(
        username=data["username"],
        password=data["password"],
        first_name=data.get("first_name", ""),
    )
    role = Group.objects.get(name=data["role"])
    user.groups.set([role])
    user.is_staff = data["role"] == "administrator"
    user.save(update_fields=["is_staff"])
    profile, _ = UserProfile.objects.get_or_create(user=user)
    profile.must_change_password = True
    profile.save(update_fields=["must_change_password"])
    record_audit(
        actor=actor,
        instance=user,
        action=action,
        before={},
        after={"username": user.username, "first_name": user.first_name, "role": data["role"]},
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
