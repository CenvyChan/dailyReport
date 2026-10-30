import re

from django.contrib.auth.models import Group, User
from django.db.models import Q

from core.errors import UnresolvedImportPeople
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


PERSON_NAME_WHITESPACE = re.compile(r"[\s\u3000]+")


def normalize_person_name(value):
    """姓名/登录名归一化：去掉首尾和中间的空白（含全角空格）。

    源表里「张 三」「张三 」「张　三」都应指向同一个人。
    """
    return PERSON_NAME_WHITESPACE.sub("", str(value or ""))


def _match_people(names, provided=None):
    """把源表姓名匹配到账号，返回 (matched, unmatched, ambiguous)。

    优先级：显式映射 → 登录名 → 姓名（first_name）。登录名和姓名都索引
    在同一张表里，所以「许莹佳」既能命中 first_name=许莹佳 的 xuyingjia，
    也能命中 username=许莹佳 的历史账号。命中多个账号时不猜，交回调用方
    报歧义，避免把日报挂到错误的人名下。
    """
    provided = provided or {}
    index = {}
    for user in User.objects.order_by("id"):
        keys = {normalize_person_name(user.username), normalize_person_name(user.first_name)}
        for key in keys:
            if key:
                index.setdefault(key, []).append(user)

    matched = {}
    unmatched = []
    ambiguous = {}
    for name in sorted(set(names)):
        if name in provided:
            matched[name] = provided[name]
            continue
        candidates = {user.pk: user for user in index.get(normalize_person_name(name), [])}
        if len(candidates) == 1:
            matched[name] = next(iter(candidates.values()))
        elif len(candidates) > 1:
            ambiguous[name] = [
                f"{user.username}（{user.first_name}）" if user.first_name else user.username
                for user in candidates.values()
            ]
        else:
            unmatched.append(name)
    return matched, unmatched, ambiguous


def describe_import_people(names, *, provided=None):
    """预览用：只读地给出姓名解析结果，供导入页面提前展示。"""
    matched, unmatched, ambiguous = _match_people(names, provided)
    return {
        "matched": [
            {"name": name, "username": user.username, "first_name": user.first_name}
            for name, user in sorted(matched.items())
        ],
        "unmatched": unmatched,
        "ambiguous": [{"name": name, "candidates": candidates} for name, candidates in ambiguous.items()],
    }


def resolve_import_people(names, *, provided=None, create_missing=False):
    """正式导入用：把源表姓名解析成账号，解析不了就抛 UnresolvedImportPeople。

    create_missing 只给「管理员明确要求为新人建号」的场景用；建号时同时把
    姓名写进 first_name，下次导入才能按姓名匹配回来。默认 False，避免源表
    笔误或新姓名悄悄产生一批无法登录的账号。
    """
    matched, unmatched, ambiguous = _match_people(names, provided)
    if create_missing:
        for name in unmatched:
            matched[name] = User.objects.create(username=name, first_name=name)
        unmatched = []
    if unmatched or ambiguous:
        raise UnresolvedImportPeople(unmatched, ambiguous)
    return matched


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
