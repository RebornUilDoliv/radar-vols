#!/usr/bin/env python3
"""Génère le site statique multilingue d'Eunodia à partir de docs/prices.json."""
import hashlib
import html
import json
import re
import shutil
import sys
import tomllib
import unicodedata
import urllib.parse
from datetime import date, datetime
from statistics import median
from pathlib import Path

import radar
from site_text import CONTINENTS, LANG_NAMES, LANGS, LOCALES, MONTHS, REGIONS, SCRIPT_TEXT, SHORT_MONTHS, TEXT

ROOT = Path(__file__).parent
DOCS = ROOT / "docs"
SOON_DAYS = 45
AHEAD_DAYS = 150
HERO_PHOTO = "TYO"
BUDGETS = (100, 200, 500)
MIN_COLLECTION_CITIES = 3
COLLECTION_ROWS = 40
ROUTES_PER_ORIGIN = 40           # pages de route créées par ville de départ
POPULAR_ORIGINS = 10             # une destination doit être desservie depuis autant de villes
MAX_ROUTE_PRICE = 3000           # écarte les prix aberrants
HUB_ROWS = 60
DEFAULT_ORIGIN = {"fr": "PAR", "en": "LON", "es": "MAD"}
SOUTH_AMERICA = {"AR", "BO", "BR", "CL", "CO", "EC", "GF", "GY", "PE", "PY", "SR", "UY", "VE"}
LOGO = (
    '<svg class="mark" viewBox="0 0 32 32" aria-hidden="true"><circle cx="16" cy="16" r="13.8" fill="none" stroke="currentColor" stroke-width="2"/>'
    '<path d="M9.5 17.5a6.5 6.5 0 0 1 13 0z" fill="currentColor"/><rect x="6.2" y="18.8" width="19.6" height="1.6" rx=".8" fill="currentColor"/>'
    '<rect x="9.5" y="22" width="13" height="1.4" rx=".7" fill="currentColor"/></svg>'
)
e = html.escape


def slug(text):
    plain = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", plain.lower()).strip("-")


class Page:
    """Contexte d'une langue : textes, adresses et mise en forme."""

    def __init__(self, site, lang, names=None):
        self.site, self.lang, self.names = site, lang, names or {}
        self.base = site["root"]
        self.root = self.base if lang == "fr" else f"{self.base}{lang}/"
        self.folder = DOCS if lang == "fr" else DOCS / lang
        self.prefix = "" if lang == "fr" else f"{lang}/"
        self.zones = {}

    def t(self, key, **values):
        return TEXT[self.lang][key].format(**values) if values else TEXT[self.lang][key]

    def euro(self, value):
        number = f"{value:,.0f}"
        if self.lang == "en":
            return f"€{number}"
        return number.replace(",", " ") + " €"

    def day(self, iso, year=True):
        value = date.fromisoformat(iso)
        month = SHORT_MONTHS[self.lang][value.month - 1]
        label = f"{value.day} {month}"
        return f"{label} {value.year}" if year else label

    def month(self, key):
        year, month = key.split("-")
        return f"{MONTHS[self.lang][int(month) - 1]} {year}"

    def city(self, code, fallback):
        return self.names.get(code, fallback)

    def region(self, name):
        return REGIONS.get(self.lang, {}).get(name, name)

    def stops(self, offer):
        count = offer.get("stops")
        if count is None:
            return self.t("stops_unknown")
        if count == 0:
            return self.t("direct")
        return self.t("stop" if count == 1 else "stops", count=count)


def nights(offer):
    return (date.fromisoformat(offer["back"]) - date.fromisoformat(offer["depart"])).days


def photo_exists(code):
    return (DOCS / "assets" / "photos" / f"{code}.jpg").exists()


def photo_set(p, code, sizes):
    """Sert la version 4K aux grands écrans, et la version légère aux autres."""
    light = f"{p.base}assets/photos/{code}.jpg"
    if not (DOCS / "assets" / "photos" / f"{code}-4k.jpg").exists():
        return f'src="{light}"'
    return f'src="{light}" srcset="{light} 1280w, {p.base}assets/photos/{code}-4k.jpg 3840w" sizes="{sizes}"'


def load_credits():
    path = DOCS / "assets" / "photos" / "credits.json"
    return json.loads(path.read_text()) if path.exists() else {}


def destinations(offers):
    """Regroupe les vols par ville, chaque ville avec une adresse unique."""
    cities, used = {}, set()
    for offer in offers:
        cities.setdefault(offer["code"], {"city": offer["city"], "code": offer["code"], "offers": []})
        cities[offer["code"]]["offers"].append(offer)
    for city in cities.values():
        name = slug(city["city"]) or city["code"].lower()
        city["slug"] = name if name not in used else f"{name}-{city['code'].lower()}"
        used.add(city["slug"])
        city["offers"].sort(key=lambda o: o["price"])
        city["best"] = city["offers"][0]
        city["region"] = city["best"]["region"]
    return sorted(cities.values(), key=lambda c: c["best"]["price"])


def layout(p, title, description, path, body, noindex=False, extra=""):
    site, base, root = p.site, p.base, p.root
    name = e(site["name"])
    links = "".join(
        f'<link rel="alternate" hreflang="{lang}" href="{e(site["url"] + ("" if lang == "fr" else lang + "/") + path)}">'
        for lang in LANGS
    )
    switch = "".join(
        f'<a href="{base}{"" if lang == "fr" else lang + "/"}{path}" lang="{lang}" hreflang="{lang}"'
        f'{" aria-current=\"true\"" if lang == p.lang else ""} title="{LANG_NAMES[lang]}">{lang.upper()}</a>'
        for lang in LANGS
    )
    shared = {key: TEXT[p.lang][key] for key in ("see", "direct", "stop", "stops", "stops_unknown", "days")}
    script = json.dumps(
        {"lang": p.lang, "locale": LOCALES[p.lang], "root": root, "base": base, "t": {**SCRIPT_TEXT[p.lang], **shared},
         "from_label": p.t("search_from"), "to_label": p.t("search_to"), "out_label": p.t("search_out"), "search_place": p.t("search_place"),
         "from_name": p.city("PAR", "Paris"), "to_name": p.city("NYC", "New York"),
         "photos": sorted(code for code in load_credits() if photo_exists(code))},
        ensure_ascii=False, separators=(",", ":"),
    ).replace("</", "<\\/")
    version = site["version"]
    analytics = ""
    if site.get("analytics_token"):
        beacon = e(json.dumps({"token": site["analytics_token"]}))
        analytics = f'<script defer src="https://static.cloudflareinsights.com/beacon.min.js" data-cf-beacon="{beacon}"></script>'
    return f"""<!doctype html>
<html lang="{p.lang}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(title)}</title>
<meta name="description" content="{e(description)}">
<link rel="canonical" href="{e(site['url'] + p.prefix + path)}">
{links}
{'<meta name="robots" content="noindex, nofollow">' if noindex else ''}
<meta property="og:title" content="{e(title)}">
<meta property="og:description" content="{e(description)}">
<meta property="og:type" content="website">
<link rel="icon" href="{base}assets/icon.svg?v=3" type="image/svg+xml">
<link rel="stylesheet" href="{base}assets/style.css?v={version}">
<script>window.RF={script}</script>
<script src="{base}assets/app.js?v={version}" defer></script>
{extra}
{analytics}
</head>
<body>
<header class="nav">
  <a class="logo" href="{root}" aria-label="{name}">{LOGO}{name}</a>
  <nav aria-label="Menu">
    <a href="{root}vols/">{p.t('nav_flights')}</a>
    <a href="{root}depuis/">{p.t('nav_world')}</a>
    <a href="{root}destinations/">{p.t('nav_places')}</a>
    <a href="{root}vols-pas-chers/">{p.t('nav_deals')}</a>
    <a href="{root}a-propos/">{p.t('nav_info')}</a>
  </nav>
  <div class="langs" aria-label="Langue">{switch}</div>
</header>
<main>
{body}
</main>
<footer class="foot">
  <div class="wrap foot-in">
    <p class="foot-brand">{LOGO}{name}</p>
    <div>
      <p>{p.t('foot_1')}</p>
      <p>{p.t('foot_2', name=name)}</p>
    </div>
    <p class="foot-links"><a href="{root}depuis/">{p.t('nav_world')}</a><a href="{root}vols/">{p.t('nav_flights')}</a><a href="{root}vols-pas-chers/">{p.t('nav_deals')}</a><a href="{root}destinations/">{p.t('nav_places')}</a><a href="{root}a-propos/">{p.t('nav_info')}</a><a href="{root}credits/">{p.t('credits')}</a></p>
  </div>
</footer>
</body>
</html>
"""


def flight_row(p, offer, city):
    page = f'{p.root}destinations/{city["slug"]}/'
    name = e(p.city(offer["code"], offer["city"]))
    label = e(p.t("see_flight", city=p.city(offer["code"], offer["city"])))
    return f"""<li class="row">
  <div class="row-info">
    <h3><a href="{page}">{name}</a></h3>
    <p>{e(p.day(offer['depart'], False))} → {e(p.day(offer['back']))} · {e(p.t('days', count=nights(offer)))} · {e(p.stops(offer))}</p>
  </div>
  <p class="row-price">{p.euro(offer['price'])}</p>
  <a class="go" href="{page}?mois={offer['depart'][:7]}" aria-label="{label}">{p.t('see')}</a>
</li>"""


def photo_credit(p, credit):
    license_name = e(credit["license"])
    if credit.get("license_url"):
        license_name = f'<a href="{e(credit["license_url"])}" rel="noopener">{license_name}</a>'
    return f'{p.t("photo")} : <a href="{e(credit["source"])}" rel="noopener">{e(credit["artist"])}</a>, {license_name}, {p.t("resized")}'


def photo_card(p, city, big=False):
    name = e(p.city(city["code"], city["city"]))
    return f"""<a class="card{' big' if big else ''}" href="{p.root}destinations/{city['slug']}/">
  <img {photo_set(p, city['code'], '(max-width: 980px) 100vw, 66vw' if big else '(max-width: 980px) 50vw, 33vw')} alt="{name}" loading="lazy">
  <span class="card-label"><strong>{name}</strong><span>{p.t('from_price', price=p.euro(city['best']['price']))}</span></span>
</a>"""


def newsletter_block(p):
    url = p.site.get("newsletter_url")
    if not url:
        return ""
    return f"""<section class="news"><div class="wrap news-in">
  <div><h2>{p.t('news_title')}</h2><p>{p.t('news_lead')}</p></div>
  <form id="newsletter" action="{e(url)}" method="post" target="_blank">
    <label class="sr" for="news-email">{p.t('news_email')}</label>
    <div class="news-row"><input id="news-email" name="EMAIL" type="email" placeholder="{e(p.t('news_email'))}" autocomplete="email" required><button type="submit">{p.t('news_go')}</button></div>
    <label class="news-consent"><input id="news-consent" type="checkbox" required> <span>{p.t('news_consent')}</span></label>
    <input class="sr" name="email_address_check" type="text" tabindex="-1" autocomplete="off" aria-hidden="true">
    <input type="hidden" name="locale" value="{p.lang}">
    <input type="hidden" name="html_type" value="simple">
    <p class="news-done" id="news-done" role="status" hidden></p>
  </form>
</div></section>"""


def search_form(p):
    return f"""<form class="search" id="search" data-target="https://www.aviasales.com/search/" autocomplete="off">
  <div class="field grow"><label for="from">{p.t('search_from')}</label><input id="from" placeholder="{p.t('search_place')}" required>
    <ul class="suggest" hidden></ul></div>
  <div class="field grow"><label for="to">{p.t('search_to')}</label><input id="to" placeholder="{e(p.t('search_place'))}" required>
    <ul class="suggest" hidden></ul></div>
  <div class="field"><label for="out">{p.t('search_out')}</label><input id="out" type="date" required></div>
  <div class="field"><label for="back">{p.t('search_back')}</label><input id="back" type="date"></div>
  <div class="field small"><label for="pax">{p.t('search_pax')}</label><select id="pax"><option>1</option><option>2</option><option>3</option><option>4</option><option>5</option><option>6</option></select></div>
  <button class="search-go" type="submit">{p.t('search_go')}</button>
  <p class="form-error" id="search-error" role="alert" hidden></p>
</form>"""


def home(p, cities, offers, updated, origins=()):
    today = date.today()
    by_code = {c["code"]: c for c in cities}
    credits = load_credits()
    pictured = [c for c in cities if c["code"] in credits and photo_exists(c["code"])]
    best = cities[0]["best"]
    hero_code = HERO_PHOTO if photo_exists(HERO_PHOTO) else (pictured[0]["code"] if pictured else "")
    hero_image = f'<img class="hero-img" {photo_set(p, hero_code, "100vw")} alt="">' if hero_code else ""
    mosaic = ""
    if pictured:
        first, *others = pictured[:5]
        mosaic = f"""<div class="mosaic">{photo_card(p, first, big=True)}<div class="mosaic-side">{''.join(photo_card(p, c) for c in others)}</div></div>"""
    deals = "".join(flight_row(p, c["best"], c) for c in cities[:8])

    def unique(items):
        seen, out = set(), []
        for item in items:
            if item["code"] not in seen:
                seen.add(item["code"])
                out.append(item)
        return out[:4]

    soon_list = sorted((o for o in offers if (date.fromisoformat(o["depart"]) - today).days <= SOON_DAYS), key=lambda o: o["price"])
    ahead_list = sorted((o for o in offers if (date.fromisoformat(o["depart"]) - today).days >= AHEAD_DAYS), key=lambda o: o["price"])
    soon = "".join(flight_row(p, o, by_code[o["code"]]) for o in unique(soon_list))
    ahead = "".join(flight_row(p, o, by_code[o["code"]]) for o in unique(ahead_list))
    regions = {}
    for offer in offers:
        regions[offer["region"]] = min(offer["price"], regions.get(offer["region"], 10**9))
    region_pages = {g["slug"] for g in collections(offers)}
    region_links = "".join(
        f'<a class="pill" href="{p.root}vols-pas-chers/{slug(name)}/">{e(p.region(name))}<span>{p.t("from_price", price=p.euro(price))}</span></a>'
        for name, price in sorted(regions.items(), key=lambda kv: kv[1]) if slug(name) in region_pages
    )
    budgets = "".join(
        f'<a class="budget" href="{p.root}vols/?origin=PAR&amp;budget={value}"><strong>{p.t("under", price=p.euro(value))}</strong><span>{p.t("places_count", count=sum(1 for c in cities if c["best"]["price"] <= value))}</span></a>'
        for value in (100, 300, 600, 1000)
    )
    nothing = f'<li class="empty">{p.t("nothing")}</li>'
    world = ""
    start = p.city("PAR", "Paris")
    hero_route = None
    if origins:
        cheapest = sorted(((o, r) for o in origins for r in o["pages"]), key=lambda pair: pair[1]["price"])
        hero_route = cheapest[0]
        seen, picks = set(), []
        for origin, route in cheapest:
            if route["to"] not in seen:
                seen.add(route["to"])
                picks.append((origin, route))
        deals = "".join(world_deal(p, origin, route) for origin, route in picks[:8])
        start = p.city(hero_route[0]["code"], hero_route[0]["code"])
        world = f'''<section class="band wrap"><h2>{p.t("world_home")}</h2><p class="sub">{p.t("world_home_sub", count=len(origins))}</p><ul class="links">{origin_links(p, origins)}</ul></section>'''
    body = f"""<section class="hero">
  {hero_image}
  <div class="hero-in">
    <h1>{p.t('hero')}</h1>
    <p>{e(p.t('hero_sub', start=start, city=p.city(hero_route[1]['to'], hero_route[1]['to']) if hero_route else p.city(best['code'], best['city']), price=p.euro(hero_route[1]['price'] if hero_route else best['price'])))}</p>
  </div>
</section>
<div class="wrap search-wrap" id="recherche">{search_form(p)}</div>
<ul class="perks wrap">
  <li><strong>{p.t('perk_1')}</strong><span>{p.t('perk_1b')}</span></li>
  <li><strong>{p.t('perk_2')}</strong><span>{p.t('perk_2b')}</span></li>
  <li><strong>{p.t('perk_3')}</strong><span>{p.t('perk_3b')}</span></li>
</ul>
{tools_block(p)}
{world}
<section class="band wrap">
  <h2>{p.t('offers')}</h2>
  <p class="sub">{e(p.t('offers_sub', date=updated))}</p>
  {mosaic}
</section>
<section class="dark"><div class="wrap">
  <div class="head"><h2>{p.t('cheapest')}</h2><a href="{p.root}vols/">{p.t('see_all')}</a></div>
  <ul class="rows">{deals}</ul>
</div></section>
{newsletter_block(p)}
<section class="band wrap" id="preparer">
  <h2>{p.t('trip_title')}</h2>
  <p class="sub">{p.t('stay_lead')}</p>
  <div class="stays">{stay_links(p, "")}</div>
</section>
<section class="band wrap">
  <h2>{p.t('budget')}</h2>
  <div class="budgets">{budgets}</div>
</section>
<section class="band wrap two">
  <div><h2>{p.t('soon')}</h2><p class="sub">{p.t('soon_sub', days=SOON_DAYS)}</p><ul class="rows">{soon or nothing}</ul></div>
  <div><h2>{p.t('ahead')}</h2><p class="sub">{p.t('ahead_sub')}</p><ul class="rows">{ahead or nothing}</ul></div>
</section>
<section class="band wrap">
  <h2>{p.t('regions')}</h2>
  <div class="pills">{region_links}</div>
</section>
<section class="band wrap">
</section>"""
    return layout(p, f"{p.site['name']} — {p.t('title_home')}", p.t("meta_home"), "", body)


def tools_block(p):
    """Présente les fonctions du site dès l'accueil."""
    items = [("vols/", "tools_budget"), ("#recherche", "tools_search"), ("depuis/", "tools_world"), ("destinations/", "tools_places"),
             ("vols-pas-chers/", "tools_deals"), ("#newsletter", "tools_alert"), ("#preparer", "tools_trip"), ("#preparer", "tools_claim")]
    cards = "".join(
        f'<a class="stay" href="{p.root}{target}"><strong>{p.t(key)}</strong><span>{p.t(key + "_b")}</span></a>'
        for target, key in items
    )
    return f'<section class="band wrap"><h2>{p.t("tools_title")}</h2><div class="stays tools">{cards}</div></section>'


def flights_page(p, origins=()):
    default = DEFAULT_ORIGIN[p.lang]
    choices = "".join(
        f'<option value="{o["code"]}"{" selected" if o["code"] == default else ""}>{e(p.city(o["code"], o["code"]))}</option>'
        for o in sorted(origins, key=lambda o: p.city(o["code"], o["code"]))
    )
    origin = f'<label>{p.t("f_from")}<select id="origin">{choices}</select></label>' if origins else ""
    options = "".join(f'<option value="{v}">{p.euro(v)}</option>' for v in (50, 100, 200, 300, 400, 600, 1000))
    body = f"""<section class="page wrap">
  <h1>{p.t('flights_title')}</h1>
  <p class="lead">{p.t('flights_lead')}</p>
  <form class="filters" id="filters">
    {origin}
    <label>{p.t('f_search')}<input id="q" type="search" placeholder="{p.t('f_city')}"></label>
    <label>{p.t('f_region')}<select id="region"><option value="">{p.t('f_all_f')}</option></select></label>
    <label>{p.t('f_month')}<select id="month"><option value="">{p.t('f_all_m')}</option></select></label>
    <label>{p.t('f_budget')}<select id="budget"><option value="">{p.t('f_nolimit')}</option>{options}</select></label>
    <label>{p.t('f_length')}<select id="length"><option value="">{p.t('f_all_f')}</option><option value="0-7">{p.t('f_week')}</option><option value="8-21">{p.t('f_weeks')}</option><option value="22-999">{p.t('f_long')}</option></select></label>
    <label>{p.t('f_sort')}<select id="sort"><option value="price">{p.t('f_price')}</option><option value="depart">{p.t('f_date')}</option></select></label>
  </form>
  <p class="count" id="count" role="status"></p>
  <ul class="rows" id="offers"></ul>
  <button class="more" id="more" type="button" hidden></button>
</section>"""
    return layout(p, f"{p.t('flights_title')} | {p.site['name']}", p.t("flights_lead"), "vols/", body)


def world_destinations(origins):
    """Regroupe les routes publiées par destination."""
    published = {route["to"] for origin in origins for route in origin["pages"]}
    places = {}
    for origin in origins:
        for route in origin["routes"]:
            if route["to"] in published:
                place = places.setdefault(route["to"], {"code": route["to"], "slug": route["to_slug"], "routes": []})
                place["routes"].append((origin, route))
    for place in places.values():
        place["routes"].sort(key=lambda pair: pair[1]["price"])
    return sorted(places.values(), key=lambda place: place["slug"])


def world_places_index(p, places, zones):
    groups = {}
    for place in places:
        groups.setdefault(zones.get(place["code"], "XX"), []).append(place)
    blocks = ""
    for zone in sorted(groups, key=lambda z: (z == "XX", CONTINENTS[p.lang][z])):
        ordered = sorted(groups[zone], key=lambda place: p.city(place["code"], place["code"]))
        links = "".join(
            f'<li><a href="{p.root}vers/{place["slug"]}/"><span>{e(p.city(place["code"], place["code"]))}</span>'
            f'<span>{p.t("from_price", price=p.euro(place["routes"][0][1]["price"]))}</span></a></li>'
            for place in ordered
        )
        blocks += f'<section class="dest-group"><h2>{e(CONTINENTS[p.lang][zone])}</h2><ul class="links">{links}</ul></section>'
    lead = p.t("places_lead", count=len(places))
    body = f'<section class="page wrap"><h1>{p.t("places_title")}</h1><p class="lead">{lead}</p>{blocks}</section>'
    return layout(p, f"{p.t('places_title')} | {p.site['name']}", lead, "destinations/", body)


def world_place_page(p, place):
    city = p.city(place["code"], place["code"])
    values = {"count": len(place["routes"]), "price": p.euro(place["routes"][0][1]["price"])}
    rows = "".join(world_row(p, origin, route, p.city(origin["code"], origin["code"])) for origin, route in place["routes"])
    cover = ""
    if place["code"] in load_credits() and photo_exists(place["code"]):
        cover = f'<figure class="cover"><img {photo_set(p, place["code"], "(max-width: 1200px) 100vw, 1200px")} alt="{e(city)}"></figure>'
    body = f"""<section class="page wrap">
  <p class="crumb"><a href="{p.root}destinations/">{p.t('nav_places')}</a></p>
  <h1>{e(p.t('to_title', city=city))}</h1>
  {cover}
  <p class="lead">{p.t('to_lead', **values)}</p>
  <h2>{p.t('to_list')}</h2>
  <ul class="rows">{rows}</ul>
  <section class="panel"><h2>{e(p.t('stay_title', city=city))}</h2><p class="sub">{p.t('stay_lead')}</p><div class="stays">{stay_links(p, city)}</div></section>
</section>"""
    return layout(p, f"{p.t('to_title', city=city)} | {p.site['name']}", p.t("to_meta", city=city, **values), f"vers/{place['slug']}/", body)


def route_rows(p, origin):
    """Données de l'outil « où partir » pour une ville de départ."""
    rows = []
    for route in origin["routes"]:
        internal = has_page(origin, route)
        rows.append({
            "city": p.city(route["to"], route["to"]),
            "region": CONTINENTS[p.lang][p.zones.get(route["to"], "XX")],
            "price": route["price"], "depart": route["depart"], "back": route["back"], "stops": route["stops"],
            "href": f"{p.root}{route_path(origin, route)}" if internal else route["link"], "external": not internal,
        })
    return rows


def destinations_index(p, cities):
    groups = {}
    for city in cities:
        groups.setdefault(city["region"], []).append(city)
    blocks = ""
    for region in sorted(groups, key=lambda r: groups[r][0]["best"]["price"]):
        ordered = sorted(groups[region], key=lambda c: p.city(c["code"], c["city"]))
        links = "".join(
            f'<li><a href="{p.root}destinations/{c["slug"]}/"><span>{e(p.city(c["code"], c["city"]))}</span><span>{p.t("from_price", price=p.euro(c["best"]["price"]))}</span></a></li>'
            for c in ordered
        )
        blocks += f'<section class="dest-group"><h2>{e(p.region(region))}</h2><ul class="links">{links}</ul></section>'
    lead = p.t("places_lead", count=len(cities))
    body = f'<section class="page wrap"><h1>{p.t("places_title")}</h1><p class="lead">{lead}</p>{blocks}</section>'
    return layout(p, f"{p.t('places_title')} | {p.site['name']}", lead, "destinations/", body)


def collections(offers):
    """Sélections par mois, région et budget, gardées si elles couvrent assez de villes."""
    groups = []
    for key in sorted({o["depart"][:7] for o in offers}):
        month = int(key[5:])
        groups.append({"kind": "month", "slug": slug(MONTHS["fr"][month - 1]), "value": key,
                       "offers": [o for o in offers if o["depart"][:7] == key]})
    for region in sorted({o["region"] for o in offers}):
        groups.append({"kind": "region", "slug": slug(region), "value": region,
                       "offers": [o for o in offers if o["region"] == region]})
    for budget in BUDGETS:
        groups.append({"kind": "budget", "slug": f"moins-de-{budget}-euros", "value": budget,
                       "offers": [o for o in offers if o["price"] < budget]})
    kept, used = [], set()
    for group in groups:
        best = {}
        for offer in sorted(group["offers"], key=lambda o: o["price"]):
            best.setdefault(offer["code"], offer)
        if len(best) >= MIN_COLLECTION_CITIES and group["slug"] not in used:
            used.add(group["slug"])
            kept.append({**group, "best": list(best.values())})
    return kept


def collection_name(p, group):
    if group["kind"] == "month":
        return MONTHS[p.lang][int(group["value"][5:]) - 1]
    if group["kind"] == "region":
        return p.region(group["value"])
    return p.euro(group["value"])


def collection_title(p, group):
    return p.t(f"coll_{group['kind']}", name=collection_name(p, group))


def collection_links(p, groups):
    return "".join(
        f'<li><a href="{p.root}vols-pas-chers/{g["slug"]}/"><span>{e(collection_title(p, g))}</span>'
        f'<span>{p.t("from_price", price=p.euro(g["best"][0]["price"]))}</span></a></li>'
        for g in groups
    )


def collection_facts(p, group):
    cheapest = group["best"][0]
    facts = [p.t("coll_cheapest", city=e(p.city(cheapest["code"], cheapest["city"])), price=p.euro(cheapest["price"]),
                 start=e(p.day(cheapest["depart"], False)), end=e(p.day(cheapest["back"])))]
    direct = next((o for o in group["best"] if o.get("stops") == 0), None)
    if direct:
        facts.append(p.t("coll_direct", city=e(p.city(direct["code"], direct["city"])), price=p.euro(direct["price"])))
    if group["kind"] != "month":
        first = min(group["offers"], key=lambda o: o["price"])
        facts.append(p.t("coll_best_month", month=e(p.month(first["depart"][:7])), price=p.euro(first["price"])))
    if group["kind"] != "region":
        first = min(group["offers"], key=lambda o: o["price"])
        facts.append(p.t("coll_best_region", region=e(p.region(first["region"])), price=p.euro(first["price"])))
    return "".join(f"<li>{fact}</li>" for fact in facts)


def collection_page(p, group, groups, by_code, updated):
    title = collection_title(p, group)
    prices = [o["price"] for o in group["best"]]
    values = {"count": len(prices), "price": p.euro(prices[0]), "median": p.euro(median(prices))}
    rows = "".join(flight_row(p, o, by_code[o["code"]]) for o in group["best"][:COLLECTION_ROWS])
    others = [g for g in groups if g["kind"] == group["kind"] and g["slug"] != group["slug"]]
    more = f'<section class="panel"><h2>{p.t("coll_more")}</h2><ul class="links">{collection_links(p, others)}</ul></section>' if others else ""
    body = f"""<section class="page wrap">
  <p class="crumb"><a href="{p.root}vols-pas-chers/">{p.t('nav_deals')}</a></p>
  <h1>{e(title)}</h1>
  <p class="lead">{p.t('coll_lead', **values)}</p>
  <section class="panel"><h2>{p.t('coll_key')}</h2><ul class="guide">{collection_facts(p, group)}</ul></section>
  <ul class="rows">{rows}</ul>
  <p class="sub">{p.t('coll_note', updated=e(updated))}</p>
  {more}
</section>"""
    return layout(p, f"{title} | {p.site['name']}", p.t("coll_meta", **values), f"vols-pas-chers/{group['slug']}/", body)


def collections_index(p, groups):
    blocks = ""
    for kind, label in (("month", "deals_months"), ("region", "deals_regions"), ("budget", "deals_budgets")):
        links = collection_links(p, [g for g in groups if g["kind"] == kind])
        if links:
            blocks += f'<section class="dest-group"><h2>{p.t(label)}</h2><ul class="links">{links}</ul></section>'
    body = f'<section class="page wrap"><h1>{p.t("deals_title")}</h1><p class="lead">{p.t("deals_lead")}</p>{blocks}</section>'
    return layout(p, f"{p.t('deals_title')} | {p.site['name']}", p.t("deals_lead"), "vols-pas-chers/", body)


def clean_names(names):
    """Corrige les noms de ville manquants ou erronés de la source."""
    english = names.get("en", {})
    cleaned = {}
    for lang, rows in names.items():
        cleaned[lang] = {
            code: english.get(code, name) if name == code or name.startswith("Ville de ") else name
            for code, name in rows.items()
        }
        if "BUD" in cleaned[lang]:
            cleaned[lang]["BUD"] = "Budapest"
    return cleaned


def load_world(names):
    """Regroupe les prix mondiaux par ville de départ, si le relevé existe."""
    path = DOCS / "world.json"
    if not path.exists():
        return []
    routes = [r for r in json.loads(path.read_text())["routes"] if r["price"] <= MAX_ROUTE_PRICE and r["from"] in names and r["to"] in names]
    served = {}
    for route in routes:
        served.setdefault(route["to"], set()).add(route["from"])
    slugs, used = {}, set()
    for code in sorted({r["from"] for r in routes} | {r["to"] for r in routes}):
        name = slug(names[code]) or code.lower()
        slugs[code] = name if name not in used else f"{name}-{code.lower()}"
        used.add(slugs[code])
    origins = {}
    for route in sorted(routes, key=lambda r: r["price"]):
        origin = origins.setdefault(route["from"], {"code": route["from"], "slug": slugs[route["from"]], "routes": [], "pages": []})
        row = {**route, "to_slug": slugs[route["to"]]}
        origin["routes"].append(row)
        if len(served[route["to"]]) >= POPULAR_ORIGINS and len(origin["pages"]) < ROUTES_PER_ORIGIN:
            origin["pages"].append(row)
    return sorted(origins.values(), key=lambda o: slugs[o["code"]])


def origin_links(p, origins):
    return "".join(
        f'<li><a href="{p.root}depuis/{o["slug"]}/"><span>{e(p.city(o["code"], o["code"]))}</span>'
        f'<span>{p.t("from_price", price=p.euro(o["routes"][0]["price"]))}</span></a></li>'
        for o in origins
    )


def route_path(origin, route):
    return f"depuis/{origin['slug']}/{route['to_slug']}/"


def has_page(origin, route):
    return any(row["to"] == route["to"] for row in origin["pages"])


def world_row(p, origin, route, label=None):
    name = e(label or p.city(route["to"], route["to"]))
    detail = f'{e(p.day(route["depart"], False))} → {e(p.day(route["back"]))} · {e(p.t("days", count=nights(route)))} · {e(p.stops(route))}'
    title = f'<a href="{p.root}{route_path(origin, route)}">{name}</a>' if has_page(origin, route) else name
    action = (f'<a class="go" href="{p.root}{route_path(origin, route)}">{p.t("see")}</a>' if has_page(origin, route)
              else f'<a class="go" href="{e(route["link"])}" rel="nofollow sponsored noopener" target="_blank">{p.t("see")}</a>')
    return f"""<li class="row"><div class="row-info"><h3>{title}</h3><p>{detail}</p></div><p class="row-price">{p.euro(route['price'])}</p>{action}</li>"""


def world_deal(p, origin, route):
    name = f'{p.city(origin["code"], origin["code"])} → {p.city(route["to"], route["to"])}'
    detail = f'{e(p.day(route["depart"], False))} → {e(p.day(route["back"]))} · {e(p.t("days", count=nights(route)))} · {e(p.stops(route))}'
    page = f'{p.root}{route_path(origin, route)}'
    return f"""<li class="row"><div class="row-info"><h3><a href="{page}">{e(name)}</a></h3><p>{detail}</p></div><p class="row-price">{p.euro(route['price'])}</p><a class="go" href="{page}">{p.t('see')}</a></li>"""


def world_index(p, origins):
    body = f'<section class="page wrap"><h1>{p.t("world_title")}</h1><p class="lead">{p.t("world_lead")}</p><ul class="links">{origin_links(p, origins)}</ul></section>'
    return layout(p, f"{p.t('world_title')} | {p.site['name']}", p.t("world_lead"), "depuis/", body)


def origin_page(p, origin):
    city = p.city(origin["code"], origin["code"])
    values = {"count": len(origin["routes"]), "price": p.euro(origin["routes"][0]["price"])}
    rows = "".join(world_row(p, origin, r) for r in origin["routes"][:HUB_ROWS])
    body = f"""<section class="page wrap">
  <p class="crumb"><a href="{p.root}depuis/">{p.t('nav_world')}</a></p>
  <h1>{e(p.t('hub_title', city=city))}</h1>
  <p class="lead">{p.t('hub_lead', **values)}</p>
  <h2>{p.t('hub_all')}</h2>
  <ul class="rows">{rows}</ul>
</section>"""
    return layout(p, f"{p.t('hub_title', city=city)} | {p.site['name']}", p.t("hub_meta", city=city, **values), f"depuis/{origin['slug']}/", body)


def route_page(p, origin, route, origins, updated):
    start, end = p.city(origin["code"], origin["code"]), p.city(route["to"], route["to"])
    title = p.t("route_title", start=start, end=end)
    price = p.euro(route["price"])
    facts = [p.t("route_trip", days=e(p.t("days", count=nights(route))), stops=e(p.stops(route)))]
    reverse = next((o for o in origins if o["code"] == route["to"]), None)
    back = next((r for r in reverse["pages"] if r["to"] == origin["code"]), None) if reverse else None
    if back:
        facts.append(f'<a href="{p.root}{route_path(reverse, back)}">{p.t("route_back", end=e(end), start=e(start), price=p.euro(back["price"]))}</a>')
    items = "".join(f"<li>{fact}</li>" for fact in facts)
    others = sorted(
        ((o, r) for o in origins if o["code"] != origin["code"] for r in o["pages"] if r["to"] == route["to"]),
        key=lambda pair: pair[1]["price"],
    )[:6]
    from_others = "".join(
        f'<li><a href="{p.root}{route_path(o, r)}"><span>{e(p.city(o["code"], o["code"]))}</span><span>{p.t("from_price", price=p.euro(r["price"]))}</span></a></li>'
        for o, r in others
    )
    siblings = [r for r in origin["pages"] if r["to"] != route["to"]][:6]
    more = "".join(
        f'<li><a href="{p.root}{route_path(origin, r)}"><span>{e(p.city(r["to"], r["to"]))}</span><span>{p.t("from_price", price=p.euro(r["price"]))}</span></a></li>'
        for r in siblings
    )
    others_block = f'<section class="panel"><h2>{e(p.t("route_others", city=end))}</h2><ul class="links">{from_others}</ul></section>' if others else ""
    more_block = f'<section class="panel"><h2>{e(p.t("route_more", city=start))}</h2><ul class="links">{more}</ul></section>' if siblings else ""
    body = f"""<section class="page wrap">
  <p class="crumb"><a href="{p.root}depuis/">{p.t('nav_world')}</a> › <a href="{p.root}depuis/{origin['slug']}/">{e(start)}</a></p>
  <h1>{e(title)}</h1>
  <p class="lead">{p.t('route_lead', price=price, out=e(p.day(route['depart'], False)), back=e(p.day(route['back'])))}</p>
  <p><a class="go" href="{e(route['link'])}" rel="nofollow sponsored noopener" target="_blank">{p.t('check')}</a></p>
  <section class="panel"><h2>{p.t('route_key')}</h2><ul class="guide">{items}</ul><p class="sub">{p.t('route_note', updated=e(updated))}</p></section>
  <section class="panel"><h2>{e(p.t('stay_title', city=end))}</h2><p class="sub">{p.t('stay_lead')}</p><div class="stays">{stay_links(p, end)}</div></section>
  {others_block}
  {more_block}
</section>"""
    return layout(p, f"{title} | {p.site['name']}", p.t("route_meta", start=start, end=end, price=price), route_path(origin, route), body)


BOOKING_LOCALES = {"fr": "fr", "en": "en-gb", "es": "es"}


def stay_links(p, name):
    """Liens vers les partenaires, suivis dès que le programme est renseigné dans config.toml."""
    query = urllib.parse.quote(name)
    hotel = f"https://www.booking.com/searchresults.{BOOKING_LOCALES[p.lang]}.html?ss={query}"
    tour = f"https://www.tiqets.com/{p.lang}/search?q={query}"

    def tracked(url, kind):
        program = p.site.get(f"{kind}_program")
        if not program:
            return url
        return radar.partner_link(url, {**p.site, "program": program, "campaign": p.site[f"{kind}_campaign"]})

    def card(url, title, text):
        return f'<a class="stay" href="{e(url)}" rel="nofollow sponsored noopener" target="_blank"><strong>{title}</strong><span>{text}</span></a>'

    claim = f"https://www.airhelp.com/{p.lang}/"
    esim = "https://www.airalo.com/" + ("" if p.lang == "en" else p.lang)
    transfer = f"https://kiwitaxi.com/{p.lang}"
    car = f"https://localrent.com/{p.lang}/"
    return (card(tracked(hotel, "hotels"), p.t("stay_hotel"), p.t("stay_hotel_b"))
            + card(tracked(tour, "tours"), p.t("stay_tour"), p.t("stay_tour_b"))
            + card(tracked(car, "cars"), p.t("stay_car"), p.t("stay_car_b"))
            + card(tracked(esim, "esim"), p.t("stay_esim"), p.t("stay_esim_b"))
            + card(tracked(transfer, "transfers"), p.t("stay_transfer"), p.t("stay_transfer_b"))
            + card(tracked(claim, "claims"), p.t("stay_claim"), p.t("stay_claim_b")))


def guide_block(p, city, months):
    """Repères calculés à partir des prix relevés, sans texte inventé."""
    if len(months) < 2:
        return ""
    ordered = sorted(months.items(), key=lambda item: item[1]["price"])
    low_key, low = ordered[0]
    high_key, high = ordered[-1]
    direct = sum(1 for offer in months.values() if offer.get("stops") == 0)
    name = p.city(city["code"], city["city"])
    points = [
        p.t("guide_best", month=p.month(low_key), price=p.euro(low["price"])),
        p.t("guide_high", month=p.month(high_key), price=p.euro(high["price"])),
    ]
    if direct:
        points.append(p.t("guide_direct", count=direct, total=len(months)))
    items = "".join(f"<li>{e(point)}</li>" for point in points)
    return f'<section class="panel"><h2>{e(p.t("guide_title", city=name))}</h2><ul class="guide">{items}</ul><p class="sub">{p.t("guide_note")}</p></section>'


def merged_history(city):
    days = {}
    for offer in city["offers"]:
        for when, price in offer.get("history", []):
            days[when] = min(price, days.get(when, price))
    return [[when, days[when]] for when in sorted(days)]


def destination_page(p, city, cities):
    best = city["best"]
    months = {}
    for offer in city["offers"]:
        key = offer["depart"][:7]
        if key not in months or offer["price"] < months[key]["price"]:
            months[key] = offer
    rows = "".join(
        f'<tr id="m-{key}"><th scope="row">{e(p.month(key).capitalize())}</th><td>{e(p.day(o["depart"]))} → {e(p.day(o["back"]))}</td>'
        f'<td>{e(p.stops(o))}</td><td class="num">{p.euro(o["price"])}</td>'
        f'<td><a class="go" href="{e(o["link"])}" rel="nofollow sponsored noopener" target="_blank">{p.t("check")}</a></td></tr>'
        for key, o in sorted(months.items())
    )
    history = merged_history(city)
    chart = ""
    if len(history) >= 3:
        data = e(json.dumps(history, separators=(",", ":")))
        chart = f'<section class="panel"><h2>{p.t("history")}</h2><div class="chart" data-history="{data}"></div></section>'
    others = [c for c in cities if c["region"] == city["region"] and c["code"] != city["code"]][:6]
    related = "".join(
        f'<li><a href="{p.root}destinations/{c["slug"]}/"><span>{e(p.city(c["code"], c["city"]))}</span><span>{p.t("from_price", price=p.euro(c["best"]["price"]))}</span></a></li>'
        for c in others
    )
    related_block = f'<section class="panel"><h2>{e(p.t("others", region=p.region(city["region"])))}</h2><ul class="links">{related}</ul></section>' if others else ""
    name = e(p.city(city["code"], city["city"]))
    credits = load_credits()
    cover = ""
    if city["code"] in credits and photo_exists(city["code"]):
        cover = f'<figure class="cover"><img {photo_set(p, city["code"], "(max-width: 1200px) 100vw, 1200px")} alt="{name}"></figure>'
    body = f"""<section class="page wrap">
  <p class="crumb"><a href="{p.root}destinations/">{p.t('nav_places')}</a> › {e(p.region(city['region']))}</p>
  <h1>{e(p.t('dest_title', city=p.city(city['code'], city['city'])))}</h1>
  {cover}
  <p class="lead">{p.t('dest_lead', price=p.euro(best['price']), month=e(p.month(best['depart'][:7])))}</p>
  <aside class="notice"><strong>{p.t('dest_why')}</strong> {p.t('dest_why_b')}</aside>
  <section class="panel"><h2>{p.t('best_month')}</h2>
    <div class="scroll"><table><thead><tr><th scope="col">{p.t('t_month')}</th><th scope="col">{p.t('t_dates')}</th><th scope="col">{p.t('t_stops')}</th><th scope="col" class="num">{p.t('t_price')}</th><th scope="col"><span class="sr">{p.t('t_link')}</span></th></tr></thead><tbody>{rows}</tbody></table></div>
  </section>
  {guide_block(p, city, months)}
  <section class="panel"><h2>{e(p.t('stay_title', city=p.city(city['code'], city['city'])))}</h2><p class="sub">{p.t('stay_lead')}</p><div class="stays">{stay_links(p, p.city(city['code'], city['city']))}</div></section>
  {chart}
  {related_block}
</section>"""
    title = f"{p.t('dest_title', city=p.city(city['code'], city['city']))} | {p.site['name']}"
    return layout(p, title, p.t("dest_meta", city=p.city(city["code"], city["city"])), f"destinations/{city['slug']}/", body)


def about_page(p):
    items = "".join(f"<details><summary>{e(q)}</summary><p>{e(a)}</p></details>" for q, a in TEXT[p.lang]["faq"])
    body = f'<section class="page wrap narrow"><h1>{p.t("info_title")}</h1><p class="lead">{p.t("info_lead")}</p><div class="faq">{items}</div><a class="search-go" href="{p.root}">{p.t("info_go")}</a></section>'
    return layout(p, f"{p.t('info_title')} | {p.site['name']}", p.t("info_meta"), "a-propos/", body)


def credits_page(p):
    credits = load_credits()
    rows = "".join(
        f'<li><strong>{e(p.city(code, credit["city"]))}</strong><br>{photo_credit(p, credit)}</li>'
        for code, credit in sorted(credits.items(), key=lambda item: item[1]["city"]) if photo_exists(code)
    )
    body = f'<section class="page wrap narrow"><h1>{p.t("credits")}</h1><p class="lead">{p.t("credits_lead")}</p><ul class="credit-list">{rows}</ul></section>'
    return layout(p, f"{p.t('credits')} | {p.site['name']}", p.t("credits_lead"), "credits/", body)


def missing_page(p):
    body = f'<section class="page wrap narrow"><h1>{p.t("missing")}</h1><p class="lead">{p.t("missing_lead")}</p><a class="search-go" href="{p.root}">{p.t("back_home")}</a></section>'
    return layout(p, f"{p.t('missing')} | {p.site['name']}", p.t("missing_lead"), "404.html", body)


def test_booking_page(p):
    mode = p.t("test_server") if p.site.get("test_api") else p.t("test_demo")
    body = f"""<section class="page wrap narrow">
  <p class="notice"><strong>{p.t('test_banner', mode=mode)}</strong> {p.t('test_banner_b')}</p>
  <div id="booking" tabindex="-1" data-api="{e(p.site.get('test_api', ''))}"></div>
</section>"""
    extra = f'<script src="{p.base}assets/booking.js?v={p.site["version"]}" defer></script>'
    return layout(p, f"{p.t('test_title')} | {p.site['name']}", p.t("test_meta"), "test-reservation/", body, noindex=True, extra=extra)


def write(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def city_index(places, countries):
    rows = [
        [code, place["name"], countries.get(place["country"], "")]
        for code, place in places.items() if place["airports"]
    ]
    return sorted(rows, key=lambda row: row[1])


def build_language(p, data, cities, updated_at, groups, origins=()):
    lang, folder = p.lang, p.folder
    updated = f"{updated_at.day} {MONTHS[lang][updated_at.month - 1]}, {updated_at:%H:%M} UTC"
    offers = data["offers"]
    translated = [
        {**offer, "city": p.city(offer["code"], offer["city"]), "region": p.region(offer["region"]), "region_key": offer["region"]}
        for offer in offers
    ]
    if lang != "fr":
        write(folder / "prices.json", json.dumps({**data, "offers": translated}, ensure_ascii=False, separators=(",", ":")) + "\n")
    write(folder / "index.html", home(p, cities, offers, updated, origins))
    world = folder / "depuis"
    if world.exists():
        shutil.rmtree(world)
    if origins:
        write(world / "index.html", world_index(p, origins))
    for origin in origins:
        write(world / origin["slug"] / "index.html", origin_page(p, origin))
        for route in origin["pages"]:
            write(world / origin["slug"] / route["to_slug"] / "index.html", route_page(p, origin, route, origins, updated))
    write(folder / "vols" / "index.html", flights_page(p, origins))
    places = world_destinations(origins)
    write(folder / "destinations" / "index.html", world_places_index(p, places, p.zones) if places else destinations_index(p, cities))
    to_world = folder / "vers"
    if to_world.exists():
        shutil.rmtree(to_world)
    for place in places:
        write(to_world / place["slug"] / "index.html", world_place_page(p, place))
    for origin in origins:
        write(DOCS / "assets" / "routes" / lang / f"{origin['code']}.json", json.dumps(route_rows(p, origin), ensure_ascii=False, separators=(",", ":")))
    write(folder / "a-propos" / "index.html", about_page(p))
    deals = folder / "vols-pas-chers"
    if deals.exists():
        shutil.rmtree(deals)
    by_code = {c["code"]: c for c in cities}
    write(deals / "index.html", collections_index(p, groups))
    for group in groups:
        write(deals / group["slug"] / "index.html", collection_page(p, group, groups, by_code, updated))
    write(folder / "test-reservation" / "index.html", test_booking_page(p))
    write(folder / "credits" / "index.html", credits_page(p))
    keep = {c["slug"] for c in cities}
    for child in (folder / "destinations").iterdir():
        if child.is_dir() and child.name not in keep:
            shutil.rmtree(child)
    for city in cities:
        write(folder / "destinations" / city["slug"] / "index.html", destination_page(p, city, cities))


def asset_version():
    """Change dès qu'un fichier du site change, pour que les navigateurs le rechargent."""
    digest = hashlib.sha256()
    for name in ("app.js", "booking.js", "style.css"):
        path = DOCS / "assets" / name
        if path.exists():
            digest.update(path.read_bytes())
    return digest.hexdigest()[:12]


def build(data, site, catalog=None):
    """catalog associe chaque langue à (villes, pays), quand les listes sont disponibles."""
    site = dict(site)
    after = site["url"].split("//", 1)[1]
    site["root"] = "/" + after.split("/", 1)[1] if "/" in after else "/"
    site["version"] = asset_version()
    offers = data["offers"]
    cities = destinations(offers)
    slugs = {c["code"]: c["slug"] for c in cities}
    for offer in offers:
        offer["slug"] = slugs[offer["code"]]
    updated_at = datetime.fromisoformat(data["updated"])
    write(DOCS / "prices.json", json.dumps(data, ensure_ascii=False, separators=(",", ":")) + "\n")
    names_path = DOCS / "assets" / "names.json"
    names = json.loads(names_path.read_text()) if names_path.exists() else {}
    for lang, (places, countries) in (catalog or {}).items():
        names[lang] = {code: place["name"] for code, place in places.items() if place["airports"]}
        rows = city_index(places, countries)
        write(DOCS / "assets" / f"cities-{lang}.json", json.dumps(rows, ensure_ascii=False, separators=(",", ":")))
    names = clean_names(names)
    if catalog:
        write(names_path, json.dumps(names, ensure_ascii=False, separators=(",", ":")))
    groups = collections(offers)
    origins = load_world(names.get("fr", {}))
    zones_path = DOCS / "assets" / "zones.json"
    zones = json.loads(zones_path.read_text()) if zones_path.exists() else {}
    for lang in LANGS:
        page = Page(site, lang, names.get(lang))
        page.zones = zones
        build_language(page, data, cities, updated_at, groups, origins)
    write(DOCS / "404.html", missing_page(Page(site, "fr", names.get("fr"))))
    pages = ["", "vols/", "vols-pas-chers/", "destinations/", "a-propos/"] + [f"destinations/{c['slug']}/" for c in cities]
    pages += [f"vols-pas-chers/{g['slug']}/" for g in groups]
    if origins:
        pages.append("depuis/")
    for origin in origins:
        pages.append(f"depuis/{origin['slug']}/")
        pages += [route_path(origin, route) for route in origin["pages"]]
    pages += [f"vers/{place['slug']}/" for place in world_destinations(origins)]
    urls = "".join(
        f"<url><loc>{e(site['url'] + ('' if lang == 'fr' else lang + '/') + page)}</loc></url>"
        for lang in LANGS for page in pages
    )
    write(DOCS / "sitemap.xml", f'<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{urls}</urlset>\n')
    write(DOCS / "robots.txt", f"User-agent: *\nAllow: /\nSitemap: {site['url']}sitemap.xml\n")
    return len(cities)


def continent(row):
    zone, country = (row.get("time_zone") or "").split("/")[0], row.get("country_code")
    if country in SOUTH_AMERICA:
        return "SA"
    if country in ("US", "CA", "MX"):
        return "NA"
    if country == "CV":
        return "AF"
    return {"Africa": "AF", "America": "NA", "Cuba": "NA", "Asia": "AS", "Europe": "EU", "Atlantic": "EU",
            "Australia": "OC", "Pacific": "OC", "Indian": "IN"}.get(zone, "XX")


def load_catalog():
    rows = radar.http_json(f"{radar.TP_BASE}/data/en/cities.json")
    write(DOCS / "assets" / "zones.json", json.dumps({row["code"]: continent(row) for row in rows}, separators=(",", ":")))
    catalog = {}
    for lang in LANGS:
        places = radar.load_places(lang)
        rows = radar.http_json(f"{radar.TP_BASE}/data/{lang}/countries.json")
        catalog[lang] = (places, {row["code"]: row.get("name") or row["code"] for row in rows})
    return catalog


def main():
    config = tomllib.loads((ROOT / "config.toml").read_text())
    path = DOCS / "prices.json"
    if not path.exists():
        print("prices.json manquant : site non construit.", file=sys.stderr)
        return 1
    data = json.loads(path.read_text())
    try:
        catalog = load_catalog()
    except RuntimeError as error:
        print(f"Listes des villes non mises à jour : {error}", file=sys.stderr)
        catalog = None
    count = build(data, config["site"], catalog)
    print(f"{count} destinations générées en {len(LANGS)} langues.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
