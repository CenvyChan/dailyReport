from datetime import date

from django.test import SimpleTestCase

from reports.services import preset_bounds


class ReportPresetTests(SimpleTestCase):
    def test_month_week_and_year_presets_use_inclusive_bounds(self):
        self.assertEqual(preset_bounds("month", date(2026, 8, 11)), (date(2026, 8, 1), date(2026, 8, 11)))
        self.assertEqual(preset_bounds("week", date(2026, 8, 11)), (date(2026, 8, 10), date(2026, 8, 11)))
        self.assertEqual(preset_bounds("year", date(2026, 8, 11)), (date(2026, 1, 1), date(2026, 8, 11)))
