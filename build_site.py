#!/usr/bin/env python3
"""Génère le site statique multilingue d'Eunodia à partir de docs/prices.json."""
import hashlib
import html
import json
import math
import re
import shutil
import sys
import tomllib
import unicodedata
import urllib.parse
from datetime import date, datetime
from statistics import median
from zoneinfo import ZoneInfo
from pathlib import Path

import radar
from site_text import (BAROMETER, BOOKING_LOCALES, CONTINENTS, DATA_LANGS, FULL_LANGS, LANG_NAMES, LANGS, LOCALES, MONTHS, NEAR_TITLES, NEWS_DONE, REGIONS,
                       RTL_LANGS, SCRIPT_TEXT, SHORT_MONTHS, TEXT)

ROOT = Path(__file__).parent
DOCS = ROOT / "docs"
SOON_DAYS = 45
AHEAD_DAYS = 150
BUDGETS = (100, 200, 500)
MIN_COLLECTION_CITIES = 3
COLLECTION_ROWS = 40
ROUTES_PER_ORIGIN = 40           # pages de route créées par ville de départ
POPULAR_ORIGINS = 10             # une destination doit être desservie depuis autant de villes
ALWAYS_LISTED = {"YQB"}          # destinations affichées même desservies depuis moins de villes
MAX_ROUTE_PRICE = 3000           # écarte les prix aberrants
HUB_ROWS = 60
DEFAULT_ORIGIN = {"fr": "PAR", "en": "LON", "es": "MAD", "de": "BER", "it": "ROM", "pt": "LIS", "nl": "AMS", "tr": "IST", "ar": "RUH", "zh": "HKG", "ko": "SEL"}
BACKUP_ORIGIN = {"ar": "DXB"}
PARTNER_LANGS = ("fr", "en", "es", "de", "it", "pt")
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
        self.countries = {}
        self.geo = {}

    def t(self, key, **values):
        if key == "days" and values.get("count") == 1:
            key = "day_one"
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


def cover_code(p, code):
    """La photo de la ville, sinon celle d'une autre ville du même pays."""
    if photo_exists(code):
        return code
    cities = p.countries.get("cities", {})
    country = cities.get(code)
    return next((other for other, place in sorted(cities.items()) if place == country and photo_exists(other)), "") if country else ""


def photo_set(p, code, sizes):
    """Sert la version 4K aux grands écrans, et la version légère aux autres."""
    light = f"{p.base}assets/photos/{code}.jpg"
    if not (DOCS / "assets" / "photos" / f"{code}-4k.jpg").exists():
        if (DOCS / "assets" / "photos" / f"{code}-m.jpg").exists():
            return f'src="{light}" srcset="{p.base}assets/photos/{code}-m.jpg 640w, {light} 1600w" sizes="{sizes}" decoding="async"'
        return f'src="{light}"'
    small = f"{p.base}assets/photos/{code}-m.jpg"
    return f'src="{light}" srcset="{small} 828w, {light} 1280w, {p.base}assets/photos/{code}-4k.jpg 3840w" sizes="{sizes}" decoding="async"'


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


PAGE_TOP = re.compile(
    r'<section class="page wrap(?P<narrow> narrow)?">\s*(?P<crumb><p class="crumb">.*?</p>)?\s*<h1>(?P<title>.*?)</h1>\s*'
    r'(?P<cover><figure class="cover">.*?</figure>)?\s*(?P<lead><p class="lead">.*?</p>)?\s*'
    r'(?P<cta><p><a class="go".*?</a></p>)?', re.S)


def page_hero(p, path, body, photo=None):
    """Donne aux pages intérieures un en-tête photo : celle de la ville, ou aucune si elle manque."""
    top = PAGE_TOP.search(body)
    photos = sorted(code for code in load_credits() if photo_exists(code))
    if not top:
        return body
    own = re.search(r"assets/photos/([A-Z]{3})\.jpg", top["cover"] or "")
    if photo is None:
        city_page = path.startswith(("vers/", "destinations/")) and path != "destinations/"
        photo = own[1] if own else "" if city_page else photos[sum(path.encode()) % len(photos)] if photos else ""
    image = f'<img class="hero-img" {photo_set(p, photo, "100vw").replace("async", "sync")} fetchpriority="high" alt="">' if photo else ""
    videos = f' data-videos="{p.base}assets/video/" data-names="{CUSTOM_VIDEOS}"' if path == CUSTOM_PATH else ""
    hero = (f'<section class="page-hero"{videos}>{image}'
            f'<div class="page-hero-in wrap">{top["crumb"] or ""}<h1>{top["title"]}</h1>{top["lead"] or ""}{top["cta"] or ""}</div></section>'
            f'<section class="page wrap{top["narrow"] or ""}">')
    return body[:top.start()] + hero + body[top.end():]


def schema_tag(data):
    return f'<script type="application/ld+json">{json.dumps(data, ensure_ascii=False).replace("</", "<\\/")}</script>'


def breadcrumbs(p, items):
    """Fil d'Ariane lisible par Google."""
    base = p.site["url"] + p.prefix
    return schema_tag({
        "@context": "https://schema.org", "@type": "BreadcrumbList",
        "itemListElement": [{"@type": "ListItem", "position": n, "name": name, "item": base + path}
                            for n, (name, path) in enumerate(items, 1)],
    })


SOCIAL_ICONS = {
    "instagram": '<rect x="3" y="3" width="18" height="18" rx="5"/><circle cx="12" cy="12" r="4"/><circle cx="17.3" cy="6.7" r=".6" fill="currentColor"/>',
    "tiktok": '<path d="M14 3v11.5a3.5 3.5 0 1 1-3.5-3.5M14 3c.4 2.6 2.2 4.4 5 4.6"/>',
}


def social_profiles(site):
    """Comptes Instagram et TikTok renseignés dans config.toml : (nom, adresse, icône)."""
    rows = []
    if site.get("instagram"):
        rows.append(("Instagram", f"https://www.instagram.com/{site['instagram']}/", "instagram"))
    if site.get("tiktok"):
        rows.append(("TikTok", f"https://www.tiktok.com/@{site['tiktok']}", "tiktok"))
    return rows


def social_links(site):
    links = "".join(
        f'<a href="{e(url)}" rel="me noopener" target="_blank" aria-label="{name}">'
        f'<svg viewBox="0 0 24 24" aria-hidden="true">{SOCIAL_ICONS[icon]}</svg></a>'
        for name, url, icon in social_profiles(site))
    return f'<p class="foot-social">{links}</p>' if links else ""


def site_schema(p):
    url = p.site["url"]
    return schema_tag([
        {"@context": "https://schema.org", "@type": "WebSite", "name": p.site["name"], "url": url, "inLanguage": LOCALES[p.lang]},
        {"@context": "https://schema.org", "@type": "Organization", "name": p.site["name"], "url": url,
         "logo": f"{url}assets/icon-512.png", "email": "contact@eunodia.com", "sameAs": [u for _, u, _ in social_profiles(p.site)]},
    ])


def distance_km(a, b):
    lat1, lon1, lat2, lon2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 6371 * 2 * math.asin(math.sqrt(h))


def time_difference(a, b, day):
    """Écart en heures entre deux villes à une date donnée, ou None si un fuseau manque."""
    moment = datetime.fromisoformat(f"{day}T12:00:00")
    try:
        first = moment.replace(tzinfo=ZoneInfo(a[2])).utcoffset()
        second = moment.replace(tzinfo=ZoneInfo(b[2])).utcoffset()
    except (KeyError, IndexError, TypeError, ValueError):
        return None
    return (second - first).total_seconds() / 3600


def page_langs(path):
    """Les pages de route et la réservation test n'existent que dans les langues principales."""
    if path.startswith("voyage-sur-mesure"):
        return ("fr",)
    return FULL_LANGS if path.startswith("test-reservation") or re.fullmatch(r"depuis/[^/]+/[^/]+/", path) else LANGS


# Vérification du site par Impact (programme d'affiliation Omio) : seulement sur la page d'accueil.
IMPACT_SCRIPT = """<script type="text/javascript">(function(i,m,p,a,c,t){c.ire_o=p;c[p]=c[p]||function(){(c[p].a=c[p].a||[]).push(arguments)};t=a.createElement(m);var z=a.getElementsByTagName(m)[0];t.async=1;t.src=i;z.parentNode.insertBefore(t,z)})('https://utt.impactcdn.com/P-A8164987-c216-40f7-a20e-12ac200872c71.js','script','impactStat',document,window);impactStat('transformLinks');impactStat('trackImpression');</script>"""


def layout(p, title, description, path, body, noindex=False, extra="", photo=None):
    site, base, root = p.site, p.base, p.root
    body = page_hero(p, path, body, photo)
    name = e(site["name"])
    links = "".join(
        f'<link rel="alternate" hreflang="{lang}" href="{e(site["url"] + ("" if lang == "fr" else lang + "/") + path)}">'
        for lang in page_langs(path)
    )
    flights_nav = f'<a href="{root}vols/">{p.t("nav_flights")}</a>'
    custom = p.lang == "fr"
    first_nav = f'<a class="nav-cta" href="{root}{CUSTOM_PATH}">Voyage sur mesure</a>' if custom else flights_nav
    late_nav = flights_nav + "\n    " if custom else ""
    switch = "".join(
        f'<a href="{base}{"" if lang == "fr" else lang + "/"}{path}" lang="{lang}" hreflang="{lang}"'
        f'{" aria-current=\"true\"" if lang == p.lang else ""} title="{LANG_NAMES[lang]}">{LANG_NAMES[lang]}</a>'
        for lang in page_langs(path)
    )
    shared = {key: TEXT[p.lang][key] for key in ("see", "check", "direct", "stop", "stops", "stops_unknown", "days", "day_one")}
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
<html lang="{p.lang}"{' dir="rtl"' if p.lang in RTL_LANGS else ''}>
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
<meta name="theme-color" content="#0b0b0b">
<link rel="icon" href="{base}assets/icon.svg?v=3" type="image/svg+xml">
<link rel="apple-touch-icon" href="{base}assets/icon-180.png">
<link rel="manifest" href="{base}manifest.webmanifest">
<link rel="preload" href="{base}assets/clash-600.woff2" as="font" type="font/woff2" crossorigin>
<link rel="preload" href="{base}assets/geist.woff2" as="font" type="font/woff2" crossorigin>
<link rel="stylesheet" href="{base}assets/style.css?v={version}">
<script>window.RF={script}</script>
<script src="{base}assets/app.js?v={version}" defer></script>
{extra}
{analytics}
{IMPACT_SCRIPT if p.lang == 'fr' and path == '' else ''}
</head>
<body>
<header class="nav">
  <a class="logo" href="{root}" aria-label="{name}">{LOGO}{name}</a>
  <nav aria-label="Menu" id="menu">
    {first_nav}
    <a href="{root}depuis/">{p.t('nav_world')}</a>
    <a href="{root}destinations/">{p.t('nav_places')}</a>
    <a href="{root}vols-pas-chers/">{p.t('nav_deals')}</a>
    {late_nav}<a href="{root}{WHO_PATH}">{e(WHO.get(p.lang, WHO["en"])["nav"])}</a><a href="{root}a-propos/">{p.t('nav_info')}</a>
  </nav>
  <details class="langs"><summary aria-label="Langue">{p.lang.upper()}</summary><div class="langs-list">{switch}</div></details>
  <button class="menu-btn" id="menu-btn" type="button" aria-expanded="false" aria-controls="menu" aria-label="{p.t('menu')}"><span></span><span></span><span></span></button>
</header>
<main>
{body}
</main>
<footer class="foot">
  <div class="wrap foot-in">
    <div><p class="foot-brand">{LOGO}{name}</p>{social_links(p.site)}</div>
    <div>
      <p>{p.t('foot_1')}</p>
      <p>{p.t('foot_2', name=name)}</p>
    </div>
    <p class="foot-links"><a href="{root}depuis/">{p.t('nav_world')}</a><a href="{root}vols/">{p.t('nav_flights')}</a><a href="{root}vols-pas-chers/">{p.t('nav_deals')}</a><a href="{root}barometre/">{e(BAROMETER[p.lang][0])}</a><a href="{root}destinations/">{p.t('nav_places')}</a><a href="{root}{WHO_PATH}">{e(WHO.get(p.lang, WHO["en"])["nav"])}</a><a href="{root}a-propos/">{p.t('nav_info')}</a><a href="{root}credits/">{p.t('credits')}</a><a href="mailto:contact@eunodia.com">contact@eunodia.com</a></p>
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
    currency = WHITE_LABEL_CURRENCY.get(p.lang, "eur").upper()
    return f"""<form class="search" id="search" data-target="https://www.aviasales.com/search/" data-results="{p.root}{RESULTS_PATH}" data-currency="{currency}" autocomplete="off">
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


HOTEL_KEYS = ("flights", "hotels", "city", "place", "in", "out", "guests", "go", "pick", "note")
HOTEL_WORDS = {
    "fr": ("Vols", "Hôtels", "Ville", "Lisbonne, Tokyo, Marrakech…", "Arrivée", "Départ", "Voyageurs", "Chercher",
           "Choisis une ville dans la liste.", "Tu réserves sur Klook, au prix affiché. Plus de villes arrivent bientôt."),
    "en": ("Flights", "Hotels", "City", "Lisbon, Tokyo, Marrakech…", "Check-in", "Check-out", "Guests", "Search",
           "Pick a city from the list.", "You book on Klook, at the price shown. More cities coming soon."),
    "es": ("Vuelos", "Hoteles", "Ciudad", "Lisboa, Tokio, Marrakech…", "Llegada", "Salida", "Viajeros", "Buscar",
           "Elige una ciudad de la lista.", "Reservas en Klook, al precio indicado. Pronto habrá más ciudades."),
    "pt": ("Voos", "Hotéis", "Cidade", "Lisboa, Tóquio, Marraquexe…", "Check-in", "Check-out", "Viajantes", "Pesquisar",
           "Escolhe uma cidade da lista.", "Reservas na Klook, ao preço indicado. Mais cidades em breve."),
    "it": ("Voli", "Hotel", "Città", "Lisbona, Tokyo, Marrakech…", "Arrivo", "Partenza", "Viaggiatori", "Cerca",
           "Scegli una città dall'elenco.", "Prenoti su Klook, al prezzo indicato. Presto altre città."),
    "de": ("Flüge", "Hotels", "Stadt", "Lissabon, Tokio, Marrakesch…", "Anreise", "Abreise", "Reisende", "Suchen",
           "Wähle eine Stadt aus der Liste.", "Du buchst bei Klook zum angezeigten Preis. Weitere Städte folgen bald."),
    "nl": ("Vluchten", "Hotels", "Stad", "Lissabon, Tokio, Marrakesh…", "Inchecken", "Uitchecken", "Reizigers", "Zoeken",
           "Kies een stad uit de lijst.", "Je boekt bij Klook, tegen de getoonde prijs. Binnenkort meer steden."),
    "tr": ("Uçuşlar", "Oteller", "Şehir", "Lizbon, Tokyo, Marakeş…", "Giriş", "Çıkış", "Misafir", "Ara",
           "Listeden bir şehir seç.", "Klook'ta gösterilen fiyattan rezervasyon yaparsın. Yakında daha fazla şehir."),
    "ar": ("رحلات", "فنادق", "المدينة", "لشبونة، طوكيو، مراكش…", "الوصول", "المغادرة", "المسافرون", "بحث",
           "اختر مدينة من القائمة.", "تحجز على Klook بالسعر المعروض. المزيد من المدن قريبًا."),
    "zh": ("机票", "酒店", "城市", "里斯本、东京、马拉喀什…", "入住", "退房", "人数", "搜索",
           "请从列表中选择城市。", "在 Klook 按显示价格预订。更多城市即将上线。"),
    "ko": ("항공권", "호텔", "도시", "리스본, 도쿄, 마라케시…", "체크인", "체크아웃", "인원", "검색",
           "목록에서 도시를 선택하세요.", "Klook에서 표시된 가격으로 예약합니다. 곧 더 많은 도시가 추가됩니다."),
}
KLOOK_LANG = {"fr": "fr", "en": "en-US", "es": "es", "de": "de", "it": "it", "pt": "pt-BR", "nl": "nl", "ko": "ko", "zh": "zh-CN"}


def klook_cities():
    path = ROOT / "klook_cities.json"
    if not path.exists():
        return {}
    return {code: value for code, value in json.loads(path.read_text()).items() if not code.startswith("_")}


def hotel_search(p, cities=()):
    """Onglets Vols / Hôtels et recherche d'hôtels Klook (villes relevées dans klook_cities.json)."""
    fr = p.lang == "fr"
    words = dict(zip(HOTEL_KEYS, HOTEL_WORDS.get(p.lang, HOTEL_WORDS["en"])))
    rows = sorted(([p.city(code, code), str(value), code] for code, value in klook_cities().items()), key=lambda row: row[0])
    data = e(json.dumps(rows, ensure_ascii=False, separators=(",", ":")))
    guests = "".join(f"<option{' selected' if n == 2 else ''}>{n}</option>" for n in range(1, 7))
    tabs = (f'<div class="search-tabs" role="tablist"><button type="button" class="on" data-show="search">{words["flights"]}</button>'
            f'<button type="button" data-show="hotel-search">{words["hotels"]}</button>'
            + (f'<button type="button" data-show="train-search">{TRAIN_WORDS.get(p.lang, TRAIN_WORDS["en"])[0]}</button>' if omio_data(p.lang) else "")
            + '</div>')
    form = f"""<form class="search hotel-search" id="hotel-search" data-cities="{data}" data-lang="{KLOOK_LANG.get(p.lang, "en-US")}" autocomplete="off" hidden>
  <div class="field grow"><label for="h-city">{words['city']}</label><input id="h-city" placeholder="{e(words['place'])}" required>
    <ul class="suggest" hidden></ul></div>
  <div class="field"><label for="h-in">{words['in']}</label><input id="h-in" type="date"></div>
  <div class="field"><label for="h-out">{words['out']}</label><input id="h-out" type="date"></div>
  <div class="field small"><label for="h-guests">{words['guests']}</label><select id="h-guests">{guests}</select></div>
  <button class="search-go" type="submit">{words['go']}</button>
  <p class="form-error" id="hotel-error" role="alert" hidden>{words['pick']}</p>
  <p class="hotel-note">{words['note']}</p>
</form>"""
    return tabs, form + train_search(p, cities)


# Omio (trains, bus, ferries) : programme d'affiliation direct sur Impact (compte 8164987), accepté le 10/11/2026.
# omio.py récupère chaque jour les catalogues Omio dans docs/omio/<langue>.json ; la recherche se fait sur le site
# et le bouton de réservation mène chez Omio avec le lien de suivi Impact.
OMIO_FALLBACK = "en"
# Lien de redirection officiel Omio (outil d'affiliation, onglet « Redirect link ») : passe par le suivi Impact
# avec le numéro de partenaire et ouvre directement la page de résultats pour le départ, l'arrivée et les dates.
OMIO_REDIRECT = "https://omio.sjv.io/c/8164987/4057579/7385?u="
OMIO_LINKS = "https://www.omio.com/links/626fa8a9-f982-43d0-ace9-9a13f6b14612"
OMIO_LOCALE = {"fr": "fr", "en": "en", "es": "es", "de": "de", "it": "it", "pt": "pt", "nl": "nl", "tr": "tr", "ar": "ar", "zh": "zh", "ko": "ko"}
TRAIN_KEYS = ("tab", "note", "from", "from_place", "to", "to_place", "go", "price_from", "book", "none", "pick", "more", "loading")
TRAIN_DATES = {"fr": ("Aller", "Retour"), "en": ("Depart", "Return"), "es": ("Ida", "Vuelta"), "de": ("Hinfahrt", "Rückfahrt"),
               "it": ("Andata", "Ritorno"), "pt": ("Ida", "Volta"), "nl": ("Heen", "Terug"), "tr": ("Gidiş", "Dönüş"),
               "ar": ("الذهاب", "العودة"), "zh": ("去程", "返程"), "ko": ("가는 날", "오는 날")}
TRAIN_WORDS = {
    "fr": ("Train & bus", "Prix « dès » relevés chaque jour par Omio. Tu réserves chez Omio, au prix affiché.",
           "Départ", "Paris, Lyon, Madrid…", "Arrivée", "Partout", "Rechercher", "dès", "Voir les horaires",
           "Pas encore de prix pour ce trajet ici : vois directement les horaires chez Omio.", "Choisis une ville de départ dans la liste.",
           "Chercher sur Omio", "Chargement des trajets…"),
    "en": ("Trains & buses", "“From” prices updated daily by Omio. You book with Omio at the price shown.",
           "From", "London, Paris, Madrid…", "To", "Anywhere", "Search", "from", "See times",
           "No price for this route here yet: check times directly on Omio.", "Pick a departure city from the list.",
           "Search on Omio", "Loading routes…"),
    "es": ("Tren y bus", "Precios «desde» actualizados cada día por Omio. Reservas en Omio al precio indicado.",
           "Salida", "Madrid, Barcelona, París…", "Llegada", "Cualquier destino", "Buscar", "desde", "Ver horarios",
           "Aún no hay precio para este trayecto aquí: consulta los horarios en Omio.", "Elige una ciudad de salida de la lista.",
           "Buscar en Omio", "Cargando trayectos…"),
    "de": ("Zug & Bus", "„Ab“-Preise, täglich von Omio aktualisiert. Du buchst bei Omio zum angezeigten Preis.",
           "Abfahrt", "Berlin, München, Paris…", "Ziel", "Überallhin", "Suchen", "ab", "Verbindungen ansehen",
           "Für diese Strecke gibt es hier noch keinen Preis: sieh dir die Verbindungen direkt bei Omio an.", "Wähle eine Abfahrtsstadt aus der Liste.",
           "Bei Omio suchen", "Strecken werden geladen…"),
    "it": ("Treno e bus", "Prezzi «da» aggiornati ogni giorno da Omio. Prenoti su Omio al prezzo indicato.",
           "Partenza", "Roma, Milano, Parigi…", "Arrivo", "Ovunque", "Cerca", "da", "Vedi gli orari",
           "Nessun prezzo per questa tratta qui: guarda gli orari direttamente su Omio.", "Scegli una città di partenza dall'elenco.",
           "Cerca su Omio", "Caricamento tratte…"),
    "pt": ("Trem e ônibus", "Preços «a partir de» atualizados todos os dias pela Omio. Você reserva na Omio pelo preço exibido.",
           "Partida", "Lisboa, Porto, Madri…", "Chegada", "Qualquer lugar", "Buscar", "a partir de", "Ver horários",
           "Ainda não há preço para este trajeto aqui: veja os horários diretamente na Omio.", "Escolha uma cidade de partida na lista.",
           "Buscar na Omio", "Carregando trajetos…"),
    "nl": ("Trein & bus", "Vanafprijzen, dagelijks bijgewerkt door Omio. Je boekt bij Omio, tegen de getoonde prijs.",
           "Vertrek", "Amsterdam, Brussel, Parijs…", "Bestemming", "Overal", "Zoeken", "vanaf", "Bekijk tijden",
           "Nog geen prijs voor deze route hier: bekijk de tijden direct bij Omio.", "Kies een vertrekstad uit de lijst.",
           "Zoeken bij Omio", "Routes laden…"),
    "tr": ("Tren ve otobüs", "Omio'nun her gün güncellediği başlangıç fiyatları. Omio'da gösterilen fiyattan rezervasyon yaparsın.",
           "Kalkış", "Londra, Paris, Roma…", "Varış", "Her yer", "Ara", "başlangıç", "Saatleri gör",
           "Bu güzergah için burada henüz fiyat yok: saatlere doğrudan Omio'dan bak.", "Listeden bir kalkış şehri seç.",
           "Omio'da ara", "Güzergahlar yükleniyor…"),
    "ar": ("قطار وحافلة", "أسعار تبدأ من، تحدّثها Omio يوميًا. تحجز على Omio بالسعر المعروض.",
           "المغادرة", "لندن، باريس، روما…", "الوصول", "أي مكان", "بحث", "ابتداءً من", "عرض المواعيد",
           "لا يوجد سعر لهذا المسار هنا بعد: اطّلع على المواعيد مباشرة في Omio.", "اختر مدينة المغادرة من القائمة.",
           "البحث في Omio", "جارٍ تحميل المسارات…"),
    "zh": ("火车和巴士", "Omio 每日更新的起价。在 Omio 按显示价格预订。",
           "出发", "巴黎、伦敦、罗马…", "到达", "任意目的地", "搜索", "起", "查看时刻",
           "这里暂时没有该线路的价格：请直接在 Omio 查看时刻。", "请从列表中选择出发城市。",
           "在 Omio 搜索", "正在加载线路…"),
    "ko": ("기차·버스", "Omio가 매일 업데이트하는 최저가입니다. Omio에서 표시된 가격으로 예약합니다.",
           "출발", "런던, 파리, 로마…", "도착", "어디든", "검색", "부터", "시간표 보기",
           "이 노선의 가격은 아직 없습니다. Omio에서 시간표를 확인하세요.", "목록에서 출발 도시를 선택하세요.",
           "Omio에서 검색", "노선 불러오는 중…"),
}


def omio_data(lang):
    """Fichier de trajets Omio utilisé pour cette langue (ou None s'il n'a pas encore été récupéré)."""
    for code in (lang, OMIO_FALLBACK):
        if (DOCS / "omio" / f"{code}.json").exists():
            return code
    return None


def train_search(p, cities=()):
    """Recherche trains / bus de l'accueil : les trajets Omio sont chargés au clic sur l'onglet et les offres
    s'affichent sous le formulaire après la recherche."""
    data = omio_data(p.lang)
    if not data:
        return ""
    w = dict(zip(TRAIN_KEYS, TRAIN_WORDS.get(p.lang, TRAIN_WORDS["en"])))
    dates = TRAIN_DATES.get(p.lang, TRAIN_DATES["en"])
    texts = e(json.dumps({k: w[k] for k in ("price_from", "book", "none", "pick", "more", "loading")}, ensure_ascii=False))
    # photos du site pour les villes qu'Omio ne fournit pas (nom de la ville dans la langue -> code de la photo)
    photos = {}
    known = {c["code"]: c.get("city", c["code"]) for c in cities}
    known.update({code: name for code, name in p.names.items() if isinstance(name, str)})
    for code in sorted(known):
        if photo_exists(code):
            photos.setdefault(p.city(code, known[code]).lower(), code)
    photos = e(json.dumps(photos, ensure_ascii=False, separators=(",", ":")))
    return f"""<form class="search train-search" id="train-search" data-src="/omio/{data}.json" data-lang="{p.lang}" data-words="{texts}"
  data-photos="{photos}" data-photo-root="{p.base}assets/photos/" data-redirect="{e(OMIO_REDIRECT)}" data-omio-links="{e(OMIO_LINKS)}"
  data-omio-locale="{OMIO_LOCALE.get(p.lang, 'en')}" autocomplete="off" hidden>
  <div class="field grow"><label for="t-from">{w['from']}</label><input id="t-from" placeholder="{e(w['from_place'])}" required>
    <ul class="suggest" hidden></ul></div>
  <div class="field grow"><label for="t-to">{w['to']}</label><input id="t-to" placeholder="{e(w['to_place'])}">
    <ul class="suggest" hidden></ul></div>
  <div class="field"><label for="t-out">{dates[0]}</label><input id="t-out" type="date"></div>
  <div class="field"><label for="t-back">{dates[1]}</label><input id="t-back" type="date"></div>
  <button class="search-go" type="submit">{w['go']}</button>
  <p class="form-error" id="train-error" role="alert" hidden>{w['pick']}</p>
  <div class="train-results" id="train-results" aria-live="polite"></div>
  <p class="hotel-note">{w['note']}</p>
</form>"""


def home(p, cities, offers, updated, origins=()):
    today = date.today()
    by_code = {c["code"]: c for c in cities}
    credits = load_credits()
    pictured = [c for c in cities if c["code"] in credits and photo_exists(c["code"])]
    best = cities[0]["best"]
    choices = sorted(code for code in credits if photo_exists(code))
    hero_code = choices[(today - date(1970, 1, 1)).days % len(choices)] if choices else ""
    hero_image = f'<img class="hero-img" {photo_set(p, hero_code, "100vw").replace("async", "sync")} fetchpriority="high" alt="">' if hero_code else ""
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
    near_titles = NEAR_TITLES[p.lang]
    near_city = p.city("PAR", "Paris")
    near_script = ""
    local = default_origin(p, origins)
    if local:
        near_city = p.city(local["code"], local["code"])

        def pick(rule):
            seen, kept = set(), []
            for route in local["routes"]:
                gap = (date.fromisoformat(route["depart"]) - today).days
                if rule(gap) and route["to"] not in seen:
                    seen.add(route["to"])
                    kept.append(route)
            return kept[:4]

        soon = "".join(world_row(p, local, r) for r in pick(lambda gap: gap <= SOON_DAYS))
        ahead = "".join(world_row(p, local, r) for r in pick(lambda gap: gap >= AHEAD_DAYS))
        near_data = {"soon": SOON_DAYS, "ahead": AHEAD_DAYS, "default": local["code"], "titles": near_titles,
                     "origins": [[o["code"], p.city(o["code"], o["code"]), (p.geo.get(o["code"]) or [0, 0, ""])[2]] for o in origins]}
        near_script = f'<script>window.RFNEAR={json.dumps(near_data, ensure_ascii=False).replace("</", "<\\/")}</script>'
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
        world = f'''<section class="band wrap"><h2>{p.t("world_home")}</h2><p class="sub">{p.t("world_home_sub", count=len(origins))}</p><ul class="links cities">{origin_links(p, origins)}</ul><p class="all-cities"><a href="{p.root}depuis/">{p.t("world_all")}</a></p></section>'''
    body = f"""<section class="hero" data-videos="{p.base}assets/video/" data-names="rome-steps,rome-castle,rome-basilica,paris,new-york">
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
{custom_block(p)}
{tools_block(p)}
<section class="trip" id="preparer">
  <img class="hero-img" {photo_set(p, "BKK" if photo_exists("BKK") else hero_code, "100vw")} alt="" loading="lazy">
  <div class="trip-in wrap">
    <h2>{p.t('trip_title')}</h2>
    <p>{p.t('trip_lead')}</p>
    <div class="stays">{stay_links(p, "")}</div>
  </div>
</section>
<section class="band wrap">
  <h2>{p.t('offers')}</h2>
  <p class="sub">{e(p.t('offers_sub', date=updated))}</p>
  {mosaic}
</section>
{world}
<section class="dark"><div class="wrap">
  <div class="head"><h2>{p.t('cheapest')}</h2><a href="{p.root}vols/">{p.t('see_all')}</a></div>
  <ul class="rows">{deals}</ul>
</div></section>
{newsletter_block(p)}
<section class="band wrap">
  <h2>{p.t('budget')}</h2>
  <div class="budgets">{budgets}</div>
</section>
<section class="band wrap two">
  <div><h2 id="soon-title">{e(near_titles[0].format(city=near_city))}</h2><p class="sub">{p.t('soon_sub', days=SOON_DAYS)}</p><ul class="rows" id="soon-list">{soon or nothing}</ul></div>
  <div><h2 id="ahead-title">{e(near_titles[1].format(city=near_city))}</h2><p class="sub">{p.t('ahead_sub')}</p><ul class="rows" id="ahead-list">{ahead or nothing}</ul></div>
</section>
{ticker_block(p, origins)}
<section class="band wrap"{' hidden' if origins else ''}>
  <h2>{p.t('regions')}</h2>
  <div class="pills">{region_links}</div>
</section>
<section class="band wrap">
</section>"""
    return layout(p, f"{p.site['name']} — {p.t('title_home')}", p.t("meta_home"), "", body, extra=site_schema(p) + near_script)


def ticker_block(p, origins):
    """Bandeau continu : le meilleur prix relevé pour chaque pays."""
    cities = p.countries.get("cities", {})
    names = p.countries.get("names", {}).get(p.lang, {})
    published = {route["to"] for origin in origins for route in origin["pages"]}
    best = {}
    for origin in origins:
        for route in origin["routes"]:
            country = cities.get(route["to"])
            if country in names and (country not in best or route["price"] < best[country][1]["price"]):
                best[country] = (origin, route)
    if not best:
        return ""
    items = ""
    for country in sorted(best, key=lambda code: names[code]):
        origin, route = best[country]
        city = p.city(route["to"], route["to"])
        href = (f"{p.root}vers/{route['to_slug']}/" if route["to"] in published
                else f"{p.root}vols/?origin={origin['code']}&amp;q={urllib.parse.quote(city)}")
        items += f'<li><a href="{href}">{e(names[country])}<span>{p.t("from_price", price=p.euro(route["price"]))}</span></a></li>'
    copy = items.replace("<a ", '<a tabindex="-1" ')
    return f"""<section class="ticker-box"><h2 class="wrap">{p.t('ticker')}</h2>
<div class="ticker" style="--time:{len(best) * 3}s"><div class="ticker-track"><ul>{items}</ul><ul aria-hidden="true">{copy}</ul></div></div></section>"""


def tools_block(p):
    """Présente les fonctions du site dès l'accueil."""
    items = [("vols/", "tools_budget"), ("destinations/", "tools_places"), ("vols-pas-chers/", "tools_deals"), ("#newsletter", "tools_alert")]
    cards = "".join(
        f'<a class="stay" href="{p.root}{target}"><strong>{p.t(key)}</strong><span>{p.t(key + "_b")}</span></a>'
        for target, key in items
    )
    return f'<section class="band wrap"><h2>{p.t("tools_title")}</h2><div class="stays tools">{cards}</div></section>'


def default_origin(p, origins):
    """La ville de la langue, ou la plus proche disponible, puis Paris."""
    wanted = (DEFAULT_ORIGIN[p.lang], BACKUP_ORIGIN.get(p.lang), "PAR")
    return next((o for code in wanted for o in origins if o["code"] == code), None)


def flights_page(p, origins=()):
    chosen = default_origin(p, origins)
    default = chosen["code"] if chosen else ""
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
    <label class="adv">{p.t('f_search')}<input id="q" type="search" placeholder="{p.t('f_city')}"></label>
    <label class="adv">{p.t('f_region')}<select id="region"><option value="">{p.t('f_all_f')}</option></select></label>
    <label>{p.t('f_month')}<select id="month"><option value="">{p.t('f_all_m')}</option></select></label>
    <label>{p.t('f_budget')}<select id="budget"><option value="">{p.t('f_nolimit')}</option>{options}</select></label>
    <label class="adv">{p.t('f_length')}<select id="length"><option value="">{p.t('f_all_f')}</option><option value="0-7">{p.t('f_week')}</option><option value="8-21">{p.t('f_weeks')}</option><option value="22-999">{p.t('f_long')}</option></select></label>
    <label class="adv">{p.t('f_sort')}<select id="sort"><option value="price">{p.t('f_price')}</option><option value="depart">{p.t('f_date')}</option></select></label>
    <button class="more-filters" id="more-filters" type="button">{p.t('f_more')}</button>
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
    # Une photo ne sert qu'une fois sur la page : une ville sans photo à elle
    # garde un fond uni plutôt que de répéter celle d'une voisine.
    used = {place["code"] for place in places if photo_exists(place["code"])}
    for zone in sorted(groups, key=lambda z: (z == "XX", CONTINENTS[p.lang][z])):
        ordered = sorted(groups[zone], key=lambda place: p.city(place["code"], place["code"]))
        covers = {}
        for place in ordered:
            cover = cover_code(p, place["code"])
            if cover != place["code"]:
                cover = "" if cover in used else cover
                used.add(cover)
            covers[place["code"]] = cover
        cards = "".join(
            f'<li><a class="place" href="{p.root}vers/{place["slug"]}/">'
            + (f'<img {photo_set(p, covers[place["code"]], "(max-width: 640px) 50vw, 25vw")} alt="" loading="lazy">' if covers[place["code"]] else "")
            + f'<span class="place-name">{e(p.city(place["code"], place["code"]))}</span>'
            f'<span class="place-price">{p.t("from_price", price=p.euro(place["routes"][0][1]["price"]))}</span></a></li>'
            for place in ordered
        )
        blocks += f'<section class="dest-group"><h2>{e(CONTINENTS[p.lang][zone])}</h2><ul class="places">{cards}</ul></section>'
    lead = p.t("places_lead", count=len(places))
    body = f'<section class="page wrap"><h1>{p.t("places_title")}</h1><p class="lead">{lead}</p>{blocks}</section>'
    return layout(p, f"{p.t('places_title')} | {p.site['name']}", lead, "destinations/", body)


def duration_label(p, hours):
    """3.5 → « 3 h 30 » (« 3h 30m » en anglais), arrondi à la demi-heure."""
    total = max(30, round(hours * 2) * 30)
    h, m = divmod(total, 60)
    if p.lang == "en":
        return f"{h}h {m:02d}m" if m else f"{h}h"
    return f"{h} h {m:02d}" if m else f"{h} h"


def place_facts(p, place, now=None):
    """Bloc « en bref » et questions fréquentes d'une destination, calculés à partir des prix et de la géographie."""
    origin, route = place["routes"][0]
    city = p.city(place["code"], place["code"])
    start = p.city(origin["code"], origin["code"])
    values = {"city": city, "origin": start, "price": p.euro(route["price"]),
              "depart": p.day(route["depart"]), "back": p.day(route["back"])}
    others = []
    for other, _ in place["routes"]:
        name = p.city(other["code"], other["code"])
        if name not in others:
            others.append(name)
    facts = [(p.t("fact_price"), p.t("fact_price_v", **values))]
    faq = [(p.t("q_price", **values), p.t("a_price", **values))]
    here, there = p.geo.get(origin["code"]), p.geo.get(place["code"])
    if here and there:
        lat1, lon1, lat2, lon2 = map(math.radians, (here[0], here[1], there[0], there[1]))
        km = 6371 * 2 * math.asin(math.sqrt(math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2))
        if km >= 150:
            label = f"{round(km, -1):,.0f}"
            label = label if p.lang == "en" else label.replace(",", " ")
            time = duration_label(p, km / 800 + 0.5)
            facts.append((p.t("fact_flight"), p.t("fact_flight_v", time=time, km=label, **values)))
            faq.append((p.t("q_time", **values), p.t("a_time", time=time, **values)))
        try:
            moment = now or datetime.now(ZoneInfo("UTC"))
            gap = (moment.astimezone(ZoneInfo(there[2])).utcoffset() - moment.astimezone(ZoneInfo(here[2])).utcoffset()).total_seconds() / 3600
        except Exception:
            gap = None
        if gap is not None:
            if gap:
                sign = "+" if gap > 0 else "−"
                diff = sign + duration_label(p, abs(gap)).replace("h 00", "h")
                facts.append((p.t("fact_tz"), p.t("fact_tz_v", diff=diff, **values)))
                faq.append((p.t("q_tz", **values), p.t("a_tz", diff=diff, **values)))
            else:
                facts.append((p.t("fact_tz"), p.t("fact_tz_none", **values)))
                faq.append((p.t("q_tz", **values), p.t("a_tz_none", **values)))
    if len(others) > 1:
        shown = ", ".join(others[:4])
        facts.append((p.t("fact_from"), p.t("fact_from_v", count=len(others), list=shown)))
        faq.append((p.t("q_from", **values), p.t("a_from", count=len(others), list=shown, **values)))
    rows = "".join(f"<div><dt>{e(label)}</dt><dd>{e(value)}</dd></div>" for label, value in facts)
    questions = "".join(f"<details><summary>{e(q)}</summary><p>{e(a)}</p></details>" for q, a in faq)
    block = (f'<section class="panel"><h2>{e(p.t("facts_title", city=city))}</h2><dl class="facts">{rows}</dl></section>'
             f'<section class="panel"><h2>{p.t("place_faq")}</h2><div class="faq">{questions}</div></section>')
    schema = schema_tag({"@context": "https://schema.org", "@type": "FAQPage",
                         "mainEntity": [{"@type": "Question", "name": q, "acceptedAnswer": {"@type": "Answer", "text": a}} for q, a in faq]})
    return block, schema


def world_place_page(p, place):
    city = p.city(place["code"], place["code"])
    values = {"count": len(place["routes"]), "price": p.euro(place["routes"][0][1]["price"])}
    rows = "".join(world_row(p, origin, route, p.city(origin["code"], origin["code"])) for origin, route in place["routes"])
    cover = ""
    if place["code"] in load_credits() and photo_exists(place["code"]):
        cover = f'<figure class="cover"><img {photo_set(p, place["code"], "(max-width: 1200px) 100vw, 1200px")} alt="{e(city)}"></figure>'
    facts, faq_schema = place_facts(p, place)
    body = f"""<section class="page wrap">
  <p class="crumb"><a href="{p.root}destinations/">{p.t('nav_places')}</a></p>
  <h1>{e(p.t('to_title', city=city))}</h1>
  {cover}
  <p class="lead">{p.t('to_lead', **values)}</p>
  <p><a class="go" href="{e(place['routes'][0][1]['link'])}" rel="nofollow sponsored noopener" target="_blank">{p.t('check')}</a></p>
  {musts_block(p, place['code'], city)}
  <h2>{p.t('to_list')}</h2>
  <ul class="rows">{rows}</ul>
  {facts}
  <section class="panel"><h2>{e(p.t('stay_title', city=city))}</h2><p class="sub">{p.t('stay_lead')}</p><div class="stays">{stay_links(p, city, place['code'])}</div></section>
</section>"""
    return layout(p, f"{p.t('to_title', city=city)} | {p.site['name']}", p.t("to_meta", city=city, **values), f"vers/{place['slug']}/", body,
                  extra=breadcrumbs(p, [(p.t("nav_places"), "destinations/"), (city, f"vers/{place['slug']}/")]) + faq_schema)


def route_rows(p, origin):
    """Données de l'outil « où partir » pour une ville de départ."""
    rows = []
    for route in origin["routes"]:
        internal = has_page(p, origin, route)
        rows.append({
            "city": p.city(route["to"], route["to"]),
            "region": CONTINENTS[p.lang][p.zones.get(route["to"], "XX")],
            "price": route["price"], "depart": route["depart"], "back": route["back"], "stops": route["stops"],
            "href": f"{p.root}{route_path(origin, route)}" if internal else route["link"], "external": not internal,
            "buy": route["link"],
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


def deals_picker(p, origins):
    """Choix de la ville de départ des bons plans ; les autres villes sont affichées par app.js."""
    if not origins:
        return ""
    chosen = default_origin(p, origins)
    options = "".join(
        f'<option value="{o["code"]}"{" selected" if chosen and o["code"] == chosen["code"] else ""}>{e(p.city(o["code"], o["code"]))}</option>'
        for o in sorted(origins, key=lambda o: p.city(o["code"], o["code"]))
    )
    text = {"title": p.t("hub_title"), "months": p.t("deals_months"), "regions": p.t("deals_regions"), "budgets": p.t("deals_budgets"),
            "under": p.t("under"), "from": p.t("from_price"), "count": p.t("places_count")}
    return (f'<form class="filters deals-pick"><label>{p.t("f_from")}<select id="deals-origin" data-text="{e(json.dumps(text, ensure_ascii=False))}">'
            f'{options}</select></label></form>')


def collections_index(p, groups, origins=()):
    blocks = ""
    for kind, label in (("month", "deals_months"), ("region", "deals_regions"), ("budget", "deals_budgets")):
        links = collection_links(p, [g for g in groups if g["kind"] == kind])
        if links:
            blocks += f'<section class="dest-group"><h2>{p.t(label)}</h2><ul class="links">{links}</ul></section>'
    body = (f'<section class="page wrap"><h1>{p.t("deals_title")}</h1><p class="lead">{p.t("deals_lead")}</p>'
            f'{deals_picker(p, origins)}<div id="deals-list">{blocks}</div></section>')
    return layout(p, f"{p.t('deals_title')} | {p.site['name']}", p.t("deals_lead"), "vols-pas-chers/", body)


LATIN_LANGS = ("fr", "en", "es", "de", "it", "pt", "nl", "tr")
SHARED_NAME_FIXES = {
    "AYQ": "Uluru", "BOB": "Bora-Bora", "CAE": "Columbia", "DPS": "Bali", "EAS": "San Sebastián", "EIS": "Tortola", "FAE": "Vágar",
    "GNY": "Şanlıurfa", "IGD": "Iğdır", "JER": "Jersey", "LOP": "Lombok", "OST": "Ostende", "POS": "Port of Spain", "TAB": "Tobago",
}
NAME_FIXES = {
    "en": {"AER": "Sochi", "LAX": "Los Angeles", "OST": "Ostend"},
    "de": {"LAX": "Los Angeles"}, "it": {"LAX": "Los Angeles", "OST": "Ostenda"}, "pt": {"LAX": "Los Angeles"},
    "fr": {
        "AAR": "Aarhus", "ACE": "Lanzarote", "ACH": "Saint-Gall", "AER": "Sotchi", "AES": "Ålesund", "AGH": "Ängelholm", "AJI": "Ağrı",
        "AUA": "Aruba", "AZS": "Samaná", "BDS": "Brindisi", "BJM": "Bujumbura", "BJX": "León (Mexique)", "BLA": "Barcelona (Venezuela)",
        "BNI": "Benin City", "BOC": "Bocas del Toro", "BON": "Bonaire", "BRN": "Berne", "BXU": "Butuan", "BZE": "Belize City",
        "CGY": "Cagayan de Oro", "CIY": "Comiso", "CJM": "Chumphon", "CJU": "Jeju", "CPC": "San Martín de los Andes", "CUR": "Curaçao",
        "DLU": "Dali", "DOM": "Dominique", "DYG": "Zhangjiajie", "DZA": "Mayotte", "EBL": "Erbil", "ECP": "Panama City (Floride)",
        "EDI": "Édimbourg", "EYP": "El Yopal", "FDF": "Fort-de-France", "FEN": "Fernando de Noronha", "FEZ": "Fès", "FNC": "Madère",
        "FUO": "Foshan", "GCI": "Guernesey", "GND": "La Grenade", "GPS": "Îles Galápagos", "GRO": "Gérone", "GRV": "Grozny", "GRX": "Grenade",
        "HAS": "Haïl", "IAS": "Iași", "IOM": "Île de Man", "IWA": "Ivanovo", "JDF": "Juiz de Fora", "JDO": "Juazeiro do Norte",
        "JSI": "Skiathos", "JTR": "Santorin", "KGS": "Cos", "KKC": "Khon Kaen", "KOP": "Nakhon Phanom", "LAX": "Los Angeles", "LCA": "Larnaca",
        "LDY": "Derry", "LEN": "León (Espagne)", "LJG": "Lijiang", "LPA": "Las Palmas de Gran Canaria", "LZY": "Nyingchi", "NOJ": "Noïabrsk",
        "NSK": "Norilsk", "NTG": "Nantong", "OSA": "Osaka", "PAP": "Port-au-Prince", "PAS": "Paros", "POS": "Port-d'Espagne", "PTY": "Panama",
        "PUS": "Busan", "RJL": "Logroño", "RRG": "Rodrigues", "RUN": "La Réunion", "SAP": "San Pedro Sula", "SBH": "Saint-Barthélemy",
        "SCQ": "Saint-Jacques-de-Compostelle", "SDQ": "Saint-Domingue", "SEZ": "Mahé (Seychelles)", "SFG": "Saint-Martin (Grand-Case)",
        "SJP": "São José do Rio Preto", "SMS": "Île Sainte-Marie", "SRQ": "Sarasota", "STL": "Saint-Louis", "SVD": "Saint-Vincent",
        "TAC": "Tacloban", "TCI": "Tenerife", "TIF": "Taïf", "TRR": "Trincomalee", "TUC": "Tucumán", "VXE": "São Vicente", "ZTH": "Zante",
        "ZVK": "Savannakhet", "EAS": "Saint-Sébastien",
    },
}


def clean_names(names):
    """Corrige les noms de ville manquants ou erronés de la source."""
    english = names.get("en", {})
    cleaned = {}
    for lang, rows in names.items():
        cleaned[lang] = {
            code: english.get(code, name) if name == code or name.startswith("Ville de ") or name.endswith("机场") else name
            for code, name in rows.items()
        }
        if "BUD" in cleaned[lang]:
            cleaned[lang]["BUD"] = "Budapest"
        fixes = {**(SHARED_NAME_FIXES if lang in LATIN_LANGS else {}), **NAME_FIXES.get(lang, {})}
        cleaned[lang].update({code: name for code, name in fixes.items() if code in cleaned[lang]})
    return cleaned


def retrack(value, project):
    """Rattache les liens Travelpayouts déjà enregistrés au projet actuel."""
    if not project:
        return value
    if isinstance(value, dict):
        return {key: retrack(item, project) for key, item in value.items()}
    if isinstance(value, list):
        return [retrack(item, project) for item in value]
    if isinstance(value, str) and value.startswith("https://tp.media/r?"):
        return re.sub(r"([?&]trs=)[^&]*", lambda m: m.group(1) + str(project), value)
    return value


def load_world(names, project=None):
    """Regroupe les prix mondiaux par ville de départ, si le relevé existe."""
    path = DOCS / "world.json"
    if not path.exists():
        return []
    routes = [r for r in retrack(json.loads(path.read_text()), project)["routes"] if r["price"] <= MAX_ROUTE_PRICE and r["from"] in names and r["to"] in names]
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
        if route["to"] in ALWAYS_LISTED or (len(served[route["to"]]) >= POPULAR_ORIGINS and len(origin["pages"]) < ROUTES_PER_ORIGIN):
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


def has_page(p, origin, route):
    return p.lang in FULL_LANGS and any(row["to"] == route["to"] for row in origin["pages"])


def world_row(p, origin, route, label=None):
    name = e(label or p.city(route["to"], route["to"]))
    detail = f'{e(p.day(route["depart"], False))} → {e(p.day(route["back"]))} · {e(p.t("days", count=nights(route)))} · {e(p.stops(route))}'
    outside = f'href="{e(route["link"])}" rel="nofollow sponsored noopener" target="_blank"'
    title = f'<a href="{p.root}{route_path(origin, route)}">{name}</a>' if has_page(p, origin, route) else f'<a {outside}>{name}</a>'
    action = f'<a class="go buy" {outside}>{p.t("check")}</a>'
    return f"""<li class="row"><div class="row-info"><h3>{title}</h3><p>{detail}</p></div><p class="row-price">{p.euro(route['price'])}</p>{action}</li>"""


def barometer_rows(p, pairs):
    return "".join(world_deal(p, origin, route) for origin, route in pairs)


def barometer_page(p, origins, updated):
    title, lead, far, near, zones_title, note, median_label = BAROMETER[p.lang]
    pairs = sorted(((o, r) for o in origins for r in o["routes"]), key=lambda pair: pair[1]["price"])

    def unique(items, limit):
        seen, kept = set(), []
        for origin, route in items:
            if route["to"] not in seen:
                seen.add(route["to"])
                kept.append((origin, route))
            if len(kept) == limit:
                break
        return kept

    def long_haul(pair):
        a, b = p.geo.get(pair[0]["code"]), p.geo.get(pair[1]["to"])
        return bool(a and b and distance_km(a, b) >= 5000)

    by_zone = {}
    for origin, route in pairs:
        by_zone.setdefault(p.zones.get(route["to"], "XX"), []).append(route["price"])
    zone_rows = "".join(
        f'<li><span class="stat">{e(CONTINENTS[p.lang][z])}</span><span>{e(median_label.format(price=p.euro(median(v))))}</span></li>'
        for z, v in sorted(by_zone.items(), key=lambda item: median(item[1])) if z != "XX"
    )
    body = f"""<section class="page wrap">
  <h1>{e(title)}</h1>
  <p class="lead">{e(lead)}</p>
  <h2>{e(far)}</h2>
  <ul class="rows">{barometer_rows(p, unique(filter(long_haul, pairs), 10))}</ul>
  <h2>{e(near)}</h2>
  <ul class="rows">{barometer_rows(p, unique(pairs, 10))}</ul>
  <h2>{e(zones_title)}</h2>
  <ul class="links zones">{zone_rows}</ul>
  <p class="sub">{e(note.format(updated=updated))}</p>
</section>"""
    return layout(p, f"{title} | {p.site['name']}", lead, "barometre/", body, extra=breadcrumbs(p, [(title, "barometre/")]))


def world_deal(p, origin, route):
    name = f'{p.city(origin["code"], origin["code"])} → {p.city(route["to"], route["to"])}'
    detail = f'{e(p.day(route["depart"], False))} → {e(p.day(route["back"]))} · {e(p.t("days", count=nights(route)))} · {e(p.stops(route))}'
    internal = p.lang in FULL_LANGS
    internal = internal and has_page(p, origin, route)
    page = f'{p.root}{route_path(origin, route)}' if internal else e(route["link"])
    extra = "" if internal else ' rel="nofollow sponsored noopener" target="_blank"'
    return f"""<li class="row"><div class="row-info"><h3><a href="{page}"{extra}>{e(name)}</a></h3><p>{detail}</p></div><p class="row-price">{p.euro(route['price'])}</p><a class="go" href="{page}"{extra}>{p.t('see')}</a></li>"""


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
  <p><a class="go" href="{e(origin['routes'][0]['link'])}" rel="nofollow sponsored noopener" target="_blank">{p.t('check')}</a></p>
  <h2>{p.t('hub_all')}</h2>
  <ul class="rows">{rows}</ul>
</section>"""
    return layout(p, f"{p.t('hub_title', city=city)} | {p.site['name']}", p.t("hub_meta", city=city, **values), f"depuis/{origin['slug']}/", body,
                  extra=breadcrumbs(p, [(p.t("nav_world"), "depuis/"), (city, f"depuis/{origin['slug']}/")]),
                  photo=origin["code"] if photo_exists(origin["code"]) else "")


def route_page(p, origin, route, origins, updated):
    start, end = p.city(origin["code"], origin["code"]), p.city(route["to"], route["to"])
    title = p.t("route_title", start=start, end=end)
    price = p.euro(route["price"])
    facts = [p.t("route_trip", days=e(p.t("days", count=nights(route))), stops=e(p.stops(route)))]
    here, there = p.geo.get(origin["code"]), p.geo.get(route["to"])
    if here and there:
        km = distance_km(here, there)
        if km >= 150:
            facts.append(p.t("route_dist", km=f"{round(km, -1):,.0f}".replace(",", " "), hours=max(1, round(km / 800 + 0.5))))
        diff = time_difference(here, there, route["depart"])
        if diff:
            facts.append(p.t("route_tz", start=e(start), diff=f"{diff:+g}"))
    reverse = next((o for o in origins if o["code"] == route["to"]), None)
    back = next((r for r in reverse["pages"] if r["to"] == origin["code"]), None) if reverse else None
    if back:
        facts.append(f'<a href="{p.root}{route_path(reverse, back)}">{p.t("route_back", end=e(end), start=e(start), price=p.euro(back["price"]))}</a>')
    facts.append(f'<a href="{p.root}vers/{route["to_slug"]}/">{e(p.t("route_to", end=end))}</a>')
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
  <section class="panel"><h2>{e(p.t('stay_title', city=end))}</h2><p class="sub">{p.t('stay_lead')}</p><div class="stays">{stay_links(p, end, route['to'])}</div></section>
  {others_block}
  {more_block}
</section>"""
    return layout(p, f"{title} | {p.site['name']}", p.t("route_meta", start=start, end=end, price=price), route_path(origin, route), body,
                  extra=breadcrumbs(p, [(p.t("nav_world"), "depuis/"), (start, f"depuis/{origin['slug']}/"), (title, route_path(origin, route))]),
                  photo=next((code for code in (route["to"], origin["code"]) if photo_exists(code)), ""))



STAY_ICONS = {
    "hotel": '<path d="M3 18V6m0 8h18v4m0-4v-1a3 3 0 0 0-3-3h-7v4M7.5 11.5h.01"/>',
    "tour": '<path d="M4 8h16v3a2 2 0 0 0 0 3v3H4v-3a2 2 0 0 0 0-3zM14 8v9"/>',
    "car": '<path d="M4 16v-3l2-5h12l2 5v3zM4 13h16M7 16v2M17 16v2"/>',
    "esim": '<path d="M7 3h7l4 4v14H7zM10 12h5v5h-5z"/>',
    "transfer": '<path d="M4 17V7a2 2 0 0 1 2-2h12a2 2 0 0 1 2 2v10zM4 12h16M8 17v2M16 17v2"/>',
    "claim": '<path d="M12 4 3 20h18zM12 10v4M12 17h.01"/>',
}


def klook_hotels_url(p, code=""):
    """Hôtels Klook de la ville si on connaît son numéro Klook, sinon la page hôtels de Klook."""
    lang = KLOOK_LANG.get(p.lang, "en-US")
    value = str(klook_cities().get(code, ""))
    if not value:
        return f"https://www.klook.com/{lang}/hotels/"
    if value[0] in "pd":
        params = {"city_id": "", "stype": "province" if value[0] == "p" else "district", "svalue": value[1:]}
    else:
        params = {"city_id": value, "stype": "city", "svalue": value}
    params.update(adult_num=2, child_num=0, room_num=1)
    return f"https://www.klook.com/{lang}/hotels/searchresult/?{urllib.parse.urlencode(params)}"


def stay_items(p, name, code=""):
    """Liens partenaires, suivis dès que le programme est renseigné dans config.toml."""
    query = urllib.parse.quote(name)
    hotel = klook_hotels_url(p, code)
    code = p.lang if p.lang in PARTNER_LANGS else "en"
    tour = f"https://www.tiqets.com/{code}/search?q={query}"

    def tracked(url, kind):
        program = p.site.get(f"{kind}_program")
        if not program:
            return url
        return radar.partner_link(url, {**p.site, "program": program, "campaign": p.site[f"{kind}_campaign"]})

    claim = f"https://www.airhelp.com/{code}/"
    esim = "https://www.airalo.com/" + ("" if code == "en" else code)
    transfer = f"https://kiwitaxi.com/{code}"
    car = f"https://localrent.com/{code}/"
    return [(tracked(hotel, "hotels"), p.t("stay_hotel"), p.t("stay_hotel_b"), "hotel"),
            (tracked(tour, "tours"), p.t("stay_tour"), p.t("stay_tour_b"), "tour"),
            (tracked(car, "cars"), p.t("stay_car"), p.t("stay_car_b"), "car"),
            (tracked(esim, "esim"), p.t("stay_esim"), p.t("stay_esim_b"), "esim"),
            (tracked(transfer, "transfers"), p.t("stay_transfer"), p.t("stay_transfer_b"), "transfer"),
            (tracked(claim, "claims"), p.t("stay_claim"), p.t("stay_claim_b"), "claim")]


def stay_links(p, name, code=""):
    return "".join(
        f'<a class="stay" href="{e(url)}" rel="nofollow sponsored noopener" target="_blank">'
        f'<svg class="stay-icon" viewBox="0 0 24 24" aria-hidden="true">{STAY_ICONS[icon]}</svg><strong>{title}</strong><span>{text}</span></a>'
        for url, title, text, icon in stay_items(p, name, code)
    )


# « Les incontournables » : barre dépliable sur les pages destinations (activités Klook, chargées au clic),
# avec une photo différente de celle du haut de la page (jamais deux fois la même photo sur une page).
MUSTS_WORDS = {
    "fr": ("À faire sur place", "Les incontournables à {city}", "Visites, musées, spectacles : les activités préférées des voyageurs",
           "Découvrir", "Masquer", "Toutes les activités à {city}", "Billets musées et monuments"),
    "en": ("Things to do", "Top things to do in {city}", "Tours, museums, shows: travellers' favourite activities",
           "Discover", "Hide", "All activities in {city}", "Museum and landmark tickets"),
    "es": ("Qué hacer", "Imprescindibles en {city}", "Visitas, museos, espectáculos: las actividades favoritas de los viajeros",
           "Descubrir", "Ocultar", "Todas las actividades en {city}", "Entradas a museos y monumentos"),
    "de": ("Vor Ort erleben", "Highlights in {city}", "Touren, Museen, Shows: die Lieblingsaktivitäten der Reisenden",
           "Entdecken", "Ausblenden", "Alle Aktivitäten in {city}", "Tickets für Museen und Sehenswürdigkeiten"),
    "it": ("Cosa fare", "Da non perdere a {city}", "Visite, musei, spettacoli: le attività preferite dai viaggiatori",
           "Scopri", "Nascondi", "Tutte le attività a {city}", "Biglietti per musei e monumenti"),
    "pt": ("O que fazer", "Imperdíveis em {city}", "Passeios, museus, shows: as atividades favoritas dos viajantes",
           "Descobrir", "Ocultar", "Todas as atividades em {city}", "Ingressos para museus e monumentos"),
    "nl": ("Te doen", "Must-sees in {city}", "Tours, musea, shows: de favoriete activiteiten van reizigers",
           "Ontdekken", "Verbergen", "Alle activiteiten in {city}", "Tickets voor musea en monumenten"),
    "tr": ("Yapılacaklar", "{city} şehrinde mutlaka yapılacaklar", "Turlar, müzeler, gösteriler: gezginlerin favori aktiviteleri",
           "Keşfet", "Gizle", "{city} şehrindeki tüm aktiviteler", "Müze ve anıt biletleri"),
    "ar": ("ماذا تفعل هناك", "أبرز ما في {city}", "جولات ومتاحف وعروض: الأنشطة المفضلة لدى المسافرين",
           "اكتشف", "إخفاء", "كل الأنشطة في {city}", "تذاكر المتاحف والمعالم"),
    "zh": ("当地玩乐", "{city}必玩", "游览、博物馆、演出：旅行者最爱的活动", "查看", "收起", "{city}全部活动", "博物馆和景点门票"),
    "ko": ("현지 즐길 거리", "{city} 필수 코스", "투어, 박물관, 공연: 여행자들이 사랑하는 액티비티", "보기", "접기", "{city}의 모든 액티비티", "박물관·명소 입장권"),
}
# Photos choisies à la main quand celle d'Omio montre le même monument que la photo du haut
MUSTS_PHOTOS = {"PAR": "assets/photos/extra/PAR-arc.jpg"}
_MUSTS_OMIO = None


def musts_omio_photos():
    """Photos des destinations fournies par Omio (catalogue du jour), par nom de ville en minuscules."""
    global _MUSTS_OMIO
    if _MUSTS_OMIO is None:
        _MUSTS_OMIO = {}
        for lang in ("fr", "en"):
            path = DOCS / "omio" / f"{lang}.json"
            if not path.exists():
                continue
            try:
                data = json.loads(path.read_text())
            except ValueError:
                continue
            for city in data.get("cities", []):
                if len(city) > 2 and city[2]:
                    _MUSTS_OMIO.setdefault(city[1].lower(), data.get("images", "") + city[2])
    return _MUSTS_OMIO


def musts_credits():
    """Crédits des 2es photos (Wikimedia Commons), dans docs/assets/photos/extra/credits.json."""
    path = DOCS / "assets" / "photos" / "extra" / "credits.json"
    return json.loads(path.read_text()) if path.exists() else {}


def musts_photo(p, code, name):
    if code in MUSTS_PHOTOS and (DOCS / MUSTS_PHOTOS[code]).exists():
        return p.base + MUSTS_PHOTOS[code]
    if (DOCS / "assets" / "photos" / "extra" / f"{code}-must.jpg").exists():
        return f"{p.base}assets/photos/extra/{code}-must.jpg"
    photos = musts_omio_photos()
    for label in (name, FR_NAMES.get(code, "")):
        if label and label.lower() in photos:
            return photos[label.lower()]
    return ""


FR_NAMES = {}


TIQETS_LANGS = {"fr", "en", "es", "de", "it", "pt", "nl"}
KLOOK_ATTRACTIONS = {"SGN", "DEL", "BOM", "CNX", "DAD"}  # villes Klook dont la catégorie « attractions » est remplie
KLOOK_SKIP = {"YQB"}  # Klook n'a que des activités de Montréal pour ce numéro de ville
# Affiché derrière le widget : visible seulement si un bloqueur de pub l'empêche de s'afficher
MUSTS_EMPTY = {
    "fr": "Les activités ne s'affichent pas ? Ton bloqueur de pub les masque peut-être : utilise les boutons ci-dessous.",
    "en": "Activities not showing? Your ad blocker may be hiding them: use the buttons below.",
    "es": "¿No ves las actividades? Puede que tu bloqueador de anuncios las oculte: usa los botones de abajo.",
    "de": "Keine Aktivitäten zu sehen? Vielleicht blendet dein Werbeblocker sie aus: nutze die Buttons unten.",
    "it": "Non vedi le attività? Forse il tuo blocco pubblicità le nasconde: usa i pulsanti qui sotto.",
    "pt": "Não vê as atividades? Talvez o seu bloqueador de anúncios as esconda: use os botões abaixo.",
    "nl": "Zie je geen activiteiten? Misschien verbergt je adblocker ze: gebruik de knoppen hieronder.",
    "tr": "Etkinlikler görünmüyor mu? Reklam engelleyicin gizliyor olabilir: aşağıdaki düğmeleri kullan.",
    "ar": "لا تظهر الأنشطة؟ ربما يخفيها مانع الإعلانات: استخدم الأزرار أدناه.",
    "zh": "看不到活动？可能被广告拦截器隐藏了：请使用下方按钮。",
    "ko": "액티비티가 보이지 않나요? 광고 차단기가 숨겼을 수 있어요. 아래 버튼을 이용하세요.",
}
_TIQETS = None


def tiqets_cities():
    """Numéros de ville Tiqets (fichier officiel relié aux codes du site), voir tiqets_cities.json."""
    global _TIQETS
    if _TIQETS is None:
        path = ROOT / "tiqets_cities.json"
        _TIQETS = {c: v for c, v in json.loads(path.read_text()).items() if not c.startswith("_")} if path.exists() else {}
    return _TIQETS


def musts_block(p, code, name):
    """Barre « Les incontournables » (fermée par défaut) : activités Tiqets dans la langue du site quand la ville
    est chez Tiqets, sinon activités Klook ; rien si aucun des deux ne connaît la ville."""
    klook = "" if code in KLOOK_SKIP else str(klook_cities().get(code, ""))
    tiqets = tiqets_cities().get(code)
    if not tiqets and not klook.isdigit():
        return ""
    w = MUSTS_WORDS.get(p.lang, MUSTS_WORDS["en"])
    if tiqets:
        language = p.lang if p.lang in TIQETS_LANGS else "en"
        widget = (f"https://tpembd.com/content?currency=EUR&trs=597805&shmarker=800338&language={language}&locale={tiqets}"
                  f"&layout=horizontal&cards=4&powered_by=false&campaign_id=89&promo_id=3947")
        kind = "tiqets"
    else:
        # Klook : catégorie 1 (attractions) vide pour la plupart des villes, catégorie 2 (visites) sinon (testé le 10/11/2026)
        category = 1 if code in KLOOK_ATTRACTIONS else 2
        widget = (f"https://tpembd.com/content?currency=EUR&trs=597805&shmarker=800338&locale=en&city_id={klook}"
                  f"&category={category}&amount=3&powered_by=false&campaign_id=137&promo_id=4497")
        kind = "klook"
    lang = KLOOK_LANG.get(p.lang, "en-US")
    all_url = radar.partner_link(f"https://www.klook.com/{lang}/search/result/?query={urllib.parse.quote(name)}",
                                 {**p.site, "program": p.site.get("hotels_program"), "campaign": p.site.get("hotels_campaign")}) \
        if p.site.get("hotels_program") else f"https://www.klook.com/{lang}/search/result/?query={urllib.parse.quote(name)}"
    tiqets_url = stay_items(p, name, code)[1][0]
    photo = musts_photo(p, code, name)
    image = f'<img class="musts-bg" src="{e(photo)}" alt="" loading="lazy">' if photo else ""
    chev = ('<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" '
            'stroke-linejoin="round" aria-hidden="true"><path d="m6 9 6 6 6-6"/></svg>')
    return f"""<details class="musts-fold{'' if photo else ' no-photo'}">
    <summary>{image}
      <span><span class="musts-eyebrow">★ {e(w[0])}</span>
        <span class="musts-title">{e(w[1].format(city=name))}</span>
        <span class="musts-sub">{e(w[2])}</span></span>
      <span class="musts-cta"><span class="when-closed">{e(w[3])}</span><span class="when-open">{e(w[4])}</span>{chev}</span></summary>
    <div class="musts-body"><div class="musts-widget {kind}" data-src="{e(widget)}" data-empty="{e(MUSTS_EMPTY.get(p.lang, MUSTS_EMPTY['en']))}"></div>
      <p class="musts-links"><a class="musts-all" href="{e(all_url)}" target="_blank" rel="nofollow sponsored noopener">{e(w[5].format(city=name))} ↗</a>
      <a class="musts-alt" href="{e(tiqets_url)}" target="_blank" rel="nofollow sponsored noopener">{e(w[6])} ↗</a></p></div>
  </details>"""


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
  {musts_block(p, city['code'], p.city(city['code'], city['city']))}
  <section class="panel"><h2>{p.t('best_month')}</h2>
    <div class="scroll"><table><thead><tr><th scope="col">{p.t('t_month')}</th><th scope="col">{p.t('t_dates')}</th><th scope="col">{p.t('t_stops')}</th><th scope="col" class="num">{p.t('t_price')}</th><th scope="col"><span class="sr">{p.t('t_link')}</span></th></tr></thead><tbody>{rows}</tbody></table></div>
  </section>
  {guide_block(p, city, months)}
  <section class="panel"><h2>{e(p.t('stay_title', city=p.city(city['code'], city['city'])))}</h2><p class="sub">{p.t('stay_lead')}</p><div class="stays">{stay_links(p, p.city(city['code'], city['city']), city['code'])}</div></section>
  {chart}
  {related_block}
</section>"""
    title = f"{p.t('dest_title', city=p.city(city['code'], city['city']))} | {p.site['name']}"
    return layout(p, title, p.t("dest_meta", city=p.city(city["code"], city["city"])), f"destinations/{city['slug']}/", body)


CUSTOM_PATH = "voyage-sur-mesure/"
CUSTOM_VIDEOS = "sm-lagon,sm-route,sm-dunes,sm-mer"
CUSTOM_STEPS = [
    ("Ton envie", "Destination, dates, budget et ce que tu aimes, en 3 minutes."),
    ("Ton prix", "Une réponse sous 24 h, avec le prix et le contenu de ton plan."),
    ("Ton plan", "Programme jour par jour, vols, quartiers, activités et budget, livré en 3 jours."),
    ("Ta réservation", "Tu réserves toi-même, au prix affiché par les sites. Une retouche est incluse."),
]
CUSTOM_GIVES = [
    "Un programme jour par jour, du matin au soir",
    "Le meilleur moment pour partir, d'après les prix relevés par Eunodia",
    "Les vols à surveiller, avec le lien pour réserver",
    "Le quartier où dormir et des hôtels adaptés à ton budget",
    "Les activités à réserver, et celles à éviter",
    "Comment te déplacer sur place, et quelle eSIM prendre",
    "Un budget total estimé, poste par poste",
    "Une retouche incluse si tu veux changer quelque chose",
]
CUSTOM_PRICES = [("Jusqu'à 7 jours", "60 €"), ("8 à 14 jours", "95 €"), ("Plus long ou plusieurs pays", "Sur devis")]
CUSTOM_TASTES = ["Plage", "Culture", "Nature", "Gastronomie", "Fête", "Aventure", "Détente", "Petit budget"]


def custom_block(p):
    """Encart de l'accueil pour le voyage sur mesure, en français seulement."""
    if p.lang != "fr":
        return ""
    photo = "LIS" if photo_exists("LIS") else ""
    image = f'<img class="hero-img" {photo_set(p, photo, "100vw")} alt="" loading="lazy">' if photo else ""
    steps = "".join(f'<div class="stay"><strong>{e(t)}</strong><span>{e(d)}</span></div>' for t, d in CUSTOM_STEPS)
    return f"""<section class="trip custom" id="sur-mesure" data-videos="{p.base}assets/video/" data-names="{CUSTOM_VIDEOS}">
  {image}
  <div class="trip-in wrap">
    <p class="kicker">Nouveau · voyage sur mesure</p>
    <h2>Je prépare ton voyage pour toi.</h2>
    <p>Tu me dis ce que tu aimes, je te livre un plan complet, jour par jour. Dès 60 €.</p>
    <div class="stays custom-steps">{steps}</div>
    <p><a class="go big" href="{p.root}{CUSTOM_PATH}">Demander mon voyage</a></p>
  </div>
</section>"""


def custom_page(p):
    """Page du service de préparation de voyage (conseil seulement : le client réserve lui-même)."""
    steps = "".join(f'<li><strong>{e(t)}</strong><span>{e(d)}</span></li>' for t, d in CUSTOM_STEPS)
    gives = "".join(f"<li>{e(g)}</li>" for g in CUSTOM_GIVES)
    prices = "".join(f'<li><span>{e(a)}</span><strong>{e(b)}</strong></li>' for a, b in CUSTOM_PRICES)
    tastes = "".join(f'<label class="chip"><input type="checkbox" name="envies" value="{e(t)}"> {e(t)}</label>' for t in CUSTOM_TASTES)
    body = f"""<section class="page wrap">
  <h1>Ton voyage sur mesure</h1>
  <p class="lead">Tu dis ce que tu aimes, tu reçois un plan complet, jour par jour. Tu réserves ensuite toi-même, au prix affiché par les sites.</p>
  <a class="go" href="#demande">Demander mon voyage</a>
  <section class="panel"><h2>Comment ça marche</h2><ol class="custom-flow">{steps}</ol></section>
  <section class="panel custom-two">
    <div><h2>Ce que tu reçois</h2><ul class="custom-gives">{gives}</ul></div>
    <div><h2>Prix</h2><ul class="custom-prices">{prices}</ul>
      <p class="sub">Tu paies seulement après avoir validé le prix, par virement. Tes vols, hôtels et activités, tu les paies directement aux sites, sans frais en plus.</p></div>
  </section>
  <section class="panel" id="demande"><h2>Ta demande</h2>
    <form class="custom-form" id="custom-form" data-to="contact@eunodia.com" data-endpoint="https://formsubmit.co/ajax/contact@eunodia.com">
      <input class="hp" type="text" name="_honey" tabindex="-1" autocomplete="off" aria-hidden="true">
      <div class="custom-grid">
        <label>Prénom<input id="c-name" name="prenom" autocomplete="given-name" required></label>
        <label>E-mail<input id="c-email" name="email" type="email" autocomplete="email" required></label>
        <label>Où veux-tu aller ?<input id="c-where" name="destination" placeholder="Japon, Mexique… ou « je ne sais pas »" required></label>
        <label>Ville de départ<input id="c-from" name="depart" placeholder="Paris"></label>
        <label>Quand ?<input id="c-when" name="dates" placeholder="Avril 2027, 10 jours" required></label>
        <label>Combien de voyageurs ?<select id="c-pax" name="voyageurs"><option>1</option><option selected>2</option><option>3</option><option>4</option><option>5 ou plus</option></select></label>
        <label>Budget total, vols compris<select id="c-budget" name="budget"><option>Moins de 1 000 €</option><option selected>1 000 à 2 000 €</option><option>2 000 à 4 000 €</option><option>Plus de 4 000 €</option></select></label>
      </div>
      <fieldset class="chips"><legend>Ce que tu aimes</legend>{tastes}</fieldset>
      <label>Ton voyage idéal<textarea id="c-more" name="message" rows="4" placeholder="Rythme, envies, ce que tu veux éviter…"></textarea></label>
      <button class="go big" type="submit">Envoyer ma demande</button>
      <p class="custom-done" id="custom-done" role="status" hidden>Merci, ta demande est bien envoyée ! Je te réponds par e-mail sous 48 h.</p>
      <p class="custom-done" id="custom-fail" role="alert" hidden>L'envoi n'a pas marché. <a href="mailto:contact@eunodia.com">Envoie ta demande par e-mail</a> ou écris à <strong>contact@eunodia.com</strong>.</p>
    </form>
  </section>
  <p class="sub custom-legal">Eunodia propose un service de conseil et de préparation de voyage. Les réservations et paiements des vols, hébergements et activités sont faits par le voyageur, directement auprès des prestataires. Certains liens sont partenaires : Eunodia peut toucher une commission, sans frais pour toi.</p>
</section>"""
    return layout(p, f"Voyage sur mesure | {p.site['name']}",
                  "Un voyage préparé selon tes envies : programme jour par jour, vols, quartiers, activités et budget. Dès 60 €.",
                  CUSTOM_PATH, body, photo="LIS" if photo_exists("LIS") else None)


WHO_PATH = "qui-suis-je/"
WHO = {
    "fr": {"nav": "Qui suis-je ?", "title": "Qui suis-je ?",
           "lead": "Bonjour, moi c'est José Luis Cardozo Pintos, Parisien et fondateur d'Eunodia.",
           "meta": "José Luis Cardozo Pintos, Parisien, diplômé en tourisme et hôtellerie, fondateur d'Eunodia : pourquoi j'ai créé le site.",
           "alt": "José Luis Cardozo Pintos, fondateur d'Eunodia", "job": "Fondateur d'Eunodia",
           "paras": [
               "Le voyage, c'est ma passion. J'ai fait mes études dans le tourisme, jusqu'au master en gestion des activités touristiques et hôtelières à l'IREST, Sorbonne Paris 1. Je parle français, anglais et espagnol, et j'ai des notions d'italien.",
               "Durant mes études en alternance, j'ai découvert les coulisses du voyage : réserver des hébergements pour de grands événements internationaux, organiser des séjours de groupe, reloger des voyageurs à la dernière minute, échanger chaque jour avec des hôtels et des agences de voyage du monde entier. J'y ai appris comment se construisent les prix… et où se cachent les bonnes affaires.",
               "**Pourquoi Eunodia ?** Au départ, je voulais simplement créer un petit outil qui affiche les meilleurs prix de vols. Puis je me suis dit que ce serait vraiment fou de construire un vrai site, pour partager avec tout le monde les bons plans du moment : vols, hôtels, activités. Eunodia est né comme ça.",
               "Ce qui me passionne le plus, c'est de **préparer des voyages sur mesure** : imaginer l'itinéraire, trouver le bon vol et le bon hôtel au bon prix… et voir quelqu'un partir heureux. Parce qu'un voyage réussi, c'est du bonheur, et c'est pour ça que je fais ce métier.",
               "Eunodia est un projet indépendant : **je suis auto-entrepreneur** et je m'occupe du site moi-même. Il est gratuit pour toi : il se rémunère grâce à de petites commissions versées par nos partenaires quand tu réserves, sans aucun frais en plus pour toi.",
           ],
           "contact": "Une question, une envie de voyage ? Écris-moi à {mail} ou retrouve-moi sur Instagram et TikTok {handle}.",
           "go": "Préparer ton voyage avec moi"},
    "en": {"nav": "About me", "title": "About me",
           "lead": "Hi, I'm José Luis Cardozo Pintos, a Parisian and the founder of Eunodia.",
           "meta": "José Luis Cardozo Pintos, from Paris, graduate in tourism and hospitality, founder of Eunodia: why I created the site.",
           "alt": "José Luis Cardozo Pintos, founder of Eunodia", "job": "Founder of Eunodia",
           "paras": [
               "Travel is my passion. I studied tourism up to a master's degree in tourism and hotel management at IREST, Sorbonne Paris 1. I speak French, English and Spanish, plus some Italian.",
               "During my work-study years, I discovered what happens behind the scenes of travel: booking accommodation for major international events, organising group trips, rehousing travellers at the last minute, and working every day with hotels and online travel agencies around the world. That's where I learned how prices are built… and where the real deals hide.",
               "**Why Eunodia?** At first, I just wanted to build a small tool showing the best flight prices. Then I thought it would be amazing to build a real website and share the best deals of the moment with everyone: flights, hotels, activities. That's how Eunodia was born.",
               "What I love most is **planning tailor-made trips**: designing the itinerary, finding the right flight and hotel at the right price… and seeing someone leave happy. A great trip brings happiness, and that's why I do this.",
               "Eunodia is an independent project: **I'm self-employed** and I run the site myself. It's free for you: it earns small commissions from our partners when you book, at no extra cost to you.",
           ],
           "contact": "A question, a trip in mind? Write to me at {mail} or find me on Instagram and TikTok {handle}.",
           "go": "Plan my trip with José Luis"},
    "es": {"nav": "Quién soy", "title": "¿Quién soy?",
           "lead": "Hola, soy José Luis Cardozo Pintos, parisino y fundador de Eunodia.",
           "meta": "José Luis Cardozo Pintos, de París, titulado en turismo y hostelería, fundador de Eunodia: por qué creé el sitio.",
           "alt": "José Luis Cardozo Pintos, fundador de Eunodia", "job": "Fundador de Eunodia",
           "paras": [
               "Viajar es mi pasión. Estudié turismo hasta el máster en gestión de actividades turísticas y hoteleras en el IREST, Sorbona París 1. Hablo francés, inglés y español, y tengo nociones de italiano.",
               "Durante mis estudios en alternancia, descubrí los entresijos del mundo del viaje: reservando alojamientos para grandes eventos internacionales, organizando viajes de grupo, recolocando viajeros a última hora y trabajando a diario con hoteles y agencias de viajes en línea de todo el mundo. Ahí aprendí cómo se forman los precios… y dónde se esconden las gangas.",
               "**¿Por qué Eunodia?** Al principio solo quería crear una pequeña herramienta con los mejores precios de vuelos. Luego pensé que sería increíble construir un sitio de verdad para compartir con todo el mundo las mejores ofertas del momento: vuelos, hoteles, actividades. Así nació Eunodia.",
               "Lo que más me apasiona es **preparar viajes a medida**: imaginar el itinerario, encontrar el vuelo y el hotel adecuados al mejor precio… y ver a alguien irse feliz. Un buen viaje da felicidad, y por eso hago este trabajo.",
               "Eunodia es un proyecto independiente: **soy autónomo** y gestiono el sitio yo mismo. Es gratis para ti: se financia con pequeñas comisiones de nuestros socios cuando reservas, sin ningún coste extra para ti.",
           ],
           "contact": "¿Una pregunta o un viaje en mente? Escríbeme a {mail} o encuéntrame en Instagram y TikTok {handle}.",
           "go": "Preparar mi viaje con José Luis"},
}

WHO.update({
    "de": {"nav": "Über mich", "title": "Über mich",
           "lead": "Hallo, ich bin José Luis Cardozo Pintos, Pariser und Gründer von Eunodia.",
           "meta": "José Luis Cardozo Pintos aus Paris, Tourismus-Absolvent und Gründer von Eunodia: warum ich die Seite gegründet habe.",
           "alt": "José Luis Cardozo Pintos, Gründer von Eunodia", "job": "Gründer von Eunodia",
           "paras": [
               "Reisen ist meine Leidenschaft. Ich habe Tourismus studiert, bis zum Master in Tourismus- und Hotelmanagement am IREST der Sorbonne Paris 1. Ich spreche Französisch, Englisch und Spanisch und habe Grundkenntnisse in Italienisch.",
               "Während meines dualen Studiums habe ich hinter die Kulissen des Reisens geblickt: Unterkünfte für große internationale Events buchen, Gruppenreisen organisieren, Reisende in letzter Minute umbuchen und täglich mit Hotels und Online-Reisebüros auf der ganzen Welt zusammenarbeiten. Dort habe ich gelernt, wie Preise entstehen … und wo sich die echten Schnäppchen verstecken.",
               "**Warum Eunodia?** Anfangs wollte ich nur ein kleines Tool bauen, das die besten Flugpreise anzeigt. Dann dachte ich mir, es wäre großartig, eine richtige Website zu bauen und die besten Angebote des Moments mit allen zu teilen: Flüge, Hotels, Aktivitäten. So ist Eunodia entstanden.",
               "Am meisten begeistert es mich, **maßgeschneiderte Reisen zu planen**: die Route entwerfen, den richtigen Flug und das richtige Hotel zum richtigen Preis finden … und jemanden glücklich abreisen sehen. Eine gelungene Reise macht glücklich, und genau deshalb mache ich diese Arbeit.",
               "Eunodia ist ein unabhängiges Projekt: **Ich bin selbstständig** und betreibe die Website selbst. Für dich ist sie kostenlos: Sie finanziert sich über kleine Provisionen unserer Partner, wenn du buchst, ohne Mehrkosten für dich.",
           ],
           "contact": "Eine Frage oder eine Reiseidee? Schreib mir an {mail} oder finde mich auf Instagram und TikTok {handle}.",
           "go": "Meine Reise mit José Luis planen"},
    "it": {"nav": "Chi sono", "title": "Chi sono",
           "lead": "Ciao, sono José Luis Cardozo Pintos, parigino e fondatore di Eunodia.",
           "meta": "José Luis Cardozo Pintos, di Parigi, laureato in turismo e fondatore di Eunodia: perché ho creato il sito.",
           "alt": "José Luis Cardozo Pintos, fondatore di Eunodia", "job": "Fondatore di Eunodia",
           "paras": [
               "Viaggiare è la mia passione. Ho studiato turismo fino al master in gestione delle attività turistiche e alberghiere all'IREST, Sorbona Parigi 1. Parlo francese, inglese e spagnolo, e ho qualche nozione di italiano.",
               "Durante i miei studi in alternanza scuola-lavoro ho scoperto il dietro le quinte dei viaggi: prenotare alloggi per grandi eventi internazionali, organizzare viaggi di gruppo, ricollocare viaggiatori all'ultimo minuto e lavorare ogni giorno con hotel e agenzie di viaggio online di tutto il mondo. Lì ho imparato come si formano i prezzi… e dove si nascondono i veri affari.",
               "**Perché Eunodia?** All'inizio volevo solo creare un piccolo strumento che mostrasse i migliori prezzi dei voli. Poi ho pensato che sarebbe stato fantastico costruire un vero sito per condividere con tutti le migliori offerte del momento: voli, hotel, attività. Così è nata Eunodia.",
               "Ciò che mi appassiona di più è **organizzare viaggi su misura**: immaginare l'itinerario, trovare il volo e l'hotel giusti al prezzo giusto… e vedere qualcuno partire felice. Un viaggio riuscito regala felicità, ed è per questo che faccio questo lavoro.",
               "Eunodia è un progetto indipendente: **sono un lavoratore autonomo** e gestisco il sito da solo. Per te è gratuito: si sostiene con piccole commissioni dei nostri partner quando prenoti, senza alcun costo aggiuntivo per te.",
           ],
           "contact": "Una domanda, un viaggio in mente? Scrivimi a {mail} o trovami su Instagram e TikTok {handle}.",
           "go": "Organizza il mio viaggio con José Luis"},
    "pt": {"nav": "Quem sou eu", "title": "Quem sou eu?",
           "lead": "Olá, eu sou José Luis Cardozo Pintos, parisiense e fundador da Eunodia.",
           "meta": "José Luis Cardozo Pintos, de Paris, formado em turismo e fundador da Eunodia: por que criei o site.",
           "alt": "José Luis Cardozo Pintos, fundador da Eunodia", "job": "Fundador da Eunodia",
           "paras": [
               "Viajar é a minha paixão. Estudei turismo até o mestrado em gestão de atividades turísticas e hoteleiras no IREST, Sorbonne Paris 1. Falo francês, inglês e espanhol, e tenho noções de italiano.",
               "Durante meus estudos em regime de alternância, descobri os bastidores das viagens: reservar hospedagens para grandes eventos internacionais, organizar viagens em grupo, realocar viajantes de última hora e trabalhar todos os dias com hotéis e agências de viagem online do mundo inteiro. Foi ali que aprendi como os preços são formados… e onde se escondem as boas ofertas.",
               "**Por que a Eunodia?** No começo, eu só queria criar uma pequena ferramenta que mostrasse os melhores preços de voos. Depois pensei que seria incrível construir um site de verdade para compartilhar com todo mundo as melhores ofertas do momento: voos, hotéis, atividades. Foi assim que a Eunodia nasceu.",
               "O que mais me apaixona é **preparar viagens sob medida**: imaginar o roteiro, encontrar o voo e o hotel certos pelo preço certo… e ver alguém partir feliz. Uma viagem bem-sucedida traz felicidade, e é por isso que faço este trabalho.",
               "A Eunodia é um projeto independente: **sou trabalhador autônomo** e cuido do site sozinho. Para você, é gratuito: o site é remunerado por pequenas comissões dos nossos parceiros quando você reserva, sem nenhum custo extra para você.",
           ],
           "contact": "Uma pergunta, uma vontade de viajar? Escreva para {mail} ou me encontre no Instagram e no TikTok {handle}.",
           "go": "Preparar minha viagem com José Luis"},
    "nl": {"nav": "Over mij", "title": "Over mij",
           "lead": "Hoi, ik ben José Luis Cardozo Pintos, Parijzenaar en oprichter van Eunodia.",
           "meta": "José Luis Cardozo Pintos uit Parijs, afgestudeerd in toerisme en oprichter van Eunodia: waarom ik de site heb gemaakt.",
           "alt": "José Luis Cardozo Pintos, oprichter van Eunodia", "job": "Oprichter van Eunodia",
           "paras": [
               "Reizen is mijn passie. Ik heb toerisme gestudeerd, tot en met een master in het beheer van toeristische en hotelactiviteiten aan het IREST, Sorbonne Paris 1. Ik spreek Frans, Engels en Spaans, en een beetje Italiaans.",
               "Tijdens mijn duale studie ontdekte ik wat er achter de schermen van reizen gebeurt: accommodaties boeken voor grote internationale evenementen, groepsreizen organiseren, reizigers op het laatste moment herplaatsen en elke dag samenwerken met hotels en online reisbureaus over de hele wereld. Daar leerde ik hoe prijzen tot stand komen… en waar de echte koopjes zich verstoppen.",
               "**Waarom Eunodia?** In het begin wilde ik alleen een kleine tool maken die de beste vliegprijzen toont. Toen dacht ik dat het geweldig zou zijn om een echte website te bouwen en de beste deals van het moment met iedereen te delen: vluchten, hotels, activiteiten. Zo is Eunodia ontstaan.",
               "Waar ik het meest van hou, is **reizen op maat plannen**: de route bedenken, de juiste vlucht en het juiste hotel tegen de juiste prijs vinden… en iemand blij zien vertrekken. Een geslaagde reis maakt mensen gelukkig, en daarom doe ik dit werk.",
               "Eunodia is een onafhankelijk project: **ik ben zelfstandig ondernemer** en beheer de site zelf. Voor jou is hij gratis: hij verdient kleine commissies van onze partners als je boekt, zonder extra kosten voor jou.",
           ],
           "contact": "Een vraag of een reisidee? Mail me op {mail} of vind me op Instagram en TikTok {handle}.",
           "go": "Mijn reis plannen met José Luis"},
    "tr": {"nav": "Hakkımda", "title": "Hakkımda",
           "lead": "Merhaba, ben José Luis Cardozo Pintos; Parisliyim ve Eunodia'nın kurucusuyum.",
           "meta": "Parisli, turizm mezunu ve Eunodia'nın kurucusu José Luis Cardozo Pintos: siteyi neden kurdum.",
           "alt": "Eunodia'nın kurucusu José Luis Cardozo Pintos", "job": "Eunodia'nın kurucusu",
           "paras": [
               "Seyahat benim tutkum. Turizm alanında okudum ve IREST, Sorbonne Paris 1'de turizm ve otel işletmeciliği yüksek lisansını tamamladım. Fransızca, İngilizce ve İspanyolca konuşuyorum; biraz da İtalyanca biliyorum.",
               "Çalışarak okuduğum yıllarda seyahatin perde arkasını keşfettim: büyük uluslararası etkinlikler için konaklama ayırtmak, grup seyahatleri düzenlemek, yolcuları son dakikada başka otellere yerleştirmek ve her gün dünyanın dört bir yanındaki otellerle ve çevrim içi seyahat acenteleriyle çalışmak. Fiyatların nasıl oluştuğunu… ve gerçek fırsatların nerede saklandığını orada öğrendim.",
               "**Neden Eunodia?** Başta sadece en iyi uçak bileti fiyatlarını gösteren küçük bir araç yapmak istiyordum. Sonra, anın en iyi fırsatlarını herkesle paylaşan gerçek bir site kurmanın harika olacağını düşündüm: uçuşlar, oteller, aktiviteler. Eunodia böyle doğdu.",
               "Beni en çok heyecanlandıran şey **kişiye özel seyahatler hazırlamak**: rotayı tasarlamak, doğru uçuşu ve doğru oteli doğru fiyata bulmak… ve birinin mutlu bir şekilde yola çıktığını görmek. İyi bir seyahat mutluluk getirir; bu işi bu yüzden yapıyorum.",
               "Eunodia bağımsız bir projedir: **serbest çalışan bir girişimciyim** ve siteyi kendim yönetiyorum. Site sizin için ücretsizdir: rezervasyon yaptığınızda iş ortaklarımızdan küçük komisyonlar alır, size hiçbir ek maliyeti yoktur.",
           ],
           "contact": "Bir sorunuz ya da bir seyahat fikriniz mi var? Bana {mail} adresinden yazın ya da Instagram ve TikTok'ta {handle} hesabından ulaşın.",
           "go": "Seyahatimi José Luis ile planla"},
    "ar": {"nav": "من أنا", "title": "من أنا؟",
           "lead": "مرحبًا، أنا خوسيه لويس كاردوزو بينتوس، من باريس ومؤسس Eunodia.",
           "meta": "خوسيه لويس كاردوزو بينتوس من باريس، خريج السياحة ومؤسس Eunodia: لماذا أنشأت الموقع.",
           "alt": "خوسيه لويس كاردوزو بينتوس، مؤسس Eunodia", "job": "مؤسس Eunodia",
           "paras": [
               "السفر هو شغفي. درست السياحة حتى الماجستير في إدارة الأنشطة السياحية والفندقية في معهد IREST بجامعة السوربون باريس 1. أتحدث الفرنسية والإنجليزية والإسبانية، ولدي معرفة بسيطة بالإيطالية.",
               "خلال دراستي بنظام التناوب بين الدراسة والعمل، اكتشفت ما يحدث خلف كواليس السفر: حجز أماكن الإقامة لفعاليات دولية كبرى، وتنظيم الرحلات الجماعية، وإعادة إسكان المسافرين في اللحظة الأخيرة، والتعامل يوميًا مع فنادق ووكالات سفر إلكترونية من جميع أنحاء العالم. هناك تعلّمت كيف تتشكّل الأسعار… وأين تختبئ أفضل العروض.",
               "**لماذا Eunodia؟** في البداية، أردت فقط إنشاء أداة صغيرة تعرض أفضل أسعار الرحلات الجوية. ثم فكّرت أنه سيكون رائعًا بناء موقع حقيقي لمشاركة أفضل عروض اللحظة مع الجميع: رحلات جوية، فنادق، أنشطة. هكذا وُلدت Eunodia.",
               "أكثر ما يشغفني هو **تحضير رحلات مصمّمة حسب الطلب**: تخيّل خط الرحلة، وإيجاد الرحلة والفندق المناسبين بالسعر المناسب… ثم رؤية شخص ينطلق سعيدًا. الرحلة الناجحة تجلب السعادة، ولهذا أقوم بهذا العمل.",
               "Eunodia مشروع مستقل: **أعمل لحسابي الخاص** وأدير الموقع بنفسي. الموقع مجاني لك: يحصل على عمولات صغيرة من شركائنا عندما تحجز، دون أي تكلفة إضافية عليك.",
           ],
           "contact": "لديك سؤال أو فكرة رحلة؟ راسلني على {mail} أو تابعني على إنستغرام وتيك توك {handle}.",
           "go": "خطّط رحلتي مع خوسيه لويس"},
    "zh": {"nav": "关于我", "title": "关于我",
           "lead": "你好，我是 José Luis Cardozo Pintos，巴黎人，Eunodia 的创始人。",
           "meta": "来自巴黎的 José Luis Cardozo Pintos，旅游专业毕业，Eunodia 创始人：我为什么创建这个网站。",
           "alt": "Eunodia 创始人 José Luis Cardozo Pintos", "job": "Eunodia 创始人",
           "paras": [
               "旅行是我的热爱。我一直在学习旅游专业，并在巴黎第一大学（索邦）IREST 获得了旅游与酒店管理硕士学位。我会说法语、英语和西班牙语，也懂一点意大利语。",
               "在工学交替的学习期间，我了解了旅行行业的幕后：为大型国际活动预订住宿、组织团体旅行、在最后一刻为旅客重新安排酒店，并每天与世界各地的酒店和在线旅行社打交道。正是在那里，我学会了价格是如何形成的……以及真正的好价藏在哪里。",
               "**为什么创建 Eunodia？** 起初，我只是想做一个显示最低机票价格的小工具。后来我觉得，建一个真正的网站，把当下最好的优惠分享给所有人，会更有意思：机票、酒店、活动。Eunodia 就这样诞生了。",
               "我最热爱的是**定制旅行**：设计行程，以合适的价格找到合适的航班和酒店……然后看着别人开心地出发。一次成功的旅行能带来幸福，这就是我做这份工作的原因。",
               "Eunodia 是一个独立项目：**我是个体经营者**，网站由我亲自运营。网站对你免费：当你预订时，我们的合作伙伴会支付少量佣金，你无需支付任何额外费用。",
           ],
           "contact": "有问题或旅行想法？请发邮件至 {mail}，或在 Instagram 和 TikTok 上关注 {handle}。",
           "go": "和 José Luis 一起规划我的旅行"},
    "ko": {"nav": "소개", "title": "저를 소개합니다",
           "lead": "안녕하세요, 파리 출신이자 Eunodia의 창립자인 José Luis Cardozo Pintos입니다.",
           "meta": "파리 출신, 관광학 전공, Eunodia 창립자 José Luis Cardozo Pintos: 제가 이 사이트를 만든 이유.",
           "alt": "Eunodia 창립자 José Luis Cardozo Pintos", "job": "Eunodia 창립자",
           "paras": [
               "여행은 제 열정입니다. 관광학을 공부했고, 소르본 파리 1대학 IREST에서 관광·호텔 경영 석사 과정을 마쳤습니다. 프랑스어, 영어, 스페인어를 할 수 있고 이탈리아어도 조금 합니다.",
               "일과 학업을 병행하던 시절, 여행업계의 뒷무대를 경험했습니다. 대형 국제 행사를 위한 숙소 예약, 단체 여행 기획, 마지막 순간의 숙소 재배정, 그리고 전 세계 호텔 및 온라인 여행사와의 매일같은 협업까지요. 그곳에서 가격이 어떻게 정해지는지… 그리고 진짜 특가가 어디에 숨어 있는지 배웠습니다.",
               "**왜 Eunodia인가요?** 처음에는 최저 항공권 가격을 보여주는 작은 도구를 만들고 싶었을 뿐이었습니다. 그러다 지금 가장 좋은 특가를 모두와 나누는 진짜 웹사이트를 만들면 정말 멋지겠다고 생각했습니다. 항공권, 호텔, 액티비티까지요. 그렇게 Eunodia가 탄생했습니다.",
               "제가 가장 좋아하는 일은 **맞춤 여행을 준비하는 것**입니다. 일정을 짜고, 알맞은 항공편과 호텔을 알맞은 가격에 찾고… 누군가가 행복하게 떠나는 모습을 보는 것이죠. 좋은 여행은 행복을 줍니다. 그래서 저는 이 일을 합니다.",
               "Eunodia는 독립 프로젝트입니다. **저는 1인 자영업자**이며 사이트를 직접 운영합니다. 사이트는 무료입니다. 예약하시면 파트너사로부터 소정의 수수료를 받으며, 추가 비용은 전혀 없습니다.",
           ],
           "contact": "궁금한 점이나 여행 계획이 있으신가요? {mail}로 메일을 보내시거나 Instagram과 TikTok {handle}에서 만나보세요.",
           "go": "José Luis와 여행 계획하기"},
})


def who_page(p):
    """Page « Qui suis-je ? » : le fondateur, son parcours et pourquoi Eunodia existe."""
    w = WHO.get(p.lang, WHO["en"])
    bold = lambda text: re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", e(text))
    handle = f"@{p.site['instagram']}" if p.site.get("instagram") else ""
    links = social_profiles(p.site)
    social = " / ".join(f'<a href="{e(url)}" rel="me noopener" target="_blank">{name}</a>' for name, url, _ in links)
    contact = e(w["contact"]).replace("{mail}", '<a href="mailto:contact@eunodia.com">contact@eunodia.com</a>').replace("{handle}", f"{e(handle)} ({social})" if social else "")
    paras = "".join(f"<p>{bold(t)}</p>" for t in w["paras"])
    photo = f"{p.base}assets/jose-luis.jpg"
    person = schema_tag({"@context": "https://schema.org", "@type": "Person", "name": "José Luis Cardozo Pintos",
                         "jobTitle": w["job"], "image": f"{p.site['url']}assets/jose-luis.jpg", "homeLocation": "Paris",
                         "worksFor": {"@type": "Organization", "name": p.site["name"], "url": p.site["url"]},
                         "sameAs": [url for _, url, _ in links]})
    body = f"""<section class="page wrap">
  <h1>{e(w['title'])}</h1>
  <p class="lead">{e(w['lead'])}</p>
  <div class="who">
    <img class="who-photo" src="{photo}" width="800" height="1000" alt="{e(w['alt'])}">
    <div class="who-text">
      {paras}
      <p class="who-contact">{contact}</p>
      <a class="search-go" href="{p.site['root']}{CUSTOM_PATH}">{e(w['go'])}</a>
    </div>
  </div>
</section>{person}"""
    return layout(p, f"{w['title']} | {p.site['name']}", w["meta"], WHO_PATH, body, photo="PAR" if photo_exists("PAR") else None)


def about_page(p):
    items = "".join(f"<details><summary>{e(q)}</summary><p>{e(a)}</p></details>" for q, a in TEXT[p.lang]["faq"])
    body = f'<section class="page wrap narrow"><h1>{p.t("info_title")}</h1><p class="lead">{p.t("info_lead")}</p><div class="faq">{items}</div><p class="info-contact"><a href="mailto:contact@eunodia.com">contact@eunodia.com</a></p><a class="search-go" href="{p.root}">{p.t("info_go")}</a></section>'
    return layout(p, f"{p.t('info_title')} | {p.site['name']}", p.t("info_meta"), "a-propos/", body, photo="BCN" if photo_exists("BCN") else None)


def credits_page(p):
    credits = load_credits()
    rows = "".join(
        f'<li><strong>{e(p.city(code, credit["city"]))}</strong><br>{photo_credit(p, credit)}</li>'
        for code, credit in sorted(credits.items(), key=lambda item: item[1]["city"]) if photo_exists(code)
    )
    rows += "".join(
        f'<li><strong>{e(p.city(code, credit["city"]))} (2)</strong><br>{photo_credit(p, credit)}</li>'
        for code, credit in sorted(musts_credits().items(), key=lambda item: item[1]["city"])
        if (DOCS / "assets" / "photos" / "extra" / f"{code}-must.jpg").exists()
    )
    video_path = DOCS / "assets" / "video" / "credit.json"
    if video_path.exists():
        video = json.loads(video_path.read_text())
        rows += "".join(
            f'<li><strong>Video</strong><br><a href="{e(item["source"])}" rel="noopener">{e(item["artist"])}</a>, '
            f'<a href="{e(item["license_url"])}" rel="noopener">{e(item["license"])}</a></li>'
            for item in video
        )
    body = f'<section class="page wrap narrow"><h1>{p.t("credits")}</h1><p class="lead">{p.t("credits_lead")}</p><ul class="credit-list">{rows}</ul></section>'
    return layout(p, f"{p.t('credits')} | {p.site['name']}", p.t("credits_lead"), "credits/", body)


def news_done_page(p):
    title, lead, first, second = NEWS_DONE[p.lang]
    body = (f'<section class="page wrap"><h1>{e(title)}</h1><p class="lead">{e(lead)}</p></section>'
            f'<section class="done-actions wrap"><a class="go" href="{p.root}vols/">{e(first)}</a>'
            f'<a class="done-link" href="{p.root}destinations/">{e(second)}</a></section>')
    return layout(p, f"{title} | {p.site['name']}", lead, "newsletter-confirmee/", body, noindex=True, photo="SYD")


def missing_page(p):
    body = f'<section class="page wrap narrow"><h1>{p.t("missing")}</h1><p class="lead">{p.t("missing_lead")}</p><a class="search-go" href="{p.root}">{p.t("back_home")}</a></section>'
    return layout(p, f"{p.t('missing')} | {p.site['name']}", p.t("missing_lead"), "404.html", body)


RESULTS_PATH = "recherche/"
WHITE_LABEL_ID = "24366"
WHITE_LABEL_CURRENCY = {"en": "usd", "ar": "usd", "ko": "usd", "zh": "usd"}


def results_page(p):
    """Résultats de recherche de vols : moteur Travelpayouts intégré au site (non indexé, comme toute page de résultats)."""
    fr = p.lang == "fr"
    currency = WHITE_LABEL_CURRENCY.get(p.lang, "eur").upper()
    title = "Trouve ton vol" if fr else "Find your flight"
    lead = ("Compare les compagnies et les agences, bagages compris. Tu réserves directement chez le vendeur, au prix affiché."
            if fr else "Compare airlines and agencies, bags included. You book directly with the seller, at the price shown.")
    perks = (("Prix bagages compris", "Choisis tes bagages : le prix affiché devient le prix final."),
             ("Achat direct", "Le bouton t'envoie chez la compagnie ou l'agence qui vend le billet."),
             ("Aucuns frais Eunodia", "Tu paies le prix du vendeur, rien de plus.")) if fr else (
             ("Bags included", "Pick your bags: the price shown becomes the final price."),
             ("Book direct", "The button takes you to the airline or agency selling the ticket."),
             ("No Eunodia fees", "You pay the seller's price, nothing more."))
    items = "".join(f"<li><strong>{e(a)}</strong><span>{e(b)}</span></li>" for a, b in perks)
    body = f"""<section class="page wrap">
  <h1>{e(title)}</h1>
  <p class="lead">{e(lead)}</p>
  <div class="wl">
    <div class="wl-card"><div id="tpwl-search"></div></div>
    <ul class="wl-perks">{items}</ul>
    <div id="tpwl-tickets"></div>
  </div>
</section>"""
    extra = f"""<script>document.cookie = "hide_hotels=true; max-age=31536000; path=/; SameSite=Lax"; ["tpwl_locale={p.lang}", "tpwl_currency={currency}"].forEach(function (c) {{ document.cookie = c + "; path=/; max-age=31536000; SameSite=Lax"; document.cookie = c + "; path=/; domain=." + location.hostname.replace(/^www\\./, "") + "; max-age=31536000; SameSite=Lax"; }});</script>
<script type="module" async src="https://tpembd.com/wl_web/main.js?wl_id={WHITE_LABEL_ID}"></script>"""
    return layout(p, f"{title} | {p.site['name']}", lead, RESULTS_PATH, body, noindex=True, extra=extra, photo="TYO" if photo_exists("TYO") else None)


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
    home_html = home(p, cities, offers, updated, origins)
    tabs, hotels = hotel_search(p, cities)  # onglets Vols / Hôtels au-dessus de la recherche
    flights = search_form(p)
    home_html = home_html.replace(flights, tabs + flights + hotels, 1)
    write(folder / "index.html", home_html)
    world = folder / "depuis"
    if world.exists():
        shutil.rmtree(world)
    if origins:
        write(world / "index.html", world_index(p, origins))
    for origin in origins:
        write(world / origin["slug"] / "index.html", origin_page(p, origin))
        for route in origin["pages"] if lang in FULL_LANGS else ():
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
    write(folder / WHO_PATH / "index.html", who_page(p))
    if lang == "fr":
        write(folder / "voyage-sur-mesure" / "index.html", custom_page(p))
    if origins:
        write(folder / "barometre" / "index.html", barometer_page(p, origins, updated))
    write(folder / "newsletter-confirmee" / "index.html", news_done_page(p))
    deals = folder / "vols-pas-chers"
    if deals.exists():
        shutil.rmtree(deals)
    by_code = {c["code"]: c for c in cities}
    write(deals / "index.html", collections_index(p, groups, origins))
    for group in groups:
        write(deals / group["slug"] / "index.html", collection_page(p, group, groups, by_code, updated))
    if lang in FULL_LANGS:
        write(folder / "test-reservation" / "index.html", test_booking_page(p))
    write(folder / RESULTS_PATH / "index.html", results_page(p))
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
    data = retrack(data, site.get("project"))
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
    names = clean_names(names)
    for lang, (places, countries) in (catalog or {}).items():
        rows = [[code, names[lang].get(code, name), *rest] for code, name, *rest in city_index(places, countries)]
        write(DOCS / "assets" / f"cities-{lang}.json", json.dumps(rows, ensure_ascii=False, separators=(",", ":")))
    if catalog:
        write(names_path, json.dumps(names, ensure_ascii=False, separators=(",", ":")))
    groups = collections(offers)
    origins = load_world(names.get("fr", {}), site.get("project"))
    zones_path = DOCS / "assets" / "zones.json"
    zones = json.loads(zones_path.read_text()) if zones_path.exists() else {}
    geo_path = DOCS / "assets" / "geo.json"
    geo = json.loads(geo_path.read_text()) if geo_path.exists() else {}
    countries_path = DOCS / "assets" / "countries.json"
    countries = json.loads(countries_path.read_text()) if countries_path.exists() else {}
    FR_NAMES.update({c["code"]: c.get("city", "") for c in cities})
    FR_NAMES.update(names.get("fr") or {})
    for lang in LANGS:
        page = Page(site, lang, names.get(lang))
        page.zones, page.countries, page.geo = zones, countries, geo
        build_language(page, data, cities, updated_at, groups, origins)
    write(DOCS / "404.html", missing_page(Page(site, "fr", names.get("fr"))))
    route_pages = [route_path(origin, route) for origin in origins for route in origin["pages"]]
    pages = ["", "vols/", "vols-pas-chers/", "destinations/", "a-propos/", WHO_PATH] + [f"destinations/{c['slug']}/" for c in cities]
    pages += [f"vols-pas-chers/{g['slug']}/" for g in groups]
    if origins:
        pages += ["depuis/", "barometre/"]
    for origin in origins:
        pages.append(f"depuis/{origin['slug']}/")
    pages += [f"vers/{place['slug']}/" for place in world_destinations(origins)]
    urls = "".join(
        f"<url><loc>{e(site['url'] + ('' if lang == 'fr' else lang + '/') + page)}</loc></url>"
        for lang in LANGS for page in pages + (route_pages if lang in FULL_LANGS else [])
    )
    urls += f"<url><loc>{e(site['url'] + CUSTOM_PATH)}</loc></url>"
    write(DOCS / "sitemap.xml", f'<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{urls}</urlset>\n')
    write(DOCS / "manifest.webmanifest", json.dumps({
        "name": site["name"], "short_name": site["name"], "start_url": site["root"], "display": "standalone",
        "background_color": "#ffffff", "theme_color": "#0b0b0b",
        "icons": [{"src": f"{site['root']}assets/icon-{size}.png", "sizes": f"{size}x{size}", "type": "image/png"} for size in (192, 512)],
    }, ensure_ascii=False))
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
    geo = {row["code"]: [row["coordinates"]["lat"], row["coordinates"]["lon"], row.get("time_zone")]
           for row in rows if (row.get("coordinates") or {}).get("lat") is not None}
    write(DOCS / "assets" / "geo.json", json.dumps(geo, separators=(",", ":")))
    catalog, country_names = {}, {}
    for lang in LANGS:
        code = DATA_LANGS.get(lang, lang)
        places = radar.load_places(code)
        rows = radar.http_json(f"{radar.TP_BASE}/data/{code}/countries.json")
        catalog[lang] = (places, {row["code"]: row.get("name") or row["code"] for row in rows})
        country_names[lang] = catalog[lang][1]
    write(DOCS / "assets" / "countries.json", json.dumps(
        {"cities": {code: place["country"] for code, place in catalog["fr"][0].items()}, "names": country_names},
        ensure_ascii=False, separators=(",", ":")))
    return catalog


MOVED_MARK = "<!-- eunodia:page-deplacee -->"
GONE_PAGES = [  # pages signalées en 404 par Google avant la mise en place des redirections
    "it/vers/st-domingue/", "de/depuis/miami/baltimore/", "nl/depuis/new-york/punta-cana/", "nl/depuis/madrid/edinbourg/",
    "nl/depuis/miami/nassau/", "nl/depuis/buenos-aires/quito/", "de/depuis/barcelone/palma-de-mallorca/",
    "ar/depuis/paris/bucarest/", "zh/depuis/dubai/makhatchkala/", "nl/depuis/dubai/makhatchkala/",
]


def built_pages():
    """Dossiers (relatifs au site) qui ont une vraie page dans cette construction."""
    pages = set()
    for path in DOCS.rglob("index.html"):
        if MOVED_MARK not in path.read_text(errors="ignore")[:400]:
            folder = path.parent.relative_to(DOCS).as_posix()
            pages.add("" if folder == "." else folder + "/")
    return pages


def moved_target(page, pages):
    """Page la plus proche encore en ligne : le dossier parent, ou les destinations pour /vers/."""
    parts = page.strip("/").split("/")
    while parts:
        parts.pop()
        if parts and parts[-1] == "vers":
            parts[-1] = "destinations"
        candidate = "/".join(parts) + "/" if parts else ""
        if candidate in pages:
            return candidate
    return ""


def keep_moved_pages(state, url="/"):
    """Une page qui disparaît (trajet sans prix, ville renommée…) redirige vers la page la plus proche au lieu d'une erreur 404."""
    pages = built_pages()
    known = set(json.loads(state.read_text())) if state.exists() else set()
    known |= set(GONE_PAGES) | pages
    moved = sorted(known - pages)
    for page in moved:
        target = e(url + moved_target(page, pages))
        write(DOCS / page / "index.html", f'<!doctype html>{MOVED_MARK}<html><head><meta charset="utf-8"><title>Eunodia</title>'
              f'<link rel="canonical" href="{target}"><meta name="robots" content="noindex">'
              f'<meta http-equiv="refresh" content="0; url={target}"></head>'
              f'<body><a href="{target}">Eunodia</a></body></html>\n')
    write(state, json.dumps(sorted(known), ensure_ascii=False, separators=(",", ":")) + "\n")
    return moved


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
    moved = keep_moved_pages(ROOT / "data" / "pages_connues.json", config["site"]["url"])
    print(f"{len(moved)} anciennes pages redirigées.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
