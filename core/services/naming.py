"""用户展示名。单独成模块是为了避免 permissions ↔ users 循环导入
（users 依赖 permissions.is_administrator，permissions 又要用展示名）。"""


def display_name(user):
    """界面上一律显示真实姓名；没填姓名的老账号退回账号名，避免出现空白。
    登录仍然用 username（工号/拼音），这里只影响展示。"""
    if user is None:
        return ""
    return (user.first_name or "").strip() or user.username
