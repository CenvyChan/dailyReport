from django.contrib.auth.models import Group, User
from django.test import TestCase
from django.urls import reverse


class DomainAccessTests(TestCase):
    def test_report_viewer_can_view_reports_but_not_data_entry(self):
        user = User.objects.create_user("viewer")
        user.groups.add(Group.objects.get(name="report_viewer"))
        self.client.force_login(user)

        self.assertEqual(self.client.get(reverse("reports:sales_dashboard")).status_code, 200)
        self.assertEqual(self.client.get(reverse("sales:shipment_list")).status_code, 403)
        self.assertEqual(self.client.get(reverse("purchase:receipt_list")).status_code, 403)

    def test_sales_role_cannot_open_purchase_entry(self):
        user = User.objects.create_user("sales-a")
        user.groups.add(Group.objects.get(name="sales"))
        self.client.force_login(user)

        self.assertEqual(self.client.get(reverse("sales:shipment_list")).status_code, 200)
        self.assertEqual(self.client.get(reverse("purchase:receipt_list")).status_code, 403)
