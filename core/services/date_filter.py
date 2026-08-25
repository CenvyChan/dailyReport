"""日报列表的日期筛选。

日报是每天录的，打开列表最常见的意图是「看今天录了什么」，所以默认只显示当天，
并提供前一天/后一天的翻页——这比每次手填两个日期快得多。

销售和采购两边完全同构，逻辑放这里共享，避免各写一套之后口径分叉。
"""

from datetime import date, datetime, timedelta

from django.utils import timezone

PRESETS = ("day", "week", "month", "year", "all")
DEFAULT_PRESET = "day"


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

    优先级：显式的 start/end > preset > 默认当天。
    这个顺序很要紧：用户点了「前一天」传的是具体日期，此时不能再被 preset 顶掉。

    返回 dict，键：
      start / end   date 或 None，供 queryset 过滤
      preset        当前生效的预设名，供按钮高亮；手填日期时为 None
      prev_day / next_day   单日模式下的前后一天，供翻页链接
      is_single_day 是否单日模式（决定要不要显示翻页箭头）
      label         人话描述当前口径，显示在筛选栏上
    """
    today = today or timezone.localdate()
    start = parse_date(request.GET.get("start"))
    end = parse_date(request.GET.get("end"))
    preset = request.GET.get("preset")

    if start or end:
        # 手填或翻页得到的具体区间，preset 不参与
        preset = None
    elif preset in PRESETS:
        start, end = preset_bounds(preset, today)
    elif preset is not None:
        # 传了个不认识的 preset（手改 URL），当没传，回到默认
        preset = DEFAULT_PRESET
        start, end = preset_bounds(preset, today)
    else:
        # 首次进入：默认当天
        preset = DEFAULT_PRESET
        start, end = preset_bounds(preset, today)

    is_single_day = bool(start and end and start == end)
    prev_day = (start - timedelta(days=1)) if is_single_day else None
    next_day = (start + timedelta(days=1)) if is_single_day else None
    return {
        "start": start,
        "end": end,
        "preset": preset,
        "is_single_day": is_single_day,
        "prev_day": prev_day,
        "next_day": next_day,
        # 翻页链接在这里拼好：模板里手拼会漏掉 size 之类的参数，
        # 而直接用 paginate 的 querystring 又会让 start/end 重复出现。
        "prev_url": _day_url(request, prev_day),
        "next_url": _day_url(request, next_day),
        "label": _label(start, end, today),
    }


def _day_url(request, day):
    """保留其他查询参数，只改写 start/end/preset 到指定单日。"""
    if day is None:
        return None
    params = request.GET.copy()
    params.pop("page", None)
    stamp = day.isoformat()
    params["start"] = stamp
    params["end"] = stamp
    params["preset"] = ""
    return f"?{params.urlencode()}"


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
