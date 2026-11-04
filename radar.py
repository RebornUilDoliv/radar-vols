#!/usr/bin/env python3
"""Radar de vols pas chers : repère les prix, les vérifie, envoie un e-mail."""
import argparse
import html
import json
import os
import smtplib
import ssl
import statistics
import sys
import time
import tomllib
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from email.message import EmailMessage
from pathlib import Path

ROOT = Path(__file__).parent
TP_BASE = "https://api.travelpayouts.com"
SERPAPI_URL = "https://serpapi.com/search"
HISTORY_KEEP_DAYS = 90
STALE_DAYS = 7
STALE_MARGIN = 0.15


class ConfigError(Exception):
    """Problème que l'utilisateur doit corriger (clé invalide, réglage manquant)."""


@dataclass
class Offer:
    destination: str
    price: float
    depart: date
    back: date
    stops: int | None = None
    airport: str = ""
    link: str = ""
    group: dict = field(default_factory=dict)
    city_name: str = ""
    reason: str = ""
    median: float | None = None
    verified: bool = False
    price_level: str = ""

    @property
    def key(self):
        return f"{self.destination}|{self.depart:%Y-%m}"

    @property
    def trip(self):
        return f"{self.destination}|{self.depart}|{self.back}"


def http_json(url, headers=None, retries=2):
    """GET JSON. Les erreurs ne citent jamais l'URL, qui peut contenir une clé."""
    request = urllib.request.Request(url, headers={"User-Agent": "radar-vols", **(headers or {})})
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(request, timeout=45) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            if error.code in (401, 403):
                raise ConfigError(f"clé API refusée (HTTP {error.code})") from None
            if error.code != 429 and error.code < 500 or attempt == retries:
                raise RuntimeError(f"HTTP {error.code}") from None
        except (urllib.error.URLError, TimeoutError, ValueError) as error:
            if attempt == retries:
                raise RuntimeError(type(error).__name__) from None
        time.sleep(2 ** (attempt + 1))


def parse_date(value):
    return datetime.fromisoformat(str(value).replace("Z", "+00:00")).date() if value else None


def to_offer(row, destination=None):
    """Unifie les trois formats de réponse de Travelpayouts."""
    price = row.get("price", row.get("value"))
    depart = parse_date(row.get("departure_at") or row.get("depart_date"))
    back = parse_date(row.get("return_at") or row.get("return_date"))
    destination = row.get("destination") or destination
    expires = parse_date(row.get("expires_at"))
    if not (price and depart and back and destination) or (expires and expires < date.today()):
        return None
    link = row.get("link") or ""
    return Offer(
        destination=destination,
        price=float(price),
        depart=depart,
        back=back,
        stops=row.get("transfers", row.get("number_of_changes")),
        airport=row.get("destination_airport") or "",
        link=f"https://www.aviasales.com{link}" if link.startswith("/") else link,
    )


class Travelpayouts:
    def __init__(self, token, search):
        self.headers = {"X-Access-Token": token}
        self.search = search
        self.calls = self.failures = 0

    def get(self, path, **params):
        params = {"currency": self.search["currency"], "market": self.search["market"], **params}
        self.calls += 1
        try:
            payload = http_json(f"{TP_BASE}{path}?{urllib.parse.urlencode(params)}", self.headers)
        except RuntimeError as error:
            self.failures += 1
            print(f"Travelpayouts {path} : {error}", file=sys.stderr)
            return None
        except ConfigError:
            raise ConfigError("token Travelpayouts refusé") from None
        return payload.get("data") if isinstance(payload, dict) else None

    def discovery(self):
        """Destinations ouvertes : deux appels couvrent toutes les villes."""
        origin = self.search["origin_city"]
        directions = self.get("/v1/city-directions", origin=origin) or {}
        latest = self.get(
            "/v2/prices/latest", origin=origin, period_type="year", one_way="false",
            show_to_affiliates="true", sorting="price", limit=1000,
        ) or []
        rows = [(row, code) for code, row in directions.items()] if isinstance(directions, dict) else []
        rows += [(row, None) for row in latest] if isinstance(latest, list) else []
        return [offer for row, code in rows if (offer := to_offer(row, code))]

    def route_month(self, destination, month):
        """Dates flexibles : tous les prix connus d'une ville pour un mois."""
        rows = self.get(
            "/aviasales/v3/prices_for_dates", origin=self.search["origin_city"],
            destination=destination, departure_at=month, one_way="false", sorting="price",
            unique="false", limit=100,
        )
        return [offer for row in rows or [] if (offer := to_offer(row, destination))]


def load_places():
    cities = http_json(f"{TP_BASE}/data/fr/cities.json")
    airports = http_json(f"{TP_BASE}/data/en/airports.json")
    by_city = {}
    for airport in airports:
        if airport.get("iata_type") == "airport" and airport.get("flightable"):
            by_city.setdefault(airport.get("city_code"), []).append(airport["code"])
    return {
        city["code"]: {
            "country": city.get("country_code"),
            "name": city.get("name") or city["code"],
            "airports": by_city.get(city["code"], []),
        }
        for city in cities
    }


def aviasales_link(offer, search):
    return offer.link or (
        f"https://www.aviasales.com/search/{search['origin_city']}{offer.depart:%d%m}"
        f"{offer.destination}{offer.back:%d%m}1"
    )


def site_rows(offers, state, search):
    """Prix Travelpayouts publiés sur le site, sans budget ni vérification Google."""
    history = state.get("history", {})
    rows = [
        {
            "city": offer.city_name,
            "code": offer.destination,
            "region": offer.group["name"],
            "price": round(offer.price),
            "usual": round(offer.median) if offer.median else None,
            "depart": offer.depart.isoformat(),
            "back": offer.back.isoformat(),
            "stops": offer.stops,
            "link": aviasales_link(offer, search),
            "history": sorted(history.get(offer.key, {}).items()),
        }
        for offer in offers
    ]
    return sorted(rows, key=lambda row: row["price"])


def write_site(path, rows, state):
    stale = state.get("stale", {})
    data = {
        "updated": datetime.now(timezone.utc).isoformat(timespec="minutes"),
        "offers": [r for r in rows if f"{r['code']}|{r['depart']}|{r['back']}" not in stale],
    }
    path.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")) + "\n")


def attach_group(offer, groups, places):
    place = places.get(offer.destination, {})
    for group in groups:
        if offer.destination in group["cities"] or place.get("country") in group["countries"]:
            offer.group = group
            offer.city_name = place.get("name", offer.destination)
            return True
    return False


def in_window(offer, search, today):
    first = today + timedelta(days=search["min_days_ahead"])
    last = today + timedelta(days=search["months_ahead"] * 31)
    days = (offer.back - offer.depart).days
    return first <= offer.depart <= last and offer.group["min_days"] <= days <= offer.group["max_days"]


def months_between(today, count):
    year, month = today.year, today.month
    for _ in range(count):
        yield f"{year}-{month:02d}"
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)


def cheapest_by_month(offers):
    best = {}
    for offer in offers:
        if offer.key not in best or offer.price < best[offer.key].price:
            best[offer.key] = offer
    return list(best.values())


def update_history(state, offers, today):
    history = state.setdefault("history", {})
    for offer in offers:
        days = history.setdefault(offer.key, {})
        day = today.isoformat()
        days[day] = min(offer.price, days.get(day, offer.price))
    limit = (today - timedelta(days=HISTORY_KEEP_DAYS)).isoformat()
    for key in list(history):
        history[key] = {day: price for day, price in history[key].items() if day >= limit}
        if not history[key]:
            del history[key]


def usual_price(state, offer, today, minimum):
    """Médiane des jours précédents, sans le jour même pour ne pas fausser la comparaison."""
    days = state.get("history", {}).get(offer.key, {})
    prices = [price for day, price in days.items() if day != today.isoformat()]
    return statistics.median(prices) if len(prices) >= minimum else None


def qualify(offer, state, alerts, today):
    offer.median = usual_price(state, offer, today, alerts["min_history_days"])
    return bool(offer.group.get("market_low_only")) or still_good(offer, alerts)


def already_alerted(offer, state, alerts, today):
    last = state.get("alerted", {}).get(offer.key)
    if not last:
        return False
    recent = today - date.fromisoformat(last["date"]) < timedelta(days=alerts["realert_days"])
    return recent and offer.price > last["price"] * (1 - alerts["realert_drop"])


def serpapi_left(state, config, today):
    usage = state.get("serpapi", {})
    used = usage.get("used", 0) if usage.get("month") == f"{today:%Y-%m}" else 0
    return max(0, config["monthly_limit"] - used)


def count_serpapi(state, today):
    month = f"{today:%Y-%m}"
    usage = state.setdefault("serpapi", {"month": month, "used": 0})
    if usage.get("month") != month:
        usage.update(month=month, used=0)
    usage["used"] += 1


def verify(offer, key, search, places):
    """Contrôle le prix sur Google Flights. Renvoie False si l'offre n'existe plus."""
    airports = [offer.airport] if offer.airport else places.get(offer.destination, {}).get("airports", [])
    params = {
        "engine": "google_flights", "api_key": key, "type": 1, "hl": "fr", "gl": "fr",
        "departure_id": search["origin_airports"],
        "arrival_id": ",".join(airports[:5]) or offer.destination,
        "outbound_date": offer.depart.isoformat(), "return_date": offer.back.isoformat(),
        "currency": search["currency"].upper(), "adults": search["adults"],
    }
    result = http_json(f"{SERPAPI_URL}?{urllib.parse.urlencode(params)}")
    prices = [f["price"] for f in result.get("best_flights", []) + result.get("other_flights", []) if f.get("price")]
    insights = result.get("price_insights") or {}
    if insights.get("lowest_price"):
        prices.append(insights["lowest_price"])
    if not prices:
        return False
    offer.price = float(min(prices))
    offer.price_level = insights.get("price_level") or ""
    offer.verified = True
    return True


def still_good(offer, alerts):
    reasons = []
    if not offer.group.get("market_low_only"):
        if offer.price <= offer.group["max_price"]:
            reasons.append("sous ton budget")
        if offer.median and offer.price <= offer.median * (1 - alerts["deal_drop"]):
            reasons.append(f"{1 - offer.price / offer.median:.0%} sous le prix habituel")
    if offer.price_level == "low":
        reasons.append("prix jugé bas par Google Flights")
    offer.reason = " · ".join(reasons)
    return bool(reasons)


def rank(offer):
    """Les offres sans budget passent après celles qui respectent le leur."""
    return offer.price / offer.group.get("max_price", offer.price)


def is_stale(offer, state, today):
    """Vrai si le contrôle a déjà démenti ce prix, sauf nouvelle baisse nette."""
    last = state.get("stale", {}).get(offer.trip)
    if not last:
        return False
    recent = today - date.fromisoformat(last["date"]) <= timedelta(days=STALE_DAYS)
    return recent and offer.price >= last["price"] * (1 - STALE_MARGIN)


def mark_stale(state, offer, cached, today):
    state.setdefault("stale", {})[offer.trip] = {"price": cached, "date": today.isoformat()}


def prune_stale(state, today):
    limit = (today - timedelta(days=STALE_DAYS)).isoformat()
    stale = state.get("stale", {})
    for trip in [t for t, entry in stale.items() if entry["date"] < limit]:
        del stale[trip]


def verify_best(candidates, key, state, config, today, places):
    alerts, search = config["alerts"], config["search"]
    allowance = min(config["serpapi"]["per_run_limit"], serpapi_left(state, config["serpapi"], today))
    kept = []
    for offer in sorted(candidates, key=rank):
        if len(kept) == alerts["max_per_email"]:
            break
        if key and allowance > 0:
            allowance -= 1
            count_serpapi(state, today)
            cached = offer.price
            try:
                exists = verify(offer, key, search, places)
                if not exists or offer.price > cached * (1 + STALE_MARGIN):
                    mark_stale(state, offer, cached, today)
                if not exists or not still_good(offer, alerts):
                    continue
            except RuntimeError as error:
                print(f"Vérification impossible pour {offer.destination} : {error}", file=sys.stderr)
            except ConfigError:
                print("Clé SerpApi refusée : offres envoyées sans vérification.", file=sys.stderr)
                key = None
        if offer.verified or not offer.group.get("market_low_only"):
            kept.append(offer)
    return kept


def google_link(offer, search):
    origin = search["origin_airports"].split(",")[0]
    query = f"Flights to {offer.airport or offer.destination} from {origin} on {offer.depart} through {offer.back}"
    return "https://www.google.com/travel/flights?" + urllib.parse.urlencode({"q": query, "hl": "fr", "curr": "EUR"})


def describe_stops(stops):
    if stops is None:
        return "escales non précisées"
    return "vol direct" if stops == 0 else f"{stops} escale{'s' if stops > 1 else ''}"


def build_email(offers, search, demo=False):
    subject = f"✈️ {len(offers)} vol{'s' if len(offers) > 1 else ''} pas cher{'s' if len(offers) > 1 else ''} depuis Paris"
    if demo:
        subject = f"[EXEMPLE] {subject}"
    lines, cards = [], []
    if demo:
        lines.append("EXEMPLE : ces prix sont fictifs.\n")
        cards.append('<p style="color:#b42318"><strong>Exemple : ces prix sont fictifs.</strong></p>')
    for offer in offers:
        status = "Vérifié sur Google Flights" if offer.verified else "À confirmer"
        dates = f"{offer.depart:%d/%m/%Y} → {offer.back:%d/%m/%Y}"
        details = f"{dates} · {(offer.back - offer.depart).days} jours · {describe_stops(offer.stops)}"
        link = google_link(offer, search)
        lines.append(
            f"{offer.city_name} ({offer.group['name']}) : {offer.price:.0f} €\n{details}\n"
            f"{offer.reason}\n{status}\n{link}\n"
        )
        extra = f' · <a href="{html.escape(offer.link)}">Aviasales</a>' if offer.link else ""
        cards.append(
            '<div style="border:1px solid #ddd;border-radius:8px;padding:14px;margin:12px 0">'
            f"<strong>{html.escape(offer.city_name)}</strong> — "
            f"<strong>{offer.price:.0f} €</strong> <small>({html.escape(offer.group['name'])})</small><br>"
            f"{html.escape(details)}<br>{html.escape(offer.reason)}<br><small>{status}</small><br>"
            f'<a href="{html.escape(link)}">Voir sur Google Flights</a>{extra}</div>'
        )
    lines.append("Prix par personne, aller-retour. Confirme toujours le prix avant de réserver.")
    cards.append("<p><small>Prix par personne, aller-retour. Confirme toujours le prix avant de réserver.</small></p>")
    message = EmailMessage()
    message["Subject"] = subject
    message.set_content("\n".join(lines))
    message.add_alternative(f'<div style="font-family:sans-serif;max-width:560px">{"".join(cards)}</div>', subtype="html")
    return message


def send_email(message):
    missing = [n for n in ("SMTP_HOST", "SMTP_USER", "SMTP_PASSWORD", "MAIL_FROM", "MAIL_TO") if not os.environ.get(n)]
    if missing:
        raise ConfigError("réglages e-mail manquants : " + ", ".join(missing))
    message["From"] = os.environ["MAIL_FROM"].strip()
    message["To"] = os.environ["MAIL_TO"].strip()
    port = int(os.environ.get("SMTP_PORT") or 587)
    context = ssl.create_default_context()
    host = os.environ["SMTP_HOST"].strip()
    connection = smtplib.SMTP_SSL(host, port, timeout=30, context=context) if port == 465 else smtplib.SMTP(host, port, timeout=30)
    with connection as server:
        print("E-mail : serveur joint.")
        if port != 465:
            server.starttls(context=context)
        print("E-mail : connexion chiffrée.")
        server.login(os.environ["SMTP_USER"].strip(), os.environ["SMTP_PASSWORD"].replace(" ", "").strip())
        print("E-mail : identification acceptée.")
        server.send_message(message)
        print("E-mail : message accepté par le serveur.")


def describe_smtp_settings():
    """Décrit le format des accès, sans jamais afficher leur valeur."""
    user, password = os.environ.get("SMTP_USER", ""), os.environ.get("SMTP_PASSWORD", "")
    print("Login au format Brevo :", user.strip().endswith("@smtp-brevo.com"))
    print("Clé de type SMTP :", password.strip().startswith("xsmtpsib-"))
    print("Clé de type API :", password.strip().startswith("xkeysib-"))
    print("Espaces autour des accès :", user != user.strip() or password != password.strip())
    code = password.replace(" ", "").strip()
    print("Login au format Gmail :", user.strip().endswith("@gmail.com"))
    print("Code de 16 lettres :", len(code) == 16 and code.isascii() and code.isalpha())


def demo_offers():
    today = date.today()
    return [
        Offer("BUE", 612, today + timedelta(days=75), today + timedelta(days=93), 1, "EZE",
              group={"name": "Argentine et Chili"}, city_name="Buenos Aires",
              reason="sous ton budget · 28 % sous le prix habituel", verified=True),
        Offer("LIS", 54, today + timedelta(days=40), today + timedelta(days=45), 0, "LIS",
              group={"name": "Europe"}, city_name="Lisbonne", reason="sous ton budget"),
    ]


def load_state(path):
    return json.loads(path.read_text()) if path.exists() else {}


def save_state(path, state):
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(state, indent=1, sort_keys=True) + "\n")


def run(config, state, client, places, serpapi_key, today, site=None):
    """Renvoie les offres à annoncer et met l'historique à jour."""
    search, alerts, groups = config["search"], config["alerts"], config["group"]
    offers = client.discovery()
    for group in groups:
        for city in group["cities"]:
            for month in months_between(today, search["months_ahead"]):
                offers += client.route_month(city, month)
                time.sleep(0.2)
    if client.calls and client.failures == client.calls:
        raise RuntimeError("Travelpayouts ne répond plus")
    prune_stale(state, today)
    offers = [
        o for o in offers
        if attach_group(o, groups, places) and in_window(o, search, today) and not is_stale(o, state, today)
    ]
    offers = cheapest_by_month(offers)
    candidates = [
        o for o in offers
        if qualify(o, state, alerts, today) and not already_alerted(o, state, alerts, today)
    ]
    update_history(state, offers, today)
    rows = site_rows(offers, state, search)
    found = verify_best(candidates, serpapi_key, state, config, today, places)
    if site:
        write_site(site, rows, state)
    print(f"{len(offers)} prix analysés, {len(candidates)} candidats, {len(found)} à envoyer.")
    return found


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=ROOT / "config.toml")
    parser.add_argument("--state", type=Path, default=ROOT / "data" / "state.json")
    parser.add_argument("--site", type=Path, default=ROOT / "docs" / "prices.json")
    parser.add_argument("--dry-run", action="store_true", help="affiche les offres sans e-mail, sans sauvegarde et sans utiliser SerpApi")
    parser.add_argument("--test-email", action="store_true", help="envoie un e-mail d'exemple")
    args = parser.parse_args()
    config = tomllib.loads(args.config.read_text())
    try:
        if args.test_email:
            describe_smtp_settings()
            send_email(build_email(demo_offers(), config["search"], demo=True))
            print("E-mail d'exemple envoyé.")
            return 0
        token = os.environ.get("TRAVELPAYOUTS_TOKEN")
        if not token:
            raise ConfigError("TRAVELPAYOUTS_TOKEN manquant")
        today = date.today()
        state = load_state(args.state)
        client = Travelpayouts(token, config["search"])
        serpapi_key = None if args.dry_run else os.environ.get("SERPAPI_KEY")
        site = None if args.dry_run else args.site
        found = run(config, state, client, load_places(), serpapi_key, today, site)
        if args.dry_run:
            for offer in found:
                print(f"{offer.city_name} {offer.price:.0f} € {offer.depart} → {offer.back} ({offer.reason})")
            return 0
        save_state(args.state, state)
        if found:
            send_email(build_email(found, config["search"]))
            for offer in found:
                state.setdefault("alerted", {})[offer.key] = {"price": offer.price, "date": today.isoformat()}
            save_state(args.state, state)
        return 0
    except ConfigError as error:
        print(f"À corriger : {error}", file=sys.stderr)
        return 2
    except (RuntimeError, smtplib.SMTPException, OSError) as error:
        print(f"Échec : {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
