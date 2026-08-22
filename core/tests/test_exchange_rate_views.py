from datetime import date
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from core.models import ExchangeRate, OperationLog
from core.testing import company_a, company_b, login_with_company


class ExchangeRateViewTests(TestCase):
    def test_administrator_can_create_and_update_monthly_rate_with_audit(self):
        admin = User.objects.create_superuser("admin", password="pw")
        login_with_company(self.client, admin, company_a())

        response = self.client.post(
            reverse("core:rate_create"),
            {"month": "2026-08", "usd_to_cny": "7.1200"},
        )

        self.assertRedirects(response, reverse("core:rate_list"))
        rate = ExchangeRate.objects.get(company=company_a(), month=date(2026, 8, 1))
        self.assertEqual(rate.usd_to_cny, Decimal("7.1200"))
        self.assertTrue(OperationLog.objects.filter(action="CREATE", object_id=str(rate.pk)).exists())

        response = self.client.post(
            reverse("core:rate_edit", args=[rate.pk]),
            {"month": "2026-08", "usd_to_cny": "7.2000"},
        )

        self.assertRedirects(response, reverse("core:rate_list"))
        rate.refresh_from_db()
        self.assertEqual(rate.usd_to_cny, Decimal("7.2000"))
        self.assertTrue(OperationLog.objects.filter(action="UPDATE", object_id=str(rate.pk)).exists())

    def test_non_administrator_cannot_open_rate_maintenance(self):
        user = User.objects.create_user("sales-a")
        login_with_company(self.client, user, company_a())

        response = self.client.get(reverse("core:rate_list"))

        self.assertEqual(response.status_code, 403)

    def test_duplicate_month_is_shown_as_friendly_form_error(self):
        admin = User.objects.create_superuser("admin", password="pw")
        ExchangeRate.objects.create(company=company_a(), month=date(2026, 8, 1), usd_to_cny="7.1200")
        login_with_company(self.client, admin, company_a())

        response = self.client.post(
            reverse("core:rate_create"),
            {"month": "2026-08", "usd_to_cny": "7.2000"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "该月份汇率已存在，请直接编辑原记录")

    def test_the_same_month_is_accepted_again_under_another_company(self):
        admin = User.objects.create_superuser("admin", password="pw")
        ExchangeRate.objects.create(company=company_a(), month=date(2026, 8, 1), usd_to_cny="7.1200")
        login_with_company(self.client, admin, company_b())

        response = self.client.post(
            reverse("core:rate_create"),
            {"month": "2026-08", "usd_to_cny": "7.3000"},
        )

        self.assertRedirects(response, reverse("core:rate_list"))
        self.assertEqual(
            ExchangeRate.objects.get(company=company_b(), month=date(2026, 8, 1)).usd_to_cny,
            Decimal("7.3000"),
        )

    def test_rate_list_only_shows_the_active_company(self):
        admin = User.objects.create_superuser("admin", password="pw")
        ExchangeRate.objects.create(company=company_a(), month=date(2026, 7, 1), usd_to_cny="7.0000")
        ExchangeRate.objects.create(company=company_b(), month=date(2026, 8, 1), usd_to_cny="7.5000")
        login_with_company(self.client, admin, company_a())

        response = self.client.get(reverse("core:rate_list"))

        self.assertContains(response, "7.0000")
        self.assertNotContains(response, "7.5000")

    def test_month_only_input_is_stored_as_the_first_day(self):
        admin = User.objects.create_superuser("admin", password="pw")
        login_with_company(self.client, admin, company_a())

        self.client.post(reverse("core:rate_create"), {"month": "2026-03", "usd_to_cny": "6.9228"})

        self.assertEqual(ExchangeRate.objects.get(company=company_a()).month, date(2026, 3, 1))

    def test_form_uses_a_month_picker_and_prefills_year_month(self):
        admin = User.objects.create_superuser("admin", password="pw")
        rate = ExchangeRate.objects.create(company=company_a(), month=date(2026, 8, 1), usd_to_cny="6.8067")
        login_with_company(self.client, admin, company_a())

        response = self.client.get(reverse("core:rate_edit", args=[rate.pk]))

        self.assertContains(response, 'type="month"')
        self.assertContains(response, 'value="2026-08"')

    def test_invalid_month_values_are_rejected_without_a_crash(self):
        admin = User.objects.create_superuser("admin", password="pw")
        login_with_company(self.client, admin, company_a())

        for bad in ("2026-13", "abc", "2026"):
            with self.subTest(month=bad):
                response = self.client.post(reverse("core:rate_create"), {"month": bad, "usd_to_cny": "7"})

                self.assertEqual(response.status_code, 200)
        self.assertFalse(ExchangeRate.objects.exists())

    def test_rate_from_another_company_cannot_be_edited(self):
        admin = User.objects.create_superuser("admin", password="pw")
        rate = ExchangeRate.objects.create(company=company_b(), month=date(2026, 8, 1), usd_to_cny="7.5000")
        login_with_company(self.client, admin, company_a())

        response = self.client.get(reverse("core:rate_edit", args=[rate.pk]))

        self.assertEqual(response.status_code, 404)
