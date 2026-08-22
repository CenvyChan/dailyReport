"""权限不足时的响应。

页面级视图用 forbidden_page()：套 base.html 渲染，用户能看到导航和说明，
而不是一段无处可去的裸文本（只能按浏览器后退）。

fetch 调用的接口继续用 HttpResponseForbidden 返回裸文本——那些地方前端
要读 body，给它 HTML 反而会解析失败。
"""

from django.shortcuts import render


def forbidden_page(request, message):
    """渲染 403.html。message 会显示给用户，要写成能照着做的中文。"""
    return render(request, "403.html", {"exception": message}, status=403)
