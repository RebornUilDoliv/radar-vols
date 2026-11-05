import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import radar
import world

TODAY = date(2026, 11, 5)
SITE = {"marker": "1", "project": "2", "program": "3", "campaign": "4"}


def fare(code, price, ahead=30):
    depart = TODAY + timedelta(days=ahead)
    return radar.Offer(destination=code, price=price, depart=depart, back=depart + timedelta(days=5))


class WorldTests(unittest.TestCase):
    def test_keeps_cheapest_price_per_destination(self):
        rows = world.best_routes("LON", [fare("TYO", 700), fare("TYO", 500)], {"TYO": {}}, SITE, TODAY)
        self.assertEqual([(r["from"], r["to"], r["price"]) for r in rows], [("LON", "TYO", 500)])
        self.assertIn("tp.media", rows[0]["link"])

    def test_ignores_origin_unknown_cities_and_past_trips(self):
        rows = world.best_routes("LON", [fare("LON", 10), fare("ZZZ", 10), fare("TYO", 10, -1)], {"LON": {}, "TYO": {}}, SITE, TODAY)
        self.assertEqual(rows, [])

    def test_recent_file_is_not_refreshed(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "world.json"
            now = datetime(2026, 11, 5, tzinfo=timezone.utc)
            self.assertFalse(world.is_recent(path, now))
            path.write_text('{"updated":"2026-11-04T23:00+00:00"}')
            self.assertTrue(world.is_recent(path, now))
            self.assertFalse(world.is_recent(path, now + timedelta(days=1)))


if __name__ == "__main__":
    unittest.main()
