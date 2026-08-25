"""列表页通用的搜索与分页。各列表页口径统一，避免每个视图各写一套。"""

from django.core.paginator import Paginator
from django.db.models import Q


PAGE_SIZE = 50
PAGE_SIZE_CHOICES = (20, 50, 100, 200)


def search_queryset(queryset, term, fields):
    """按多个字段做包含匹配。空搜索词原样返回。"""
    term = (term or "").strip()
    if not term:
        return queryset
    condition = Q()
    for field in fields:
        condition |= Q(**{f"{field}__icontains": term})
    return queryset.filter(condition)


def filter_by(queryset, request, mapping):
    """按下拉选择精确筛选。mapping 是 {查询参数名: 模型字段名}。

    比一个大文本框好用：负责人、客户、币种都是有限集合，选比打字准——
    打「高」会同时命中「高席」和「高新科技」，用户分不清自己筛到了什么。
    非法值当没筛选处理，不抛错（手改 URL 传进去不该 500）。
    """
    for param, field in mapping.items():
        value = (request.GET.get(param) or "").strip()
        if not value:
            continue
        if field.endswith("_id") and not value.isdigit():
            continue
        queryset = queryset.filter(**{field: value})
    return queryset


def field_search(request, queryset, specs):
    """按字段分别搜索，各条件之间是「且」。

    合成一个搜索框时无法表达「张三经手的美元单」这类组合，而且一个词同时去匹配
    客户名和人名会搜出无关记录（比如客户名里恰好含某个姓）。

    specs 是 [(参数名, [模型字段, ...]), ...]。取值为空的参数跳过。
    返回 (queryset, 回显用的取值字典)。
    """
    values = {}
    for param, fields in specs:
        term = (request.GET.get(param) or "").strip()
        values[param] = term
        if term:
            queryset = search_queryset(queryset, term, fields)
    return queryset, values


def paginate(request, queryset, *, default_size=PAGE_SIZE):
    """返回 (page, querystring)。querystring 已剔除 page（其余参数保留），
    供模板拼分页链接，这样翻页不会丢掉搜索条件、日期筛选和每页条数。

    当前每页条数挂在 page.current_size 上，可选值挂 page.size_choices，
    这样模板不用每个视图都额外传一遍。
    """
    size = _positive_int(request.GET.get("size"), default_size)
    if size not in PAGE_SIZE_CHOICES:
        size = default_size
    paginator = Paginator(queryset, size)
    page = paginator.get_page(request.GET.get("page"))
    page.current_size = size
    page.size_choices = PAGE_SIZE_CHOICES
    # 页码窗口：只有首页/上一页/下一页/末页时，要跳到第 7 页得连点六次。
    # elided_page_range 会在页数多时用省略号折叠中间部分。
    page.page_numbers = list(
        paginator.get_elided_page_range(page.number, on_each_side=2, on_ends=1)
    )
    page.elision = paginator.ELLIPSIS

    params = request.GET.copy()
    params.pop("page", None)
    return page, params.urlencode()


def _positive_int(value, fallback):
    try:
        number = int(value)
    except (TypeError, ValueError):
        return fallback
    return number if number > 0 else fallback
