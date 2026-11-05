#!/usr/bin/env python3
"""Génère le site statique de Radar Flight à partir de docs/prices.json."""
import html
import json
import re
import shutil
import sys
import tomllib
import unicodedata
from datetime import date, datetime, timedelta
from pathlib import Path

import radar

ROOT = Path(__file__).parent
DOCS = ROOT / "docs"
MONTHS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août",
          "septembre", "octobre", "novembre", "décembre"]
SHORT_MONTHS = ["janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc."]
SOON_DAYS = 45
AHEAD_DAYS = 150
e = html.escape


def slug(text):
    plain = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", plain.lower()).strip("-")


def euro(value):
    return f"{value:,.0f}".replace(",", " ") + " €"


def day(iso, year=True):
    value = date.fromisoformat(iso)
    label = f"{value.day} {SHORT_MONTHS[value.month - 1]}"
    return f"{label} {value.year}" if year else label


def month_name(key):
    year, month = key.split("-")
    return f"{MONTHS[int(month) - 1]} {year}"


def nights(offer):
    return (date.fromisoformat(offer["back"]) - date.fromisoformat(offer["depart"])).days


def stops(offer):
    count = offer.get("stops")
    if count is None:
        return "escales non précisées"
    return "vol direct" if count == 0 else f"{count} escale{'s' if count > 1 else ''}"


def photo_exists(code):
    return (DOCS / "assets" / "photos" / f"{code}.jpg").exists()


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


def layout(site, title, description, path, body, scripts=True, noindex=False):
    base = site["url"]
    home = base.split("//", 1)[1].split("/", 1)[1] if "/" in base.split("//", 1)[1] else ""
    root = "/" + home
    name = e(site["name"])
    script = f'<script src="{root}assets/app.js?v={site["version"]}" defer></script>' if scripts else ""
    return f"""<!doctype html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(title)}</title>
<meta name="description" content="{e(description)}">
<link rel="canonical" href="{e(base + path)}">
{'<meta name="robots" content="noindex, nofollow">' if noindex else ''}
<meta property="og:title" content="{e(title)}">
<meta property="og:description" content="{e(description)}">
<meta property="og:type" content="website">
<link rel="icon" href="{root}assets/icon.svg" type="image/svg+xml">
<link rel="stylesheet" href="{root}assets/style.css?v={site['version']}">
{script}
</head>
<body data-root="{root}">
<a class="skip" href="#contenu">Aller au contenu</a>
<header class="nav">
  <a class="logo" href="{root}">{name}</a>
  <nav aria-label="Navigation principale">
    <a href="{root}vols/">Les vols</a>
    <a href="{root}destinations/">Destinations</a>
    <a href="{root}a-propos/">Infos</a>
  </nav>
</header>
<main id="contenu">
{body}
</main>
<footer class="foot">
  <div class="wrap">
    <p class="foot-brand">{name}</p>
    <p>Les prix viennent de recherches récentes et peuvent changer vite. Vérifie toujours le prix final, les bagages et les options avant de payer.</p>
    <p>{name} ne vend pas de billets. Les liens vers les vols sont affiliés : si tu réserves, le site peut toucher une commission, sans frais pour toi.</p>
    <p><a href="{root}a-propos/">Infos</a> · <a href="{root}destinations/">Destinations</a></p>
  </div>
</footer>
</body>
</html>
"""


def flight_card(offer, root, city):
    page = f'{root}destinations/{city["slug"]}/'
    title = f'<a href="{page}">{e(offer["city"])}</a>'
    return f"""<li class="row">
  <div class="row-info">
    <h3>{title}</h3>
    <p>{e(day(offer['depart'], False))} → {e(day(offer['back']))}, {nights(offer)} jours, {e(stops(offer))}</p>
  </div>
  <p class="row-price">{euro(offer['price'])}</p>
  <a class="go" href="{page}?mois={offer['depart'][:7]}" aria-label="Voir le vol pour {e(offer['city'])}">Voir</a>
</li>"""


def load_credits():
    path = DOCS / "assets" / "photos" / "credits.json"
    return json.loads(path.read_text()) if path.exists() else {}


def photo_credit(credit):
    license_name = e(credit["license"])
    if credit.get("license_url"):
        license_name = f'<a href="{e(credit["license_url"])}" rel="noopener">{license_name}</a>'
    return f'Photo : <a href="{e(credit["source"])}" rel="noopener">{e(credit["artist"])}</a>, {license_name}, redimensionnée'


def photo_figure(site, city, credit, wide=False):
    root = site["root"]
    best = city["best"]
    return f"""<figure class="photo{' wide' if wide else ''}">
  <a href="{root}destinations/{city['slug']}/"><img src="{root}assets/photos/{city['code']}.jpg" alt="{e(city['city'])}" loading="lazy" width="1280" height="720"></a>
  <figcaption><a href="{root}destinations/{city['slug']}/"><strong>{e(city['city'])}</strong> dès {euro(best['price'])}</a><small>{photo_credit(credit)}</small></figcaption>
</figure>"""


def search_form(root):
    return f"""<form class="search" id="search" data-target="https://www.aviasales.com/search/" autocomplete="off">
  <div class="field grow"><label for="from">Départ</label><input id="from" value="Paris (PAR)" data-code="PAR" placeholder="Ville ou aéroport" required>
    <ul class="suggest" hidden></ul></div>
  <button class="swap" id="swap" type="button" aria-label="Inverser départ et destination">⇄</button>
  <div class="field grow"><label for="to">Destination</label><input id="to" placeholder="Une ville, partout dans le monde" required>
    <ul class="suggest" hidden></ul></div>
  <div class="field"><label for="out">Aller</label><input id="out" type="date" required></div>
  <div class="field"><label for="back">Retour</label><input id="back" type="date"></div>
  <div class="field small"><label for="pax">Voyageurs</label><select id="pax"><option>1</option><option>2</option><option>3</option><option>4</option><option>5</option><option>6</option></select></div>
  <button class="search-go" type="submit">Chercher</button>
  <p class="form-error" id="search-error" role="alert" hidden></p>
</form>"""


def home(site, cities, offers, updated):
    root = site["root"]
    today = date.today()
    by_code = {c["code"]: c for c in cities}
    credits = load_credits()
    pictured = [c for c in cities if c["code"] in credits and photo_exists(c["code"])]
    photos = ""
    if pictured:
        cover = max(pictured, key=lambda c: c["code"] == "PRG")
        rest = [c for c in pictured if c is not cover][:3]
        photos = f"""<section class="band wrap">
  <h2>Quelques idées</h2>
  {photo_figure(site, cover, credits[cover['code']], wide=True)}
  <div class="photos">{''.join(photo_figure(site, c, credits[c['code']]) for c in rest)}</div>
</section>"""
    deals = "".join(flight_card(c["best"], root, c) for c in cities[:10])
    soon_list = sorted((o for o in offers if (date.fromisoformat(o["depart"]) - today).days <= SOON_DAYS), key=lambda o: o["price"])
    ahead_list = sorted((o for o in offers if (date.fromisoformat(o["depart"]) - today).days >= AHEAD_DAYS), key=lambda o: o["price"])

    def unique(items):
        seen, out = set(), []
        for item in items:
            if item["code"] not in seen:
                seen.add(item["code"])
                out.append(item)
        return out[:4]

    soon = "".join(flight_card(o, root, by_code[o["code"]]) for o in unique(soon_list))
    ahead = "".join(flight_card(o, root, by_code[o["code"]]) for o in unique(ahead_list))
    regions = {}
    for offer in offers:
        regions[offer["region"]] = min(offer["price"], regions.get(offer["region"], 10**9))
    region_links = "".join(
        f'<li><a href="{root}vols/?region={e(name)}">{e(name)}</a>, dès {euro(price)}</li>'
        for name, price in sorted(regions.items(), key=lambda kv: kv[1])
    )
    budget_links = "".join(
        f'<li><a href="{root}vols/?budget={value}">Moins de {euro(value)}</a>, {sum(1 for c in cities if c["best"]["price"] <= value)} destinations</li>'
        for value in (100, 300, 600, 1000)
    )
    body = f"""<section class="intro wrap">
  <h1>Les vols pas chers du moment, depuis Paris.</h1>
  <p class="lead">La liste est mise à jour deux fois par jour. Les prix bougent vite, alors vérifie toujours avant de payer.</p>
  {search_form(root)}
</section>
<section class="band wrap">
  <div class="head"><h2>Les moins chers aujourd'hui</h2><a href="{root}vols/">Voir tous les vols</a></div>
  <p class="sub">Aller-retour par personne. Dernier relevé le {e(updated)}. Ces prix peuvent avoir augmenté depuis.</p>
  <ul class="rows">{deals}</ul>
</section>
{photos}
<section class="band wrap two">
  <div><h2>Partir bientôt</h2><p class="sub">Moins de {SOON_DAYS} jours avant le départ. La dernière minute coûte souvent plus cher, donc il y a moins de bonnes surprises.</p><ul class="rows">{soon or '<li class="empty">Rien d\'intéressant en ce moment.</li>'}</ul></div>
  <div><h2>Réserver à l'avance</h2><p class="sub">Plus de 5 mois avant le départ.</p><ul class="rows">{ahead or '<li class="empty">Rien d\'intéressant en ce moment.</li>'}</ul></div>
</section>
<section class="band wrap two">
  <div><h2>Selon ton budget</h2><ul class="plain">{budget_links}</ul></div>
  <div><h2>Par région</h2><ul class="plain">{region_links}</ul></div>
</section>"""
    return layout(site, f"{site['name']} — vols pas chers depuis Paris",
                  "Les vols les moins chers repérés au départ de Paris, et une recherche pour partir de partout vers partout.", "", body)


def flights_page(site):
    body = """<section class="page wrap">
  <h1>Tous les vols depuis Paris</h1>
  <p class="lead">Tu peux filtrer par région, mois, budget ou durée.</p>
  <form class="filters" id="filters" aria-label="Filtrer les vols">
    <label>Rechercher<input id="q" type="search" placeholder="Une ville"></label>
    <label>Région<select id="region"><option value="">Toutes</option></select></label>
    <label>Mois<select id="month"><option value="">Tous</option></select></label>
    <label>Budget<select id="budget"><option value="">Sans limite</option><option value="50">50 €</option><option value="100">100 €</option><option value="200">200 €</option><option value="300">300 €</option><option value="400">400 €</option><option value="600">600 €</option><option value="1000">1 000 €</option></select></label>
    <label>Durée<select id="length"><option value="">Toutes</option><option value="0-7">Moins d'une semaine</option><option value="8-21">1 à 3 semaines</option><option value="22-999">Plus de 3 semaines</option></select></label>
    <label>Trier<select id="sort"><option value="price">Prix</option><option value="depart">Date de départ</option></select></label>
  </form>
  <p class="count" id="count" role="status"></p>
  <ul class="rows" id="offers"></ul>
  <button class="more" id="more" type="button" hidden>Afficher plus de vols</button>
</section>"""
    return layout(site, f"Tous les vols pas chers depuis Paris | {site['name']}",
                  "Tous les vols aller-retour repérés au départ de Paris, à filtrer par région, mois, budget et durée.", "vols/", body)


def destinations_index(site, cities):
    root = site["root"]
    groups = {}
    for city in cities:
        groups.setdefault(city["region"], []).append(city)
    blocks = ""
    for region in sorted(groups, key=lambda r: groups[r][0]["best"]["price"]):
        links = "".join(
            f'<li><a href="{root}destinations/{c["slug"]}/"><span>{e(c["city"])}</span><span>dès {euro(c["best"]["price"])}</span></a></li>'
            for c in sorted(groups[region], key=lambda c: c["city"])
        )
        blocks += f'<section class="dest-group"><h2>{e(region)}</h2><ul class="links">{links}</ul></section>'
    body = f'<section class="page wrap"><h1>Toutes les destinations</h1><p class="lead">{len(cities)} villes surveillées au départ de Paris.</p>{blocks}</section>'
    return layout(site, f"Destinations au départ de Paris | {site['name']}",
                  f"{len(cities)} destinations surveillées au départ de Paris, du moins cher au plus cher.", "destinations/", body)


def merged_history(city):
    days = {}
    for offer in city["offers"]:
        for when, price in offer.get("history", []):
            days[when] = min(price, days.get(when, price))
    return [[when, days[when]] for when in sorted(days)]


def destination_page(site, city, cities):
    root = site["root"]
    best = city["best"]
    months = {}
    for offer in city["offers"]:
        key = offer["depart"][:7]
        if key not in months or offer["price"] < months[key]["price"]:
            months[key] = offer
    rows = "".join(
        f'<tr id="m-{key}"><th scope="row">{e(month_name(key).capitalize())}</th><td>{e(day(o["depart"]))} → {e(day(o["back"]))}</td>'
        f'<td>{e(stops(o))}</td><td class="num">{euro(o["price"])}</td>'
        f'<td><a class="go" href="{e(o["link"])}" rel="nofollow sponsored noopener" target="_blank">Vérifier le prix</a></td></tr>'
        for key, o in sorted(months.items())
    )
    cheapest_month = month_name(best["depart"][:7])
    history = merged_history(city)
    chart = ""
    if len(history) >= 3:
        data = e(json.dumps(history, separators=(",", ":")))
        chart = f'<section class="panel"><h2>Évolution du prix le plus bas relevé</h2><div class="chart" data-history="{data}"></div></section>'
    others = [c for c in cities if c["region"] == city["region"] and c["code"] != city["code"]][:6]
    related = "".join(
        f'<li><a href="{root}destinations/{c["slug"]}/"><span>{e(c["city"])}</span><span>dès {euro(c["best"]["price"])}</span></a></li>'
        for c in others
    )
    related_block = f'<section class="panel"><h2>Autres idées : {e(city["region"])}</h2><ul class="links">{related}</ul></section>' if others else ""
    name = e(city["city"])
    credits = load_credits()
    cover = ""
    if city["code"] in credits and photo_exists(city["code"]):
        cover = f"""<figure class="photo wide"><img src="{root}assets/photos/{city['code']}.jpg" alt="{name}" width="1280" height="720"><figcaption><small>{photo_credit(credits[city['code']])}</small></figcaption></figure>"""
    body = f"""<section class="page wrap">
  <p class="crumb"><a href="{root}destinations/">Destinations</a> › {e(city['region'])}</p>
  <h1>Vols Paris – {name}</h1>
  {cover}
  <p class="lead">Le prix le plus bas relevé est <strong>{euro(best['price'])}</strong> l'aller-retour, en {e(cheapest_month)}.</p>
  <aside class="notice"><strong>Pourquoi le prix peut être différent ?</strong> Ces prix viennent de recherches faites récemment par d'autres voyageurs. Quand tu cliques sur « Vérifier le prix », tu quittes ce site pour Aviasales, qui cherche le prix exact en direct. Il peut être plus élevé si les places les moins chères sont parties.</aside>
  <section class="panel"><h2>Le meilleur prix par mois</h2>
    <div class="scroll"><table><thead><tr><th scope="col">Mois</th><th scope="col">Dates</th><th scope="col">Escales</th><th scope="col" class="num">Prix</th><th scope="col"><span class="sr">Lien</span></th></tr></thead><tbody>{rows}</tbody></table></div>
  </section>
  {chart}
  {related_block}
</section>"""
    return layout(site, f"Vols Paris – {city['city']} dès {euro(best['price'])} | {site['name']}",
                  f"Le prix le plus bas relevé pour un vol Paris – {city['city']}, mois par mois.",
                  f"destinations/{city['slug']}/", body)


def about_page(site):
    name = e(site["name"])
    root = site["root"]
    faq = [
        ("D'où viennent les prix ?", f"{name} utilise les prix trouvés récemment par d'autres voyageurs sur un comparateur partenaire. Ils sont relevés deux fois par jour et peuvent avoir changé entre-temps : ils servent à repérer une bonne idée, pas à garantir un tarif."),
        ("Pourquoi un prix peut-il être différent sur le site de réservation ?", "Les places à petit prix partent vite, et un bagage ou une option peut s'ajouter. Quand un contrôle montre qu'un prix n'existe plus, le vol est retiré de la liste, mais tous les vols ne peuvent pas être contrôlés."),
        ("La dernière minute est-elle moins chère ?", "En général, non : les prix ont plutôt tendance à monter à l'approche du départ, même s'il existe des exceptions selon les trajets. C'est pour cela que la section « Partir bientôt » montre seulement ce qui reste intéressant."),
        ("Puis-je chercher un vol depuis une autre ville ?", "Oui. Le moteur de recherche de la page d'accueil fonctionne pour des vols partout dans le monde. Les occasions repérées par le radar sont, pour l'instant, au départ de Paris."),
        (f"Comment {name} gagne-t-il de l'argent ?", "Les liens vers les vols sont affiliés. Si tu réserves après avoir cliqué, le site peut toucher une commission, sans frais supplémentaires pour toi."),
        ("D'où viennent les photos ?", "Elles viennent de Wikimedia Commons. Le photographe et la licence sont indiqués sous chaque photo."),
        ("Puis-je réserver directement ici ?", f"Non. {name} ne vend pas de billets. La réservation et le paiement se font sur le site du partenaire, qui gère aussi les modifications et les remboursements."),
    ]
    items = "".join(f"<details><summary>{e(q)}</summary><p>{a}</p></details>" for q, a in faq)
    body = f'<section class="page wrap narrow"><h1>Comment ça marche</h1><p class="lead">Tout ce qu\'il faut savoir avant de cliquer.</p><div class="faq">{items}</div><p><a class="hero-go" href="{root}">Chercher un vol</a></p></section>'
    return layout(site, f"Infos | {site['name']}", f"D'où viennent les prix de {site['name']} et comment fonctionne le site.", "a-propos/", body)


def test_booking_page(site):
    root = site["root"]
    mode = "serveur de test Duffel" if site.get("test_api") else "démonstration"
    body = f"""<section class="page wrap narrow">
  <p class="test-banner"><strong>Version de test ({mode}).</strong> Aucun vrai vol, aucun vrai billet, aucun paiement.</p>
  <div id="booking" tabindex="-1" data-api="{e(site.get('test_api', ''))}"></div>
  <script src="{root}assets/booking.js?v={site['version']}-3" defer></script>
</section>"""
    return layout(site, f"Réservation de test | {site['name']}", "Page de test.", "test-reservation/", body, noindex=True)


def write(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def city_index(places, countries):
    rows = [
        [code, place["name"], countries.get(place["country"], "")]
        for code, place in places.items() if place["airports"]
    ]
    return sorted(rows, key=lambda row: row[1])


def build(data, site, places=None, countries=None):
    site = dict(site)
    site["root"] = "/" + site["url"].split("//", 1)[1].split("/", 1)[1] if "/" in site["url"].split("//", 1)[1] else "/"
    site["version"] = re.sub(r"\D", "", data.get("updated", ""))[:12] or "1"
    offers = data["offers"]
    cities = destinations(offers)
    updated_at = datetime.fromisoformat(data["updated"])
    updated = f"{updated_at.day} {MONTHS[updated_at.month - 1]} à {updated_at:%H:%M} UTC"
    slugs = {c["code"]: c["slug"] for c in cities}
    for offer in offers:
        offer["slug"] = slugs[offer["code"]]
    (DOCS / "prices.json").write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")) + "\n")
    write(DOCS / "index.html", home(site, cities, offers, updated))
    write(DOCS / "vols" / "index.html", flights_page(site))
    write(DOCS / "destinations" / "index.html", destinations_index(site, cities))
    write(DOCS / "a-propos" / "index.html", about_page(site))
    write(DOCS / "test-reservation" / "index.html", test_booking_page(site))
    write(DOCS / "404.html", layout(site, f"Page introuvable | {site['name']}", "Cette page n'existe pas.", "404.html",
                                    f'<section class="page wrap narrow"><h1>Cette page n\'existe pas</h1><p class="lead">Elle a peut-être changé d\'adresse.</p><a class="hero-go" href="{site["root"]}">Retour à l\'accueil</a></section>', scripts=False))
    shutil.rmtree(DOCS / "destinations" / "_tmp", ignore_errors=True)
    keep = {c["slug"] for c in cities}
    for folder in (DOCS / "destinations").iterdir():
        if folder.is_dir() and folder.name not in keep:
            shutil.rmtree(folder)
    for city in cities:
        write(DOCS / "destinations" / city["slug"] / "index.html", destination_page(site, city, cities))
    pages = ["", "vols/", "destinations/", "a-propos/"] + [f"destinations/{c['slug']}/" for c in cities]
    urls = "".join(f"<url><loc>{e(site['url'] + page)}</loc></url>" for page in pages)
    write(DOCS / "sitemap.xml", f'<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{urls}</urlset>\n')
    write(DOCS / "robots.txt", f"User-agent: *\nAllow: /\nSitemap: {site['url']}sitemap.xml\n")
    if places:
        rows = city_index(places, countries or {})
        write(DOCS / "assets" / "cities.json", json.dumps(rows, ensure_ascii=False, separators=(",", ":")))
    return len(cities)


def load_countries():
    rows = radar.http_json(f"{radar.TP_BASE}/data/fr/countries.json")
    return {row["code"]: row.get("name") or row["code"] for row in rows}


def main():
    config = tomllib.loads((ROOT / "config.toml").read_text())
    path = DOCS / "prices.json"
    if not path.exists():
        print("prices.json manquant : site non construit.", file=sys.stderr)
        return 1
    data = json.loads(path.read_text())
    try:
        places, countries = radar.load_places(), load_countries()
    except RuntimeError as error:
        print(f"Liste des villes non mise à jour : {error}", file=sys.stderr)
        places, countries = None, None
    count = build(data, config["site"], places, countries)
    print(f"{count} pages destination générées.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
