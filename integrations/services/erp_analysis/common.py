"""经营分析的纯计算原语；历史报告必须显式传入参照日期。"""

import calendar
import re
from collections import defaultdict
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

ZERO = Decimal(0)


def number(value):
    text = str(value if value is not None else "").strip().replace(",", "")
    if not text:
        return ZERO
    try:
        result = Decimal(text)
    except InvalidOperation as exc:
        raise ValueError(f"无法识别的数值：{text[:60]}") from exc
    if not result.is_finite():
        raise ValueError("经营分析不接受 NaN / Infinity")
    return result


def rounded(value, places=2):
    return number(value).quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)


def rate(numerator, denominator, *, undefined=None):
    return rounded(number(numerator) * 100 / number(denominator), 1) if number(denominator) else undefined


def parse_date(value):
    if isinstance(value, date):
        return date(value.year, value.month, value.day)
    match = re.match(r"^(\d{4})[-/](\d{1,2})[-/](\d{1,2})(?:$|[ T])", str(value or "").strip())
    if not match:
        return None
    try:
        return date(*map(int, match.groups()))
    except ValueError:
        return None


def month(value):
    return value.strftime("%Y-%m") if value else "未识别"


def period_window(period, months=12):
    if not isinstance(period, date) or not 1 <= months <= 36:
        raise ValueError("分析期间必须是日期，窗口须为 1 至 36 个月")
    end_index = period.year * 12 + period.month - 1
    result = []
    for index in range(end_index - months + 1, end_index + 1):
        year, month_index = divmod(index, 12)
        first = date(year, month_index + 1, 1)
        result.append((first, date(year, month_index + 1, calendar.monthrange(year, month_index + 1)[1])))
    return result


def reference_date(period):
    return period_window(period, 1)[0][1] + timedelta(days=1)


def total(rows, key):
    return sum((number(row.get(key)) for row in rows), ZERO)


def count_distinct(rows, key):
    return len({row.get(key) for row in rows if row.get(key)})


def groups(rows, key):
    result = defaultdict(list)
    for row in rows:
        result[row.get(key) or "未识别"].append(row)
    return result


def table(title, rows, columns, limit=None):
    return {
        "title": title,
        "headers": [label for _, label in columns],
        "rows": [[row.get(key) for key, _ in columns] for row in (rows[:limit] if limit else rows)],
        "total": len(rows),
    }


def cards(metrics, columns):
    return [{"label": label, "value": metrics.get(key), "suffix": suffix} for key, label, suffix in columns]


def report(metrics, summary_cards, sections, notes):
    return {"metrics": metrics, "cards": summary_cards, "sections": sections, "notes": notes}


def serializable(value):
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: serializable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [serializable(item) for item in value]
    return value
