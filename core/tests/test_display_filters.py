"""金额与数量的显示格式。

金额字段是 decimal_places=6、数量是 3，直接输出模型值会得到
534464.000000 和 120.000——六位小数全摊开、没有千分位，九列表格里
三列这样的数字根本没法纵向比对。存储保留精度是对的（外币折算需要），
只在显示层收敛。
"""

from decimal import Decimal

from django.test import SimpleTestCase

from core.templatetags.display import money, qty


class MoneyFilterTests(SimpleTestCase):
    def test_six_decimal_places_collapse_to_two(self):
        self.assertEqual(money(Decimal("534464.000000")), "534,464.00")

    def test_thousands_separators_are_added(self):
        self.assertEqual(money(Decimal("1234567890.126")), "1,234,567,890.13")

    def test_real_decimals_are_kept(self):
        self.assertEqual(money(Decimal("12345.670000")), "12,345.67")

    def test_rounding_is_half_up_not_bankers(self):
        """财务数字要确定的四舍五入。内置 round 对 .5 用银行家舍入，
        会把 0.005 变成 0.00。"""
        self.assertEqual(money(Decimal("0.005")), "0.01")
        self.assertEqual(money(Decimal("2.675")), "2.68")

    def test_negative_amounts_keep_their_sign(self):
        self.assertEqual(money(Decimal("-1234.5")), "-1,234.50")

    def test_zero_shows_two_decimals(self):
        self.assertEqual(money(Decimal("0.000000")), "0.00")

    def test_blank_values_render_as_empty(self):
        self.assertEqual(money(None), "")
        self.assertEqual(money(""), "")

    def test_unparseable_values_pass_through(self):
        """过滤器不该因为脏数据让整页 500。"""
        self.assertEqual(money("abc"), "abc")

    def test_plain_floats_and_ints_also_work(self):
        self.assertEqual(money(1500), "1,500.00")
        self.assertEqual(money(1500.5), "1,500.50")


class QtyFilterTests(SimpleTestCase):
    def test_trailing_zeros_are_dropped_for_whole_numbers(self):
        self.assertEqual(qty(Decimal("120.000")), "120")

    def test_real_decimals_are_kept(self):
        self.assertEqual(qty(Decimal("0.500")), "0.5")
        self.assertEqual(qty(Decimal("0.125")), "0.125")

    def test_thousands_separators_are_added(self):
        self.assertEqual(qty(Decimal("2500000.000")), "2,500,000")

    def test_zero_shows_as_zero(self):
        self.assertEqual(qty(Decimal("0.000")), "0")

    def test_blank_values_render_as_empty(self):
        self.assertEqual(qty(None), "")
        self.assertEqual(qty(""), "")

    def test_unparseable_values_pass_through(self):
        self.assertEqual(qty("abc"), "abc")

    def test_a_decimal_with_separators_keeps_both(self):
        self.assertEqual(qty(Decimal("1234.5")), "1,234.5")
