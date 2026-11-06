import unittest
from datetime import date, datetime
from unittest import mock

import newsletter


class NewsletterTests(unittest.TestCase):
    def test_send_time_is_next_thursday_at_eight(self):
        now = datetime(2026, 11, 6, 10, tzinfo=newsletter.PARIS)
        self.assertEqual(newsletter.send_time(now), datetime(2026, 11, 12, 8, tzinfo=newsletter.PARIS))

    def test_thursday_after_eight_moves_to_next_week(self):
        now = datetime(2026, 11, 12, 9, tzinfo=newsletter.PARIS)
        self.assertEqual(newsletter.send_time(now).day, 19)

    def test_due_only_wednesday_evening_and_thursday_morning(self):
        self.assertFalse(newsletter.is_due({}, datetime(2026, 11, 11, 15, tzinfo=newsletter.PARIS)))
        self.assertTrue(newsletter.is_due({}, datetime(2026, 11, 11, 19, tzinfo=newsletter.PARIS)))
        self.assertFalse(newsletter.is_due({"last_newsletter": "2026-46"}, datetime(2026, 11, 11, 19, tzinfo=newsletter.PARIS)))
        self.assertFalse(newsletter.is_due({}, datetime(2026, 11, 12, 7, 50, tzinfo=newsletter.PARIS)))

    def test_picks_far_and_near_routes(self):
        origin = {"code": "PAR", "routes": [
            {"to": "LIS", "depart": "2027-01-10", "price": 50}, {"to": "TYO", "depart": "2027-01-10", "price": 500},
            {"to": "ROM", "depart": "2026-11-10", "price": 20},
        ]}
        geo = {"PAR": [48.8, 2.3], "LIS": [38.7, -9.1], "TYO": [35.6, 139.6], "ROM": [41.9, 12.4]}
        with mock.patch.object(newsletter.build_site, "photo_exists", return_value=True):
            far, near = newsletter.pick_routes(origin, geo, date(2026, 11, 6))
        self.assertEqual([r["to"] for r in far], ["TYO"])
        self.assertEqual([r["to"] for r in near], ["LIS"])


if __name__ == "__main__":
    unittest.main()
