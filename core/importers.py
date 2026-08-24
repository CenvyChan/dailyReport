from dataclasses import dataclass

from django.contrib.auth.models import User
from django.db import transaction

from core.excel import is_blank, read_rows
from core.models import Customer, Supplier
from core.services.audit import record_audit
from core.services.permissions import is_administrator
from core.services.users import ROLE_NAMES, create_user_account


@dataclass(frozen=True)
class ImportPreview:
    valid_row_count: int
    error_rows: list[dict]
    rows: list[dict]


ROLE_ALIASES = {
    "管理员": "administrator",
    "销售": "sales",
    "采购": "purchase",
    "报表查看者": "report_viewer",
    **{name: name for name in ROLE_NAMES},
}
# 一个人可以兼多个角色，所以「角色」列允许写多个，用这些符号分隔。
ROLE_SEPARATORS = "、,，/;；|"


def parse_roles(value):
    """返回 (按 ROLE_NAMES 排序去重的角色列表, 第一个无法识别的原文)。"""
    text = str(value or "")
    for separator in ROLE_SEPARATORS:
        text = text.replace(separator, "\n")
    selected = set()
    for part in (part.strip() for part in text.split("\n")):
        if not part:
            continue
        role = ROLE_ALIASES.get(part)
        if role is None:
            return [], part
        selected.add(role)
    return [name for name in ROLE_NAMES if name in selected], None


def validate_named_rows(rows, *, field, aliases=None):
    aliases = aliases or (field,)
    valid_rows = []
    errors = []
    for row_number, row in enumerate(rows, start=2):
        value = next((row.get(alias) for alias in aliases if not is_blank(row.get(alias))), None)
        name = str(value).strip() if value is not None else ""
        if not name:
            errors.append({"row_number": row_number, "field": field, "message": "不能为空"})
        else:
            valid_rows.append({"row_number": row_number, "name": name})
    return ImportPreview(len(valid_rows), errors, valid_rows)


def validate_user_rows(rows):
    valid_rows = []
    errors = []
    for row_number, row in enumerate(rows, start=2):
        missing = next((field for field in ("用户名", "角色", "初始密码") if is_blank(row.get(field))), None)
        if missing:
            errors.append({"row_number": row_number, "field": missing, "message": "不能为空"})
            continue
        roles, invalid = parse_roles(row["角色"])
        if invalid:
            errors.append({"row_number": row_number, "field": "角色", "message": f"角色无效：{invalid}"})
            continue
        if not roles:
            errors.append({"row_number": row_number, "field": "角色", "message": "不能为空"})
            continue
        valid_rows.append(
            {
                "row_number": row_number,
                "username": str(row["用户名"]).strip(),
                "first_name": str(row.get("姓名", "") or "").strip(),
                "roles": roles,
                "password": str(row["初始密码"]),
            }
        )
    return ImportPreview(len(valid_rows), errors, valid_rows)


def _read_rows(path):
    return read_rows(path)


def preview_customer_import(path):
    return validate_named_rows(_read_rows(path), field="客户名称", aliases=("客户名称", "名称"))


def preview_supplier_import(path):
    return validate_named_rows(_read_rows(path), field="供应商名称", aliases=("供应商名称", "供应商", "名称"))


def preview_user_import(path):
    preview = validate_user_rows(_read_rows(path))
    errors = list(preview.error_rows)
    existing = set(User.objects.filter(username__in=[row["username"] for row in preview.rows]).values_list("username", flat=True))
    valid = []
    for row in preview.rows:
        if row["username"] in existing:
            errors.append({"row_number": row["row_number"], "field": "用户名", "message": "用户已存在"})
        else:
            valid.append(row)
    return ImportPreview(len(valid), errors, valid)


def _commit_named(preview, *, actor, company, model):
    if not is_administrator(actor):
        raise PermissionError("只有管理员可以导入基础资料")
    if preview.error_rows:
        raise ValueError("导入预览存在错误")
    with transaction.atomic():
        for row in preview.rows:
            instance, created = model.objects.get_or_create(
                company=company, name=row["name"], defaults={"is_active": True}
            )
            before = {} if created else {"name": instance.name, "is_active": instance.is_active}
            if not instance.is_active:
                instance.is_active = True
                instance.save(update_fields=["is_active"])
            record_audit(
                actor=actor,
                instance=instance,
                action="IMPORT",
                before=before,
                after={"company_id": company.pk, "name": instance.name, "is_active": True},
            )
    return preview.valid_row_count


def commit_customer_import(preview, *, actor, company):
    return _commit_named(preview, actor=actor, company=company, model=Customer)


def commit_supplier_import(preview, *, actor, company):
    return _commit_named(preview, actor=actor, company=company, model=Supplier)


def commit_user_import(preview, *, actor, company):
    if preview.error_rows:
        raise ValueError("导入预览存在错误")
    with transaction.atomic():
        for row in preview.rows:
            create_user_account(actor=actor, data={**row, "companies": [company]}, action="IMPORT")
    return preview.valid_row_count
