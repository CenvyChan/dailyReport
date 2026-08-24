"""模板的静态检查。

真实教训：Django 的 {# #} 是单行注释，不支持换行。写成跨行后，开头的 {#
找不到同行的 #}，整段注释会被当成纯文本渲染到页面上——登录页顶部因此显示
出一大段「不继承 base.html：那个模板带导航栏……」的开发者注释，用户直接
看得到。多行注释必须用 {% comment %}。
"""

from pathlib import Path

from django.test import SimpleTestCase

TEMPLATE_ROOT = Path(__file__).resolve().parents[2] / "templates"


def _templates():
    return sorted(TEMPLATE_ROOT.rglob("*.html"))


class TemplateCommentTests(SimpleTestCase):
    def test_no_single_line_comment_spans_multiple_lines(self):
        offenders = []
        for path in _templates():
            for number, line in enumerate(path.read_text(encoding="utf-8").split("\n"), 1):
                if "{#" not in line:
                    continue
                # 同一行里 {# 之后没有 #}，说明注释跨行了
                if "#}" not in line[line.index("{#"):]:
                    offenders.append(f"{path.relative_to(TEMPLATE_ROOT)}:{number}")

        self.assertEqual(
            offenders,
            [],
            "这些位置的 {# #} 跨了行，会被当成正文渲染给用户看。多行注释请改用 "
            "{% comment %}...{% endcomment %}：\n" + "\n".join(offenders),
        )

    def test_templates_exist_so_the_check_is_not_vacuous(self):
        """防止 glob 写错时这组测试变成空跑。"""
        self.assertGreater(len(_templates()), 15)


class TemplateTagBalanceTests(SimpleTestCase):
    def test_comment_tags_are_balanced(self):
        for path in _templates():
            body = path.read_text(encoding="utf-8")
            self.assertEqual(
                body.count("{% comment %}"),
                body.count("{% endcomment %}"),
                f"{path.relative_to(TEMPLATE_ROOT)} 的 comment/endcomment 不成对",
            )
