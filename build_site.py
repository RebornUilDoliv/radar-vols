#!/usr/bin/env python3
"""Génère le site statique multilingue d'Eunodia à partir de docs/prices.json."""
import html
import json
import re
import shutil
import sys
import tomllib
import unicodedata
import urllib.parse
from datetime import date, datetime
from pathlib import Path

import radar
from site_text import LANG_NAMES, LANGS, LOCALES, MONTHS, REGIONS, SCRIPT_TEXT, SHORT_MONTHS, TEXT

ROOT = Path(__file__).parent
DOCS = ROOT / "docs"
SOON_DAYS = 45
AHEAD_DAYS = 150
HERO_PHOTO = "TYO"
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
         "from_name": p.city("PAR", "Paris"), "to_name": p.city("NYC", "New York")},
        ensure_ascii=False, separators=(",", ":"),
    ).replace("</", "<\\/")
    version = site["version"]
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
<link rel="icon" href="{base}assets/icon.svg" type="image/svg+xml">
<link rel="stylesheet" href="{base}assets/style.css?v={version}">
<script>window.RF={script}</script>
<script src="{base}assets/app.js?v={version}" defer></script>
{extra}
</head>
<body>
<header class="nav">
  <a class="logo" href="{root}">{name}</a>
  <nav aria-label="Menu">
    <a href="{root}vols/">{p.t('nav_flights')}</a>
    <a href="{root}destinations/">{p.t('nav_places')}</a>
    <a href="{root}a-propos/">{p.t('nav_info')}</a>
    <a class="nav-test" href="{root}test-reservation/">{p.t('nav_test')}</a>
  </nav>
  <div class="langs" aria-label="Langue">{switch}</div>
</header>
<main>
{body}
</main>
<footer class="foot">
  <div class="wrap foot-in">
    <p class="foot-brand">{name}</p>
    <div>
      <p>{p.t('foot_1')}</p>
      <p>{p.t('foot_2', name=name)}</p>
    </div>
    <p class="foot-links"><a href="{root}vols/">{p.t('nav_flights')}</a><a href="{root}destinations/">{p.t('nav_places')}</a><a href="{root}a-propos/">{p.t('nav_info')}</a><a href="{root}credits/">{p.t('credits')}</a></p>
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
  <img src="{p.base}assets/photos/{city['code']}.jpg" alt="{name}" loading="lazy">
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
  <div class="field grow"><label for="from">{p.t('search_from')}</label><input id="from" value="{e(p.city('PAR', 'Paris'))} (PAR)" data-code="PAR" required>
    <ul class="suggest" hidden></ul></div>
  <div class="field grow"><label for="to">{p.t('search_to')}</label><input id="to" placeholder="{e(p.t('search_place'))}" required>
    <ul class="suggest" hidden></ul></div>
  <div class="field"><label for="out">{p.t('search_out')}</label><input id="out" type="date" required></div>
  <div class="field"><label for="back">{p.t('search_back')}</label><input id="back" type="date"></div>
  <div class="field small"><label for="pax">{p.t('search_pax')}</label><select id="pax"><option>1</option><option>2</option><option>3</option><option>4</option><option>5</option><option>6</option></select></div>
  <button class="search-go" type="submit">{p.t('search_go')}</button>
  <p class="form-error" id="search-error" role="alert" hidden></p>
</form>"""


def home(p, cities, offers, updated):
    today = date.today()
    by_code = {c["code"]: c for c in cities}
    credits = load_credits()
    pictured = [c for c in cities if c["code"] in credits and photo_exists(c["code"])]
    best = cities[0]["best"]
    hero_code = HERO_PHOTO if photo_exists(HERO_PHOTO) else (pictured[0]["code"] if pictured else "")
    hero_image = f'<img class="hero-img" src="{p.base}assets/photos/{hero_code}.jpg" alt="">' if hero_code else ""
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
    region_links = "".join(
        f'<a class="pill" href="{p.root}vols/?region={e(p.region(name))}">{e(p.region(name))}<span>{p.t("from_price", price=p.euro(price))}</span></a>'
        for name, price in sorted(regions.items(), key=lambda kv: kv[1])
    )
    budgets = "".join(
        f'<a class="budget" href="{p.root}vols/?budget={value}"><strong>{p.t("under", price=p.euro(value))}</strong><span>{p.t("places_count", count=sum(1 for c in cities if c["best"]["price"] <= value))}</span></a>'
        for value in (100, 300, 600, 1000)
    )
    nothing = f'<li class="empty">{p.t("nothing")}</li>'
    body = f"""<section class="hero">
  {hero_image}
  <div class="hero-in">
    <h1>{p.t('hero')}</h1>
    <p>{e(p.t('hero_sub', city=p.city(best['code'], best['city']), price=p.euro(best['price'])))}</p>
  </div>
</section>
<div class="wrap search-wrap">{search_form(p)}</div>
<ul class="perks wrap">
  <li><strong>{p.t('perk_1')}</strong><span>{p.t('perk_1b')}</span></li>
  <li><strong>{p.t('perk_2')}</strong><span>{p.t('perk_2b')}</span></li>
  <li><strong>{p.t('perk_3')}</strong><span>{p.t('perk_3b')}</span></li>
</ul>
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
  <a class="test-cta" href="{p.root}test-reservation/"><strong>{p.t('test_cta')}</strong><span>{p.t('test_cta_b')}</span></a>
</section>"""
    return layout(p, f"{p.site['name']} — {p.t('title_home')}", p.t("meta_home"), "", body)


def flights_page(p):
    options = "".join(f'<option value="{v}">{p.euro(v)}</option>' for v in (50, 100, 200, 300, 400, 600, 1000))
    body = f"""<section class="page wrap">
  <h1>{p.t('flights_title')}</h1>
  <p class="lead">{p.t('flights_lead')}</p>
  <form class="filters" id="filters">
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
        cover = f'<figure class="cover"><img src="{p.base}assets/photos/{city["code"]}.jpg" alt="{name}"></figure>'
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


def build_language(p, data, cities, updated_at):
    lang, folder = p.lang, p.folder
    updated = f"{updated_at.day} {MONTHS[lang][updated_at.month - 1]}, {updated_at:%H:%M} UTC"
    offers = data["offers"]
    translated = [
        {**offer, "city": p.city(offer["code"], offer["city"]), "region": p.region(offer["region"]), "region_key": offer["region"]}
        for offer in offers
    ]
    if lang != "fr":
        write(folder / "prices.json", json.dumps({**data, "offers": translated}, ensure_ascii=False, separators=(",", ":")) + "\n")
    write(folder / "index.html", home(p, cities, offers, updated))
    write(folder / "vols" / "index.html", flights_page(p))
    write(folder / "destinations" / "index.html", destinations_index(p, cities))
    write(folder / "a-propos" / "index.html", about_page(p))
    write(folder / "test-reservation" / "index.html", test_booking_page(p))
    write(folder / "credits" / "index.html", credits_page(p))
    keep = {c["slug"] for c in cities}
    for child in (folder / "destinations").iterdir():
        if child.is_dir() and child.name not in keep:
            shutil.rmtree(child)
    for city in cities:
        write(folder / "destinations" / city["slug"] / "index.html", destination_page(p, city, cities))


def build(data, site, catalog=None):
    """catalog associe chaque langue à (villes, pays), quand les listes sont disponibles."""
    site = dict(site)
    after = site["url"].split("//", 1)[1]
    site["root"] = "/" + after.split("/", 1)[1] if "/" in after else "/"
    site["version"] = re.sub(r"\D", "", data.get("updated", ""))[:12] or "1"
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
    if catalog:
        write(names_path, json.dumps(names, ensure_ascii=False, separators=(",", ":")))
    for lang in LANGS:
        build_language(Page(site, lang, names.get(lang)), data, cities, updated_at)
    write(DOCS / "404.html", missing_page(Page(site, "fr", names.get("fr"))))
    pages = ["", "vols/", "destinations/", "a-propos/"] + [f"destinations/{c['slug']}/" for c in cities]
    urls = "".join(
        f"<url><loc>{e(site['url'] + ('' if lang == 'fr' else lang + '/') + page)}</loc></url>"
        for lang in LANGS for page in pages
    )
    write(DOCS / "sitemap.xml", f'<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{urls}</urlset>\n')
    write(DOCS / "robots.txt", f"User-agent: *\nAllow: /\nSitemap: {site['url']}sitemap.xml\n")
    return len(cities)


def load_catalog():
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
