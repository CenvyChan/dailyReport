from datetime import date
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from core.models import ExchangeRate, OperationLog


class ExchangeRateViewTests(TestCase):
    def test_administrator_can_create_and_update_monthly_rate_with_audit(self):
        admin = User.objects.create_superuser("admin", password="pw")
        self.client.force_login(admin)

        response = self.client.post(
            reverse("core:rate_create"),
            {"month": "2026-08-01", "usd_to_cny": "7.1200"},
        )

        self.assertRedirects(response, reverse("core:rate_list"))
        rate = ExchangeRate.objects.get(month=date(2026, 8, 1))
        self.assertEqual(rate.usd_to_cny, Decimal("7.1200"))
        self.assertTrue(OperationLog.objects.filter(action="CREATE", object_id=str(rate.pk)).exists())

        response = self.client.post(
            reverse("core:rate_edit", args=[rate.pk]),
            {"month": "2026-08-01", "usd_to_cny": "7.2000"},
        )

        self.assertRedirects(response, reverse("core:rate_list"))
        rate.refresh_from_db()
        self.assertEqual(rate.usd_to_cny, Decimal("7.2000"))
        self.assertTrue(OperationLog.objects.filter(action="UPDATE", object_id=str(rate.pk)).exists())

    def test_non_administrator_cannot_open_rate_maintenance(self):
        user = User.objects.create_user("sales-a")
        self.client.force_login(user)

        response = self.client.get(reverse("core:rate_list"))

        self.assertEqual(response.status_code, 403)

    def test_duplicate_month_is_shown_as_friendly_form_error(self):
        admin = User.objects.create_superuser("admin", password="pw")
        ExchangeRate.objects.create(month=date(2026, 8, 1), usd_to_cny="7.1200")
        self.client.force_login(admin)

        response = self.client.post(
            reverse("core:rate_create"),
            {"month": "2026-08-01", "usd_to_cny": "7.2000"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "该月份汇率已存在，请直接编辑原记录")
