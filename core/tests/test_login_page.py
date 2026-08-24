"""登录页与首次改密页的呈现。

这两页走 base_auth.html 而不是 base.html：后者带导航栏和 1180px 的 main
容器，套在登录页上会让表单孤零零挂在左上角。
"""

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from core.models import CompanyMembership, UserProfile
from core.testing import company_a


class LoginPageLayoutTests(TestCase):
    def test_login_page_does_not_render_the_signed_in_navigation(self):
        """未登录时不该出现一整排点不动的导航项。"""
        response = self.client.get(reverse("login"))

        self.assertNotContains(response, "当前公司：")
        self.assertNotContains(response, "采销对比")

    def test_login_page_uses_the_auth_skeleton(self):
        response = self.client.get(reverse("login"))

        self.assertTemplateUsed(response, "base_auth.html")
        self.assertContains(response, "auth-split")
        self.assertContains(response, "auth-brand")

    def test_the_brand_side_shows_the_platform_name(self):
        response = self.client.get(reverse("login"))

        self.assertContains(response, "FINOSS 飞诺斯")
        self.assertContains(response, "采购销售日报")

    def test_all_three_fields_are_rendered_with_labels(self):
        """逐字段渲染（不用 form.as_p，那会套上 form p{max-width:360px}），
        所以要确认三个字段都在，且顺序是先选公司。"""
        response = self.client.get(reverse("login"))
        body = response.content.decode()

        self.assertIn('for="id_company"', body)
        self.assertIn('for="id_username"', body)
        self.assertIn('for="id_password"', body)
        self.assertLess(body.index("id_company"), body.index("id_username"))

    def test_required_fields_are_marked(self):
        response = self.client.get(reverse("login"))

        self.assertContains(response, 'class="req"')

    def test_the_company_help_text_is_shown(self):
        response = self.client.get(reverse("login"))

        self.assertContains(response, "登录后可在导航栏切换")


class LoginErrorTests(TestCase):
    def test_a_wrong_password_explains_itself_on_the_page(self):
        """非字段错误必须显示在表单上方，否则用户只觉得点了没反应。"""
        User.objects.create_user("someone", password="Correct@123")

        response = self.client.post(
            reverse("login"),
            {"company": company_a().pk, "username": "someone", "password": "wrong"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "errorlist")

    def test_logging_into_a_company_without_access_says_so(self):
        company = company_a()
        User.objects.create_user("outsider", password="Correct@123")

        response = self.client.post(
            reverse("login"),
            {"company": company.pk, "username": "outsider", "password": "Correct@123"},
        )

        self.assertContains(response, "没有该公司的访问权限")


class PasswordChangePageTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("newcomer", password="Initial@123")
        CompanyMembership.objects.create(user=self.user, company=company_a())
        UserProfile.objects.update_or_create(user=self.user, defaults={"must_change_password": True})
        self.client.force_login(self.user)

    def test_the_locked_page_does_not_offer_navigation_that_bounces_back(self):
        """用户此时已登录但被中间件锁在这一页，显示导航等于给出点了会被弹回的入口。"""
        response = self.client.get(reverse("core:password_change"))

        self.assertTemplateUsed(response, "base_auth.html")
        self.assertNotContains(response, "采销对比")

    def test_the_password_rules_render_as_a_list_not_escaped_markup(self):
        """Django 的密码规则 help_text 是一段 <ul>，逐字段渲染时若不放行
        HTML，页面上会出现可见的 &lt;ul&gt;&lt;li&gt;。"""
        response = self.client.get(reverse("core:password_change"))

        self.assertContains(response, "至少 8 个字符")
        self.assertNotContains(response, "&lt;ul&gt;")

    def test_the_email_field_comes_first(self):
        response = self.client.get(reverse("core:password_change"))
        body = response.content.decode()

        self.assertIn('for="id_email"', body)
        self.assertLess(body.index("id_email"), body.index("id_new_password1"))
