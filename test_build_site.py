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
    def test_deals_page_lets_visitors_pick_a_departure_city(self):
        from types import SimpleNamespace
        page = SimpleNamespace(lang="fr", t=lambda key, **k: key, city=lambda code, name: {"PAR": "Paris", "NBO": "Nairobi"}[code])
        html = build_site.deals_picker(page, [{"code": "NBO"}, {"code": "PAR"}])
        self.assertIn('id="deals-origin"', html)
        self.assertIn('<option value="PAR" selected>Paris</option>', html)
        self.assertIn('<option value="NBO">Nairobi</option>', html)
        self.assertEqual(build_site.deals_picker(page, []), "")

    def test_city_without_photo_uses_one_from_its_country(self):
        from types import SimpleNamespace
        page = SimpleNamespace(countries={"cities": {"AAA": "FR", "BBB": "FR", "CCC": "JP"}})
        with mock.patch.object(build_site, "photo_exists", lambda code: code == "BBB"):
            self.assertEqual(build_site.cover_code(page, "BBB"), "BBB")
            self.assertEqual(build_site.cover_code(page, "AAA"), "BBB")
            self.assertEqual(build_site.cover_code(page, "CCC"), "")

    def test_destinations_never_show_the_same_photo_twice(self):
        from types import SimpleNamespace
        page = SimpleNamespace(lang="fr", root="/", base="/", site={"name": "Eunodia"}, countries={"cities": {"AAA": "FR", "BBB": "FR", "DDD": "FR"}},
                               t=lambda key, **k: key, city=lambda code, name: code, euro=lambda v: f"{v} €")
        places = [{"code": c, "slug": c.lower(), "routes": [({}, {"price": 50})]} for c in ("AAA", "BBB", "DDD")]
        with mock.patch.object(build_site, "photo_exists", lambda code: code == "BBB"), \
             mock.patch.object(build_site, "layout", lambda p, title, lead, path, body, **k: body):
            html = build_site.world_places_index(page, places, {c: "EU" for c in ("AAA", "BBB", "DDD")})
        self.assertEqual(html.count("photos/BBB.jpg"), 1)
        self.assertEqual(html.count('class="place"'), 3)

    def test_destination_page_has_unique_facts_and_faq(self):
        from types import SimpleNamespace
        from datetime import datetime, timezone
        names = {"PAR": "Paris", "TYO": "Tokyo", "LIS": "Lisbonne"}
        page = SimpleNamespace(lang="fr", geo={"PAR": [48.86, 2.35, "Europe/Paris"], "TYO": [35.68, 139.65, "Asia/Tokyo"]},
                               city=lambda code, name: names.get(code, name), euro=lambda v: f"{v} €", day=lambda iso, year=True: iso,
                               t=lambda key, **v: build_site.TEXT["fr"][key].format(**v) if v else build_site.TEXT["fr"][key])
        route = {"price": 512, "depart": "2026-12-01", "back": "2026-12-15"}
        place = {"code": "TYO", "routes": [({"code": "PAR"}, route), ({"code": "LIS"}, route)]}
        block, schema = build_site.place_facts(page, place, now=datetime(2026, 11, 8, tzinfo=timezone.utc))
        self.assertIn("Tokyo en bref", block)
        self.assertIn("512 € depuis Paris", block)
        self.assertIn("9 710 km", block)
        self.assertIn("+8 h par rapport à Paris", block)
        self.assertIn("2 villes, dont Paris, Lisbonne", block)
        self.assertIn('"FAQPage"', schema)
        self.assertIn("Combien coûte un vol pour Tokyo ?", schema)

    def test_old_partner_links_move_to_current_project(self):
        old = {"offers": [{"link": "https://tp.media/r?marker=1&trs=595480&p=4114&u=x"}], "other": "https://example.com/?trs=1"}
        new = build_site.retrack(old, "597805")
        self.assertEqual(new["offers"][0]["link"], "https://tp.media/r?marker=1&trs=597805&p=4114&u=x")
        self.assertEqual(new["other"], "https://example.com/?trs=1")

    def test_row_city_is_clickable_without_its_own_page(self):
        from types import SimpleNamespace
        page = SimpleNamespace(lang="fr", root="/", city=lambda code, name: "Pise", day=lambda *a: "19 nov.", t=lambda *a, **k: "Voir", stops=lambda r: "direct", euro=lambda v: f"{v} €")
        origin = {"code": "PAR", "slug": "paris", "pages": []}
        route = {"to": "PSA", "price": 37, "depart": "2026-11-19", "back": "2026-11-21", "link": "https://tp.media/r?x=1"}
        html = build_site.world_row(page, origin, route)
        self.assertIn('<h3><a href="https://tp.media/r?x=1" rel="nofollow sponsored noopener" target="_blank">Pise</a></h3>', html)

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

    def test_home_pages_offer_hotel_search_in_every_language(self):
        docs = self.build([offer("BCN", "Barcelone", "Europe", 43, 30)])
        fr = (docs / "index.html").read_text()
        self.assertIn('id="hotel-search"', fr)
        self.assertIn(">Hôtels</button>", fr)
        self.assertEqual(fr.count('id="hotel-search"'), 1)
        self.assertIn(">فنادق</button>", (docs / "ar" / "index.html").read_text())
        self.assertNotIn("noindex", fr)

    def test_builds_all_pages_and_removes_old_destinations(self):
        docs = self.build([offer("BCN", "Barcelone", "Europe", 43, 30), offer("LON", "Londres", "Europe", 59, 200)])
        for page in ("index.html", "vols/index.html", "destinations/index.html", "a-propos/index.html",
                     "destinations/barcelone/index.html", "destinations/londres/index.html", "sitemap.xml", "robots.txt"):
            self.assertTrue((docs / page).exists(), page)
        self.assertFalse((docs / "destinations" / "ancienne-ville").exists())

    def test_sections_split_soon_and_ahead(self):
        home = (self.build([offer("BCN", "Barcelone", "Europe", 43, 30), offer("LON", "Londres", "Europe", 59, 200)]) / "index.html").read_text()
        self.assertLess(home.index("Partir bientôt"), home.index("Réserver à l"))
        self.assertIn("Londres", home[home.index("Réserver à l"):])

    def test_escapes_city_and_links(self):
        docs = self.build([offer("BAD", "<script>x", "Europe", 40, 30)])
        self.assertNotIn("<script>x<", (docs / "index.html").read_text())
        self.assertIn("&amp;y=1", next((docs / "destinations").glob("*/index.html")).read_text())

    def test_home_links_stay_on_site(self):
        docs = self.build([offer("BCN", "Barcelone", "Europe", 43, 30)])
        home = (docs / "index.html").read_text()
        self.assertNotIn("tp.media", home.split('id="preparer"')[0])
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

    def test_languages_stay_on_site(self):
        docs = self.build([offer("BCN", "Barcelone", "Europe", 43, 30)])
        english = (docs / "en" / "index.html").read_text()
        self.assertIn('<html lang="en">', english)
        self.assertIn("Your next trip starts here.", english)
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
        self.assertIn("campaign_id=120", page)
        self.assertIn("airhelp.com%2Fen%2F", page)
        self.assertIn("campaign_id=541", page)
        self.assertIn("kiwitaxi.com%2Fen", page)

    def test_partner_program_wraps_stay_links(self):
        site = dict(SITE, root="/", version="1", hotels_program="111", hotels_campaign="222", url="https://x.test/")
        html = build_site.stay_links(build_site.Page(site, "fr"), "São Paulo")
        self.assertIn("tp.media/r?", html)
        self.assertIn("p=111", html)
        self.assertIn("campaign_id=222", html)

    def test_photo_credits_live_on_their_own_page(self):
        docs = self.build([offer("BCN", "Barcelone", "Europe", 43, 30)])
        self.assertTrue((docs / "credits" / "index.html").exists())
        self.assertIn("/credits/", (docs / "index.html").read_text())
        self.assertNotIn("figcaption", (docs / "destinations/barcelone/index.html").read_text())

    def test_newsletter_appears_once_configured(self):
        p = build_site.Page(dict(SITE, root="/", version="1", newsletter_url=""), "fr")
        self.assertEqual(build_site.newsletter_block(p), "")
        p = build_site.Page(dict(SITE, root="/", version="1", newsletter_url="https://form.test/x"), "es")
        block = build_site.newsletter_block(p)
        self.assertIn('action="https://form.test/x"', block)
        self.assertIn("required", block)
        self.assertIn("darme de baja", block)

    def test_guide_uses_measured_prices(self):
        docs = self.build([offer("BCN", "Barcelone", "Europe", 43, 30), offer("BCN", "Barcelone", "Europe", 90, 90)])
        page = (docs / "destinations/barcelone/index.html").read_text()
        self.assertIn("Quand partir à Barcelone", page)
        self.assertIn("43 €", page)
        self.assertIn("90 €", page)
        self.assertIn("campaign_id=87", page)

    def test_logo_is_in_header_and_footer(self):
        docs = self.build([offer("BCN", "Barcelone", "Europe", 43, 30)])
        self.assertEqual((docs / "index.html").read_text().count('class="mark"'), 2)

    def deals(self):
        return [offer("BCN", "Barcelone", "Europe", 43, 30), offer("LIS", "Lisbonne", "Europe", 60, 30),
                offer("ROM", "Rome", "Europe", 80, 30), offer("TYO", "Tokyo", "Asie", 480, 30)]

    def test_collections_need_three_cities(self):
        groups = build_site.collections(self.deals())
        slugs = {g["slug"] for g in groups}
        self.assertIn("europe", slugs)
        self.assertIn("moins-de-100-euros", slugs)
        self.assertNotIn("asie", slugs)

    def test_collection_page_is_in_every_language_and_sitemap(self):
        docs = self.build(self.deals())
        page = (docs / "vols-pas-chers" / "europe" / "index.html").read_text()
        self.assertIn("Vols pas chers depuis Paris : Europe", page)
        self.assertIn("Le moins cher : Barcelone", page)
        self.assertIn("Cheap flights from Paris: Europe", (docs / "en" / "vols-pas-chers" / "europe" / "index.html").read_text())
        self.assertIn("vols-pas-chers/moins-de-100-euros/", (docs / "sitemap.xml").read_text())

    def test_old_collections_are_removed(self):
        docs = self.build(self.deals())
        self.assertFalse((docs / "vols-pas-chers" / "asie").exists())

    def test_analytics_beacon_follows_config(self):
        docs = self.build(self.deals())
        token = tomllib.loads(Path("config.toml").read_text())["site"]["analytics_token"]
        self.assertEqual("cloudflareinsights" in (docs / "index.html").read_text(), bool(token))

    def test_world_pages_only_for_popular_routes(self):
        names = {"LON": "Londres", "PAR": "Paris", "TYO": "Tokyo", "LIS": "Lisbonne"}
        rows = [{"from": o, "to": t, "price": 100, "depart": "2027-01-01", "back": "2027-01-05", "stops": 0, "link": "https://tp.media/r"}
                for o, t in (("LON", "TYO"), ("PAR", "TYO"), ("LON", "LIS"))]
        with tempfile.TemporaryDirectory() as folder, mock.patch.object(build_site, "DOCS", Path(folder)), mock.patch.object(build_site, "POPULAR_ORIGINS", 2):
            (Path(folder) / "world.json").write_text(json.dumps({"updated": "x", "routes": rows}))
            origins = build_site.load_world(names)
        london = next(o for o in origins if o["code"] == "LON")
        self.assertEqual(len(london["routes"]), 2)
        self.assertEqual([r["to"] for r in london["pages"]], ["TYO"])

    def test_clean_names_fixes_source_errors(self):
        names = build_site.clean_names({"fr": {"ZZZ": "ZZZ", "MAD": "Ville de Madrid", "BUD": "Buda", "LCA": "Citium"},
                                        "en": {"ZZZ": "Zedville", "MAD": "Madrid", "BUD": "Budapest", "LCA": "Larnaca"}})
        self.assertEqual(names["fr"], {"ZZZ": "Zedville", "MAD": "Madrid", "BUD": "Budapest", "LCA": "Larnaca"})

    def test_custom_trip_page_is_french_only(self):
        docs = self.build(self.deals())
        page = (docs / "voyage-sur-mesure" / "index.html").read_text()
        self.assertIn('id="custom-form"', page)
        self.assertIn("Tu réserves", page)
        self.assertIn("voyage-sur-mesure/", (docs / "index.html").read_text())
        self.assertFalse((docs / "en" / "voyage-sur-mesure").exists())
        self.assertNotIn("voyage-sur-mesure", (docs / "en" / "index.html").read_text())

    def test_test_booking_is_hidden_from_public_pages(self):
        docs = self.build(self.deals())
        self.assertNotIn("test-reservation", (docs / "index.html").read_text())
        self.assertTrue((docs / "test-reservation" / "index.html").exists())

    def test_continent_from_city_data(self):
        self.assertEqual(build_site.continent({"time_zone": "America/Lima", "country_code": "PE"}), "SA")
        self.assertEqual(build_site.continent({"time_zone": "America/New_York", "country_code": "US"}), "NA")
        self.assertEqual(build_site.continent({"time_zone": "Atlantic/Canary", "country_code": "ES"}), "EU")

    def test_world_destinations_group_routes(self):
        page = {"to": "TYO", "to_slug": "tokyo", "price": 500}
        cheaper = {"to": "TYO", "to_slug": "tokyo", "price": 400}
        origin = {"code": "LON", "slug": "londres", "pages": [page], "routes": [page]}
        other = {"code": "PAR", "slug": "paris", "pages": [], "routes": [cheaper]}
        places = build_site.world_destinations([origin, other])
        self.assertEqual(len(places), 1)
        self.assertEqual(places[0]["routes"][0][0]["code"], "PAR")

    def test_home_presents_site_features(self):
        page = (self.build(self.deals()) / "index.html").read_text()
        self.assertIn("Tout ce que tu peux faire sur Eunodia", page)
        self.assertIn('id="preparer"', page)

    def test_ticker_shows_best_price_per_country(self):
        names = {"LON": "Londres", "TYO": "Tokyo"}
        route = {"to": "TYO", "to_slug": "tokyo", "from": "LON", "price": 400, "link": "x"}
        origin = {"code": "LON", "slug": "londres", "routes": [route], "pages": [route]}
        page = build_site.Page({"root": "/"}, "fr", names)
        page.countries = {"cities": {"TYO": "JP"}, "names": {"fr": {"JP": "Japon"}}}
        html = build_site.ticker_block(page, [origin])
        self.assertIn("Japon", html)
        self.assertIn("400", html)
        self.assertIn("/vers/tokyo/", html)

    def test_one_day_is_singular(self):
        self.assertEqual(build_site.Page({"root": "/"}, "fr").t("days", count=1), "1 jour")

    def test_newsletter_confirmation_page_is_hidden_from_search(self):
        page = (self.build(self.deals()) / "newsletter-confirmee" / "index.html").read_text()
        self.assertIn("bienvenue", page)
        self.assertIn('content="noindex, nofollow"', page)

    def test_footer_shows_contact_email(self):
        self.assertIn("mailto:contact@eunodia.com", (self.build(self.deals()) / "index.html").read_text())

    def test_distance_and_time_difference(self):
        paris, tokyo = [48.85, 2.35, "Europe/Paris"], [35.68, 139.69, "Asia/Tokyo"]
        self.assertAlmostEqual(build_site.distance_km(paris, tokyo), 9700, delta=100)
        self.assertEqual(build_site.time_difference(paris, tokyo, "2027-01-15"), 8)
        self.assertIsNone(build_site.time_difference(paris, [0, 0, None], "2027-01-15"))

    def test_home_declares_site_schema(self):
        page = (self.build(self.deals()) / "index.html").read_text()
        self.assertIn('"@type": "Organization"', page)
        self.assertIn('application/ld+json', page)

    def test_about_page_has_photo_header(self):
        html = '<section class="page wrap narrow"><h1>Infos</h1><p class="lead">Texte</p></section>'
        site = {"root": "/", "url": "https://eunodia.com/", "name": "Eunodia"}
        out = build_site.page_hero(build_site.Page(site, "fr"), "a-propos/", html, "")
        self.assertIn('class="page-hero"', out)
        self.assertIn('class="page wrap narrow"', out)

    def test_slug_removes_accents(self):
        self.assertEqual(build_site.slug("Montréal – Dorval"), "montreal-dorval")


    def test_vanished_pages_redirect_to_closest_page(self):
        with tempfile.TemporaryDirectory() as folder:
            docs, state = Path(folder) / "docs", Path(folder) / "pages.json"
            for page in ("", "de/", "de/depuis/miami/", "de/destinations/"):
                build_site.write(docs / page / "index.html", "<html>page</html>")
            state.write_text(json.dumps(["de/depuis/miami/", "de/depuis/miami/oslo/"]))
            with mock.patch.object(build_site, "DOCS", docs), mock.patch.object(build_site, "GONE_PAGES", ["it/vers/rome/"]):
                moved = build_site.keep_moved_pages(state, "https://eunodia.com/")
                self.assertEqual(moved, ["de/depuis/miami/oslo/", "it/vers/rome/"])
                stub = (docs / "de/depuis/miami/oslo/index.html").read_text()
                self.assertIn('url=https://eunodia.com/de/depuis/miami/"', stub)
                self.assertIn("noindex", stub)
                self.assertIn('url=https://eunodia.com/"', (docs / "it/vers/rome/index.html").read_text())
                build_site.write(docs / "de/depuis/miami/oslo/index.html", "<html>retour</html>")
                self.assertEqual(build_site.keep_moved_pages(state, "https://eunodia.com/"), ["it/vers/rome/"])
            self.assertIn("de/depuis/miami/oslo/", json.loads(state.read_text()))


if __name__ == "__main__":
    unittest.main()
