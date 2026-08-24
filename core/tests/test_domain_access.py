from django.contrib.auth.models import Group, User
from django.test import TestCase
from django.urls import reverse

from core.testing import company_a, login_with_company


class DomainAccessTests(TestCase):
    def test_report_viewer_can_read_both_business_lines(self):
        """report_viewer 要能看两条业务线的全部日报和报表，只是不能增删改。

        此前这两个列表页对它返回 403，而报表页虽然放行、数据却因为
        sales_queryset_for 按 owner 过滤而全是空的——它不会是任何日报的 owner。
        """
        user = User.objects.create_user("viewer")
        user.groups.add(Group.objects.get(name="report_viewer"))
        login_with_company(self.client, user, company_a())

        self.assertEqual(self.client.get(reverse("reports:sales_dashboard")).status_code, 200)
        self.assertEqual(self.client.get(reverse("sales:shipment_list")).status_code, 200)
        self.assertEqual(self.client.get(reverse("purchase:receipt_list")).status_code, 200)

    def test_sales_role_cannot_open_purchase_entry(self):
        user = User.objects.create_user("sales-a")
        user.groups.add(Group.objects.get(name="sales"))
        login_with_company(self.client, user, company_a())

        self.assertEqual(self.client.get(reverse("sales:shipment_list")).status_code, 200)
        self.assertEqual(self.client.get(reverse("purchase:receipt_list")).status_code, 403)

    def test_user_without_any_company_authorisation_is_blocked(self):
        user = User.objects.create_user("orphan")
        user.groups.add(Group.objects.get(name="sales"))
        self.client.force_login(user)

        response = self.client.get(reverse("sales:shipment_list"))

        self.assertEqual(response.status_code, 403)
        self.assertIn("没有可进入的公司", response.content.decode())
