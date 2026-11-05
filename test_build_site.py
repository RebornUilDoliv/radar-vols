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
            places = {"PAR": {"name": "Paris", "country": "FR", "airports": ["CDG"]},
                      "BCN": {"name": "Barcelone", "country": "ES", "airports": ["BCN"]},
                      "ZZZ": {"name": "Sans vol", "country": "FR", "airports": []}}
            english = dict(places, BCN={"name": "Barcelona", "country": "ES", "airports": ["BCN"]})
            build_site.build(data, SITE, {"fr": (places, {"FR": "France"}), "en": (english, {"FR": "France"}), "es": (places, {"FR": "Francia"})})
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
        self.assertNotIn("<script>x<", (docs / "index.html").read_text())
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
        self.assertEqual(json.loads((docs / "assets" / "cities-fr.json").read_text())[-1], ["PAR", "Paris", "France"])

    def test_booking_page_is_hidden_from_search(self):
        docs = self.build([offer("BCN", "Barcelone", "Europe", 43, 30)])
        page = (docs / "test-reservation" / "index.html").read_text()
        self.assertIn('content="noindex, nofollow"', page)
        self.assertIn("Aucun vrai vol", page)
        self.assertNotIn("test-reservation", (docs / "sitemap.xml").read_text())
        self.assertIn(">Réservation test<", (docs / "index.html").read_text())

    def test_languages_stay_on_site(self):
        docs = self.build([offer("BCN", "Barcelone", "Europe", 43, 30)])
        english = (docs / "en" / "index.html").read_text()
        self.assertIn('<html lang="en">', english)
        self.assertIn("Your next flight starts here.", english)
        self.assertIn("Barcelona", english)
        self.assertIn("€43", english)
        self.assertIn('hreflang="es"', english)
        self.assertIn("Vuelos París – Barcelone", (docs / "es/destinations/barcelone/index.html").read_text())
        self.assertIn("/en/vols/", (docs / "sitemap.xml").read_text())
        self.assertEqual(json.loads((docs / "en/prices.json").read_text())["offers"][0]["city"], "Barcelona")

    def test_destination_links_to_hotels_and_activities(self):
        docs = self.build([offer("BCN", "Barcelone", "Europe", 43, 30)])
        page = (docs / "en/destinations/barcelone/index.html").read_text()
        self.assertIn("booking.com/searchresults.en-gb.html?ss=Barcelona", page)
        self.assertIn("tp.media/r?", page)
        self.assertIn("campaign_id=89", page)
        self.assertIn("tiqets.com%2Fen%2Fsearch%3Fq%3DBarcelona", page)

    def test_partner_program_wraps_stay_links(self):
        site = dict(SITE, root="/", version="1", hotels_program="111", hotels_campaign="222", url="https://x.test/")
        html = build_site.stay_links(build_site.Page(site, "fr"), "São Paulo")
        self.assertIn("tp.media/r?", html)
        self.assertIn("p=111", html)
        self.assertIn("campaign_id=222", html)

    def test_slug_removes_accents(self):
        self.assertEqual(build_site.slug("Montréal – Dorval"), "montreal-dorval")


if __name__ == "__main__":
    unittest.main()
