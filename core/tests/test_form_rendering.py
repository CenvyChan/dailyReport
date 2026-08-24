"""表单页的渲染结构。

此前五个表单页都是 form.as_p，标签、输入框、help_text 三者同字号同颜色
堆在一起，配上 form p { max-width: 360px } 全挤在一条窄列，也看不出哪些
字段必填。改成逐字段渲染后，这些测试锁住关键结构不再退化。
"""

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from core.templatetags.display import add_class
from core.testing import company_a, login_with_company


class AddClassFilterTests(TestCase):
    def test_the_filter_appends_without_dropping_existing_classes(self):
        """客户字段的 widget 本来带 list 属性，加 class 不能把它冲掉。"""
        from sales.forms import SalesShipmentForm

        admin = User.objects.create_superuser("admin", password="pw")
        form = SalesShipmentForm(user=admin, company=company_a())

        rendered = add_class(form["customer"], "num")

        self.assertIn('class="num"', rendered)
        self.assertIn('list="sales-customer-options"', rendered)


class FormPageStructureTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser("admin", password="pw")
        self.company = company_a()
        login_with_company(self.client, self.admin, self.company)

    def test_required_fields_are_marked(self):
        response = self.client.get(reverse("sales:shipment_create"))

        self.assertContains(response, 'class="req"')
        self.assertContains(response, "带 * 的为必填项")

    def test_help_text_is_rendered_as_its_own_element(self):
        """help_text 要能被单独降级样式，不能和标签同级同字号。"""
        response = self.client.get(reverse("sales:shipment_create"))

        self.assertContains(response, 'class="helptext"')

    def test_amount_and_quantity_inputs_are_right_aligned(self):
        """金额数量输入框用等宽右对齐，和列表页的显示口径一致。"""
        response = self.client.get(reverse("sales:shipment_create"))
        html = response.content.decode()

        self.assertIn('name="quantity"', html)
        # class="num" 必须落在数量和金额的 input 上
        self.assertEqual(html.count('class="num"'), 2)

    def test_the_currency_linkage_is_called_out_not_buried_in_help_text(self):
        """内外销决定币种和汇率，是新人最容易搞错的地方，
        此前埋在 sale_type 的 help_text 里和其他说明混在一起。"""
        response = self.client.get(reverse("sales:shipment_create"))

        self.assertContains(response, "inline-note")
        self.assertContains(response, "自动匹配汇率")

    def test_every_form_page_offers_a_way_back(self):
        """此前只有「保存」，填错了没有明确的退出路径。"""
        pages = [
            reverse("sales:shipment_create"),
            reverse("purchase:receipt_create"),
            reverse("core:user_create"),
            reverse("core:customer_create"),
            reverse("core:rate_create"),
        ]
        for url in pages:
            with self.subTest(url=url):
                response = self.client.get(url)

                self.assertEqual(response.status_code, 200)
                self.assertContains(response, "取消")
                self.assertContains(response, 'class="crumb"')

    def test_every_form_page_uses_the_card_layout(self):
        pages = [
            reverse("sales:shipment_create"),
            reverse("purchase:receipt_create"),
            reverse("core:user_create"),
            reverse("core:customer_create"),
            reverse("core:rate_create"),
        ]
        for url in pages:
            with self.subTest(url=url):
                response = self.client.get(url)

                self.assertContains(response, "form-card")
                # as_p 的痕迹应该没有了
                self.assertNotContains(response, "<p><label")

    def test_checkbox_groups_still_render_on_the_user_form(self):
        """角色和公司是 CheckboxSelectMultiple，循环渲染不能把它们漏掉。"""
        response = self.client.get(reverse("core:user_create"))

        self.assertContains(response, 'name="roles"')
        self.assertContains(response, 'name="companies"')

    def test_validation_errors_are_still_shown_per_field(self):
        """改成逐字段渲染后，字段级错误不能丢。"""
        response = self.client.post(reverse("core:rate_create"), {"month": "", "usd_to_cny": ""})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "errorlist")
