from django.test import SimpleTestCase

from integrations.services.party_match import decide, score


class PartyMatchTests(SimpleTestCase):
    def test_exact_after_normalize_is_auto(self):
        status, resolved, cands = decide("新华书店有限公司", [(1, "新华书店"), (2, "完全无关商行")])
        self.assertEqual(status, "AUTO")
        self.assertEqual(resolved, 1)

    def test_substring_short_name_matches_full_name(self):
        # 系统侧简称是全称的子串
        self.assertGreaterEqual(score("华为", "华为技术有限公司"), 0.95)

    def test_multiple_candidates_go_pending(self):
        status, resolved, cands = decide(
            "华为技术有限公司", [(1, "华为"), (2, "华为科技"), (3, "无关公司")]
        )
        self.assertEqual(status, "PENDING")
        self.assertIsNone(resolved)
        self.assertGreaterEqual(len(cands), 2)

    def test_no_candidate_is_unmatched(self):
        status, resolved, cands = decide("上海某某贸易", [(1, "北京完全不同")])
        self.assertEqual(status, "UNMATCHED")
        self.assertEqual(cands, [])
