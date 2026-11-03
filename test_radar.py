import tempfile
import tomllib
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest import mock

import radar

TODAY = date(2026, 11, 3)
CONFIG = tomllib.loads((Path(__file__).parent / "config.toml").read_text())
# Budgets et durées figés : les tests ne dépendent pas des réglages personnels.
CONFIG["group"] = [
    {"name": "Argentine", "countries": ["AR"], "cities": [], "max_price": 700, "min_days": 10, "max_days": 30},
    {"name": "Europe", "countries": ["PT"], "cities": [], "max_price": 70, "min_days": 2, "max_days": 10},
    {"name": "Corée du Nord", "countries": ["KP"], "cities": [], "market_low_only": True, "min_days": 10, "max_days": 30},
]
PLACES = {
    "BUE": {"country": "AR", "name": "Buenos Aires", "airports": ["EZE", "AEP"]},
    "LIS": {"country": "PT", "name": "Lisbon", "airports": ["LIS"]},
    "ASU": {"country": "PY", "name": "Asuncion", "airports": ["ASU"]},
    "JFK": {"country": "US", "name": "New York", "airports": ["JFK"]},
    "FNJ": {"country": "KP", "name": "Pyongyang", "airports": ["FNJ"]},
}


def row(destination, price, depart=TODAY + timedelta(days=60), days=15):
    return {
        "destination": destination, "price": price, "transfers": 1,
        "departure_at": f"{depart}T10:00:00+01:00",
        "return_at": f"{depart + timedelta(days=days)}T10:00:00+01:00",
    }


class FakeClient:
    calls, failures = 1, 0

    def __init__(self, rows):
        self.rows = rows

    def discovery(self):
        return [o for r in self.rows if (o := radar.to_offer(r))]

    def route_month(self, destination, month):
        return []


def run(rows, state=None, key=None):
    state = {} if state is None else state
    with mock.patch.object(radar.time, "sleep"):
        return radar.run(CONFIG, state, FakeClient(rows), PLACES, key, TODAY), state


def history(destination, price, depart=TODAY + timedelta(days=60), count=8):
    days = {str(TODAY - timedelta(days=i + 1)): price for i in range(count)}
    return {"history": {f"{destination}|{depart:%Y-%m}": days}}


class FormatTests(unittest.TestCase):
    def test_reads_all_three_response_formats(self):
        v3 = radar.to_offer(row("BUE", 600) | {"link": "/search/x"})
        latest = radar.to_offer({"destination": "LIS", "value": 50, "depart_date": "2027-01-10",
                                 "return_date": "2027-01-14", "number_of_changes": 0})
        directions = radar.to_offer({"price": 90, "departure_at": "2027-01-10T16:35:00Z",
                                     "return_at": "2027-01-14T16:05:00Z", "transfers": 0}, "BCN")
        self.assertEqual((v3.price, v3.link), (600, "https://www.aviasales.com/search/x"))
        self.assertEqual((latest.price, latest.stops), (50, 0))
        self.assertEqual(directions.destination, "BCN")

    def test_skips_one_way_rows(self):
        self.assertIsNone(radar.to_offer({"destination": "LIS", "price": 20, "departure_at": "2027-01-10"}))

    def test_months_cross_new_year(self):
        self.assertEqual(list(radar.months_between(date(2026, 11, 3), 3)), ["2026-11", "2026-12", "2027-01"])


class AlertTests(unittest.TestCase):
    def test_under_budget_alerts(self):
        found, _ = run([row("BUE", 650)])
        self.assertEqual([o.destination for o in found], ["BUE"])
        self.assertIn("sous ton budget", found[0].reason)

    def test_above_budget_without_history_is_ignored(self):
        self.assertEqual(run([row("BUE", 900)])[0], [])

    def test_unusual_drop_alerts_even_above_budget(self):
        found, _ = run([row("BUE", 750)], history("BUE", 1200))
        self.assertEqual(len(found), 1)
        self.assertIn("38 % sous le prix habituel".replace(" %", "%"), found[0].reason)

    def test_short_history_is_not_a_deal(self):
        self.assertEqual(run([row("BUE", 750)], history("BUE", 1200, count=3))[0], [])

    def test_unknown_destination_ignored(self):
        self.assertEqual(run([row("XXX", 10)])[0], [])

    def test_trip_length_and_window(self):
        self.assertEqual(run([row("LIS", 40, days=15)])[0], [])
        self.assertEqual(run([row("LIS", 40, depart=TODAY + timedelta(days=3), days=5)])[0], [])
        self.assertEqual(len(run([row("LIS", 40, days=5)])[0]), 1)

    def test_keeps_cheapest_of_month(self):
        found, _ = run([row("BUE", 690), row("BUE", 640)])
        self.assertEqual([o.price for o in found], [640])

    def test_repeat_alert_needs_new_drop(self):
        key = f"BUE|{TODAY + timedelta(days=60):%Y-%m}"
        state = {"alerted": {key: {"price": 650, "date": str(TODAY - timedelta(days=2))}}}
        self.assertEqual(run([row("BUE", 640)], state)[0], [])
        self.assertEqual(len(run([row("BUE", 610)], state)[0]), 1)

    def test_repeat_alert_returns_after_cooldown(self):
        key = f"BUE|{TODAY + timedelta(days=60):%Y-%m}"
        state = {"alerted": {key: {"price": 650, "date": str(TODAY - timedelta(days=8))}}}
        self.assertEqual(len(run([row("BUE", 650)], state)[0]), 1)

    def test_all_failures_raise(self):
        client = FakeClient([])
        client.failures = 1
        with mock.patch.object(radar.time, "sleep"), self.assertRaises(RuntimeError):
            radar.run(CONFIG, {}, client, PLACES, None, TODAY)


def serp(price, level="typical"):
    return {"best_flights": [{"price": price}], "other_flights": [],
            "price_insights": {"lowest_price": price, "price_level": level}}


class VerificationTests(unittest.TestCase):
    def test_confirmed_price_replaces_cached_one(self):
        with mock.patch.object(radar, "http_json", return_value=serp(630)) as api:
            found, state = run([row("BUE", 650)], key="k")
        self.assertEqual((found[0].price, found[0].verified), (630, True))
        self.assertEqual(state["serpapi"]["used"], 1)
        self.assertIn("arrival_id=EZE%2CAEP", api.call_args.args[0])
        self.assertIn("departure_id=CDG%2CORY", api.call_args.args[0])

    def test_vanished_or_expensive_offer_dropped(self):
        with mock.patch.object(radar, "http_json", return_value={"best_flights": []}):
            self.assertEqual(run([row("BUE", 650)], key="k")[0], [])
        with mock.patch.object(radar, "http_json", return_value=serp(990)):
            self.assertEqual(run([row("BUE", 650)], key="k")[0], [])

    def test_google_low_level_keeps_offer(self):
        with mock.patch.object(radar, "http_json", return_value=serp(720, "low")):
            found, _ = run([row("BUE", 650)], key="k")
        self.assertIn("Google Flights", found[0].reason)

    def test_budget_exhausted_sends_unverified(self):
        state = {"serpapi": {"month": "2026-11", "used": 240}}
        with mock.patch.object(radar, "http_json") as api:
            found, _ = run([row("BUE", 650)], state, key="k")
        api.assert_not_called()
        self.assertFalse(found[0].verified)

    def test_per_run_limit(self):
        rows = [row("BUE", 500 + i, TODAY + timedelta(days=30 * i + 20)) for i in range(7)]
        with mock.patch.object(radar, "http_json", return_value=serp(600)) as api:
            found, _ = run(rows, key="k")
        self.assertEqual(api.call_count, 4)
        self.assertEqual(len(found), 7)

    def test_counter_resets_each_month(self):
        state = {"serpapi": {"month": "2026-10", "used": 240}}
        self.assertEqual(radar.serpapi_left(state, CONFIG["serpapi"], TODAY), 240)
        radar.count_serpapi(state, TODAY)
        self.assertEqual(state["serpapi"], {"month": "2026-11", "used": 1})

    def test_network_error_keeps_unverified_offer(self):
        with mock.patch.object(radar, "http_json", side_effect=RuntimeError("HTTP 500")):
            found, _ = run([row("BUE", 650)], key="k")
        self.assertFalse(found[0].verified)


class RejectedKeyTests(unittest.TestCase):
    def test_serpapi_rejection_keeps_offers_unverified(self):
        rows = [row("BUE", 640, TODAY + timedelta(days=60)), row("BUE", 650, TODAY + timedelta(days=95))]
        with mock.patch.object(radar, "http_json", side_effect=radar.ConfigError("x")) as api:
            found, _ = run(rows, key="k")
        self.assertEqual(api.call_count, 1)
        self.assertEqual([o.verified for o in found], [False, False])

    def test_travelpayouts_rejection_names_the_service(self):
        client = radar.Travelpayouts("t", CONFIG["search"])
        with mock.patch.object(radar, "http_json", side_effect=radar.ConfigError("x")), \
                self.assertRaisesRegex(radar.ConfigError, "Travelpayouts"):
            client.discovery()


class MarketLowOnlyTests(unittest.TestCase):
    def test_low_market_price_alerts(self):
        with mock.patch.object(radar, "http_json", return_value=serp(2000, "low")):
            found, _ = run([row("FNJ", 2100)], key="k")
        self.assertEqual([o.price for o in found], [2000])
        self.assertEqual(found[0].reason, "prix jugé bas par Google Flights")

    def test_typical_market_price_stays_silent(self):
        with mock.patch.object(radar, "http_json", return_value=serp(100, "typical")):
            self.assertEqual(run([row("FNJ", 100)], key="k")[0], [])

    def test_history_drop_alone_stays_silent(self):
        with mock.patch.object(radar, "http_json", return_value=serp(1000, "typical")):
            self.assertEqual(run([row("FNJ", 1000)], history("FNJ", 3000), key="k")[0], [])

    def test_no_alert_without_verification(self):
        self.assertEqual(run([row("FNJ", 100)])[0], [])
        with mock.patch.object(radar, "http_json", side_effect=RuntimeError("HTTP 500")):
            self.assertEqual(run([row("FNJ", 100)], key="k")[0], [])

    def test_budgeted_offers_are_verified_first(self):
        rows = [row("FNJ", 100)] + [row("BUE", 500 + i, TODAY + timedelta(days=30 * i + 20)) for i in range(4)]
        with mock.patch.object(radar, "http_json", return_value=serp(600)) as api:
            run(rows, key="k")
        self.assertEqual(api.call_count, 4)
        self.assertNotIn("arrival_id=FNJ", " ".join(call.args[0] for call in api.call_args_list))


class EmailTests(unittest.TestCase):
    def test_demo_is_labelled(self):
        message = radar.build_email(radar.demo_offers(), CONFIG["search"], demo=True)
        self.assertIn("[EXEMPLE]", message["Subject"])
        self.assertIn("fictifs", message.get_body(("plain",)).get_content())

    def test_html_is_escaped(self):
        offer = radar.demo_offers()[0]
        offer.city_name = "<b>x</b>"
        body = radar.build_email([offer], CONFIG["search"]).get_body(("html",)).get_content()
        self.assertIn("&lt;b&gt;", body)
        self.assertNotIn("<b>x", body)

    def test_missing_settings_named(self):
        with mock.patch.dict(radar.os.environ, {}, clear=True), self.assertRaises(radar.ConfigError) as error:
            radar.send_email(radar.build_email(radar.demo_offers(), CONFIG["search"]))
        self.assertIn("SMTP_HOST", str(error.exception))


class StateTests(unittest.TestCase):
    def test_history_ignores_today_and_prunes_old(self):
        offer = radar.demo_offers()[0]
        old = str(TODAY - timedelta(days=120))
        state = {"history": {offer.key: {old: 100}}}
        radar.update_history(state, [offer], TODAY)
        self.assertEqual(list(state["history"][offer.key]), [str(TODAY)])
        self.assertIsNone(radar.usual_price(state, offer, TODAY, 1))

    def test_round_trip_to_disk(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "data" / "state.json"
            radar.save_state(path, {"history": {}})
            self.assertEqual(radar.load_state(path), {"history": {}})

    def test_secret_not_in_http_error(self):
        error = radar.urllib.error.HTTPError("https://x?api_key=SECRET", 500, "x", {}, None)
        with mock.patch.object(radar.urllib.request, "urlopen", side_effect=error), \
                mock.patch.object(radar.time, "sleep"), self.assertRaises(RuntimeError) as caught:
            radar.http_json("https://x?api_key=SECRET")
        self.assertNotIn("SECRET", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
