import json
import tempfile
import tomllib
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest import mock

import build_site

SITE = tomllib.loads((Path(__file__).parent / "config.toml").read_text())["site"]
TODAY = date.today()


def offer(code, city, region, price, ahead, history=None):
    depart = TODAY + timedelta(days=ahead)
    return {"city": city, "code": code, "region": region, "price": price, "usual": None,
            "depart": str(depart), "back": str(depart + timedelta(days=5)), "stops": 0,
            "link": "https://tp.media/r?u=x&y=1", "history": history or [[str(TODAY), price]]}


class BuildTests(unittest.TestCase):
    def build(self, offers):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        docs = Path(folder.name)
        (docs / "destinations" / "ancienne-ville").mkdir(parents=True)
        data = {"updated": "2026-11-04T14:40+00:00", "offers": offers}
        with mock.patch.object(build_site, "DOCS", docs):
            build_site.build(data, SITE, {"PAR": {"name": "Paris", "country": "FR", "airports": ["CDG"]},
                                          "ZZZ": {"name": "Sans vol", "country": "FR", "airports": []}}, {"FR": "France"})
        return docs

    def test_builds_all_pages_and_removes_old_destinations(self):
        docs = self.build([offer("BCN", "Barcelone", "Europe", 43, 30), offer("LON", "Londres", "Europe", 59, 200)])
        for page in ("index.html", "vols/index.html", "destinations/index.html", "a-propos/index.html",
                     "destinations/barcelone/index.html", "destinations/londres/index.html", "sitemap.xml", "robots.txt"):
            self.assertTrue((docs / page).exists(), page)
        self.assertFalse((docs / "destinations" / "ancienne-ville").exists())

    def test_sections_split_soon_and_ahead(self):
        home = (self.build([offer("BCN", "Barcelone", "Europe", 43, 30), offer("LON", "Londres", "Europe", 59, 200)]) / "index.html").read_text()
        self.assertLess(home.index("Partir bientôt"), home.index("Réserver à l'avance"))
        self.assertIn("Londres", home[home.index("Réserver à l'avance"):])

    def test_escapes_city_and_links(self):
        docs = self.build([offer("BAD", "<script>x", "Europe", 40, 30)])
        self.assertNotIn("<script>x", (docs / "index.html").read_text())
        self.assertIn("&amp;y=1", next((docs / "destinations").glob("*/index.html")).read_text())

    def test_home_links_stay_on_site(self):
        docs = self.build([offer("BCN", "Barcelone", "Europe", 43, 30)])
        home = (docs / "index.html").read_text()
        self.assertNotIn("tp.media", home)
        month = str(TODAY + timedelta(days=30))[:7]
        self.assertIn(f"destinations/barcelone/?mois={month}", home)
        self.assertIn(f'id="m-{month}"', (docs / "destinations/barcelone/index.html").read_text())

    def test_same_city_name_gets_unique_page(self):
        docs = self.build([offer("AAA", "Santiago", "Asie", 40, 30), offer("BBB", "Santiago", "Europe", 50, 30)])
        self.assertTrue((docs / "destinations" / "santiago-bbb" / "index.html").exists())

    def test_chart_needs_three_days(self):
        history = [[str(TODAY - timedelta(days=i)), 40 + i] for i in range(3)]
        docs = self.build([offer("BCN", "Barcelone", "Europe", 40, 30, history), offer("LON", "Londres", "Europe", 59, 30)])
        self.assertIn("data-history", (docs / "destinations/barcelone/index.html").read_text())
        self.assertNotIn("data-history", (docs / "destinations/londres/index.html").read_text())

    def test_city_list_keeps_only_cities_with_airports(self):
        docs = self.build([offer("BCN", "Barcelone", "Europe", 43, 30)])
        self.assertEqual(json.loads((docs / "assets" / "cities.json").read_text()), [["PAR", "Paris", "France"]])

    def test_booking_page_is_hidden_from_search(self):
        docs = self.build([offer("BCN", "Barcelone", "Europe", 43, 30)])
        page = (docs / "test-reservation" / "index.html").read_text()
        self.assertIn('content="noindex, nofollow"', page)
        self.assertIn("Aucun vrai vol", page)
        self.assertNotIn("test-reservation", (docs / "sitemap.xml").read_text())
        self.assertIn(">Test réservation<", (docs / "index.html").read_text())

    def test_slug_removes_accents(self):
        self.assertEqual(build_site.slug("Montréal – Dorval"), "montreal-dorval")


if __name__ == "__main__":
    unittest.main()
