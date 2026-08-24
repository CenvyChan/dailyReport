from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from django import template

from core.services.naming import display_name

register = template.Library()


@register.filter(name="person")
def person(user):
    """模板里显示用户真实姓名：{{ item.owner|person }}。没填姓名时退回账号名。"""
    return display_name(user)


@register.filter(name="money")
def money(value):
    """金额显示成 534,464.00：两位小数 + 千分位。

    金额字段是 decimal_places=6，直接输出模型值会得到 534464.000000——
    六位小数全摊开、没有千分位，九列表格里三列这样的数字根本没法比对。
    存储保留六位是对的（外币折算需要精度），只在显示层收敛。

    用 Decimal.quantize 而不是内置 round：后者对 .5 用银行家舍入，
    财务数字要的是确定的四舍五入。
    """
    if value is None or value == "":
        return ""
    try:
        amount = Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except (InvalidOperation, TypeError, ValueError):
        return value
    return f"{amount:,.2f}"


@register.filter(name="qty")
def qty(value):
    """数量显示：整数不带小数，有小数才显示，最多三位。

    数量是 decimal_places=3，页面上「120.000」的尾零纯属噪音，
    但 0.5 这类小数必须保留，所以按需显示。
    """
    if value is None or value == "":
        return ""
    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return value
    whole = number.to_integral_value()
    if number == whole:
        return f"{whole:,.0f}"
    # normalize 会把 0.500 收成 0.5，但对 1E+2 这类也会变科学计数，
    # 所以先 quantize 到三位再去掉尾零。
    trimmed = str(number.quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)).rstrip("0").rstrip(".")
    integer, _, fraction = trimmed.partition(".")
    grouped = f"{Decimal(integer):,.0f}"
    return f"{grouped}.{fraction}" if fraction else grouped
