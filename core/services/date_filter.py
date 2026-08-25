"""日报列表的日期筛选。

日报是每天录的，打开列表最常见的意图是「看今天录了什么」，所以默认只显示当天，
并提供前一天/后一天的翻页——这比每次手填两个日期快得多。

销售和采购两边完全同构，逻辑放这里共享，避免各写一套之后口径分叉。
"""

from datetime import date, datetime, timedelta

from django.utils import timezone

PRESETS = ("day", "week", "month", "year", "all")

# 默认本月而不是当天：日报不是每天都录（周末、假期、补录），线上数据就出现过
# 最近一条停在四天前的情况。默认当天时打开列表是一片空白，看起来像权限出了问题。
# 本月既能覆盖「今天录了什么」，又不会在没录的日子里给出空白页。
DEFAULT_PRESET = "month"


def parse_date(value):
    """非法日期当没填处理，不抛错——手改 URL 传进 start=abc 不该 500。"""
    if not value:
        return None
    if isinstance(value, date):
        return value
    try:
        return datetime.strptime(str(value).strip(), "%Y-%m-%d").date()
    except ValueError:
        return None


def preset_bounds(preset, today):
    """预设区间的起止。all 返回 (None, None) 表示不限。"""
    if preset == "day":
        return today, today
    if preset == "week":
        return today - timedelta(days=today.weekday()), today
    if preset == "month":
        return today.replace(day=1), today
    if preset == "year":
        return today.replace(month=1, day=1), today
    return None, None


def resolve(request, *, today=None):
    """算出本次列表要用的日期区间。

    优先级：显式的 start/end > preset > 默认区间。
    这个顺序很要紧：用户点了「前一天」传的是具体日期，此时不能再被 preset 顶掉。

    返回 dict，键：
      start / end   date 或 None，供 queryset 过滤
      preset        当前生效的预设名，供按钮高亮；手填日期时为 None
      prev_* / next_*  前后一天/一段的日期，供翻页按钮直接写进日期框
      label         人话描述当前口径，显示在筛选栏上
    """
    today = today or timezone.localdate()
    start = parse_date(request.GET.get("start"))
    end = parse_date(request.GET.get("end"))
    preset = request.GET.get("preset")

    if start or end:
        # 手填或翻页得到的具体区间，preset 不参与。
        # 只填了一头时补齐成单日，否则「前一天」会退化成开区间。
        preset = None
        if start and not end:
            end = start
        elif end and not start:
            start = end
        # 翻页：按当前区间长度整段前后移。放在服务端算而不是只靠 JS 改日期框，
        # 这样禁用脚本也能翻页。
        step = request.GET.get("step")
        if step in ("prev", "next"):
            span = (end - start).days + 1
            shift = timedelta(days=span if step == "next" else -span)
            start, end = start + shift, end + shift
    elif preset in PRESETS:
        start, end = preset_bounds(preset, today)
    elif preset is not None:
        # 传了个不认识的 preset（手改 URL），当没传，回到默认
        preset = DEFAULT_PRESET
        start, end = preset_bounds(preset, today)
    else:
        preset = DEFAULT_PRESET
        start, end = preset_bounds(preset, today)

    # 翻页步长跟随当前区间长度：看单日就翻一天，看一段就整段前后移。
    # 直接给出目标日期让按钮写进日期框，不再拼 URL——模板里 Django 会把 & 转义成
    # &amp;，参数名会变成 amp;end，等于 end 根本没传出去（真出过这个 bug）。
    span = None
    if start and end:
        span = (end - start).days + 1
    return {
        "start": start,
        "end": end,
        "preset": preset,
        "is_single_day": bool(span == 1),
        "span": span,
        "can_step": bool(span),
        "prev_start": (start - timedelta(days=span)) if span else None,
        "prev_end": (end - timedelta(days=span)) if span else None,
        "next_start": (start + timedelta(days=span)) if span else None,
        "next_end": (end + timedelta(days=span)) if span else None,
        "step_label": _step_label(span),
        "label": _label(start, end, today),
    }


def _step_label(span):
    """按钮上的提示文字，让用户知道点一下会移动多少。"""
    if not span:
        return ""
    if span == 1:
        return "一天"
    return f"{span} 天"


def _label(start, end, today):
    if not start and not end:
        return "全部日期"
    if start and end and start == end:
        if start == today:
            return f"今天（{start:%Y-%m-%d}）"
        if start == today - timedelta(days=1):
            return f"昨天（{start:%Y-%m-%d}）"
        return f"{start:%Y-%m-%d}"
    if start and end:
        return f"{start:%Y-%m-%d} 至 {end:%Y-%m-%d}"
    if start:
        return f"{start:%Y-%m-%d} 起"
    return f"截至 {end:%Y-%m-%d}"


def apply(queryset, resolved, *, field):
    """把区间套到 queryset 上。field 是日期字段名（shipment_date/purchase_date）。"""
    if resolved["start"]:
        queryset = queryset.filter(**{f"{field}__gte": resolved["start"]})
    if resolved["end"]:
        queryset = queryset.filter(**{f"{field}__lte": resolved["end"]})
    return queryset
