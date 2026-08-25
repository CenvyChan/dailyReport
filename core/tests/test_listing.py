"""列表页分页与查询。真实数据里销售日报有 4000+ 条，不分页页面会卡。"""

from datetime import date

from django.contrib.auth.models import Group, User
from django.test import TestCase
from django.urls import reverse

from core.models import Customer, SalesAssignment
from core.services.listing import search_queryset
from core.testing import company_a, login_with_company
from sales.models import SalesShipment


class SearchHelperTests(TestCase):
    def setUp(self):
        self.company = company_a()
        Customer.objects.create(company=self.company, name="上海某某")
        Customer.objects.create(company=self.company, name="北京某某")

    def test_blank_term_returns_everything(self):
        self.assertEqual(search_queryset(Customer.objects.all(), "", ("name",)).count(), 2)
        self.assertEqual(search_queryset(Customer.objects.all(), None, ("name",)).count(), 2)

    def test_whitespace_only_term_is_treated_as_blank(self):
        self.assertEqual(search_queryset(Customer.objects.all(), "   ", ("name",)).count(), 2)

    def test_term_matches_across_several_fields(self):
        user = User.objects.create_user("zhaoliu", first_name="赵六")
        SalesAssignment.objects.create(user=user, customer=Customer.objects.first())

        found = search_queryset(
            SalesAssignment.objects.all(), "赵六", ("user__first_name", "user__username")
        )

        self.assertEqual(found.count(), 1)

    def test_search_is_case_insensitive(self):
        Customer.objects.create(company=self.company, name="ABC Corp")

        self.assertEqual(search_queryset(Customer.objects.all(), "abc", ("name",)).count(), 1)


class ShipmentListPaginationTests(TestCase):
    def setUp(self):
        self.company = company_a()
        self.user = User.objects.create_superuser("admin", password="pw")
        self.user.groups.add(Group.objects.get(name="sales"))
        customer = Customer.objects.create(company=self.company, name="客户甲")
        SalesAssignment.objects.create(user=self.user, customer=customer)
        SalesShipment.objects.bulk_create(
            SalesShipment(
                company=self.company, customer=customer, owner=self.user,
                sale_type="DOMESTIC", shipment_date=date(2026, 8, 1 + index % 28),
                quantity="1", currency="CNY", original_amount="10",
                exchange_rate="1", amount_cny="10",
            )
            for index in range(120)
        )
        login_with_company(self.client, self.user, self.company)

    def test_first_page_shows_the_default_page_size(self):
        response = self.client.get(reverse("sales:shipment_list"), {"preset": "all"})

        self.assertEqual(len(response.context["page"].object_list), 50)
        self.assertEqual(response.context["page"].paginator.count, 120)

    def test_pagination_links_are_rendered(self):
        response = self.client.get(reverse("sales:shipment_list"), {"preset": "all"})

        self.assertContains(response, "下一页")
        self.assertContains(response, "共 120 条")

    def test_second_page_continues_the_list(self):
        response = self.client.get(reverse("sales:shipment_list"), {"preset": "all", "page": 2})

        self.assertEqual(response.context["page"].number, 2)

    def test_out_of_range_page_falls_back_to_the_last_page(self):
        response = self.client.get(reverse("sales:shipment_list"), {"preset": "all", "page": 999})

        self.assertEqual(response.context["page"].number, response.context["page"].paginator.num_pages)

    def test_garbage_page_value_does_not_crash(self):
        self.assertEqual(self.client.get(reverse("sales:shipment_list"), {"preset": "all", "page": "abc"}).status_code, 200)

    def test_date_range_filter_narrows_the_result(self):
        response = self.client.get(
            reverse("sales:shipment_list"), {"start": "2026-08-01", "end": "2026-08-02"}
        )

        dates = {row.shipment_date for row in response.context["page"].object_list}
        self.assertTrue(dates <= {date(2026, 8, 1), date(2026, 8, 2)})

    def test_querystring_keeps_filters_when_turning_pages(self):
        response = self.client.get(reverse("sales:shipment_list"), {"preset": "all", "q": "客户甲", "page": 2})

        self.assertIn("q=", response.context["querystring"])
        self.assertNotIn("page=", response.context["querystring"])


class PageSizeTests(TestCase):
    def setUp(self):
        self.company = company_a()
        self.user = User.objects.create_superuser("admin", password="pw")
        login_with_company(self.client, self.user, self.company)
        Customer.objects.bulk_create(
            Customer(company=self.company, name=f"客户{index:03d}") for index in range(60)
        )

    def test_supported_page_size_is_honoured(self):
        response = self.client.get(reverse("core:customer_list"), {"size": 20})

        self.assertEqual(len(response.context["page"].object_list), 20)

    def test_unsupported_page_size_falls_back_to_the_default(self):
        response = self.client.get(reverse("core:customer_list"), {"size": 7})

        self.assertEqual(len(response.context["page"].object_list), 50)

    def test_negative_or_garbage_size_falls_back(self):
        for value in ("-5", "abc", "0"):
            with self.subTest(size=value):
                response = self.client.get(reverse("core:customer_list"), {"size": value})
                self.assertEqual(len(response.context["page"].object_list), 50)
