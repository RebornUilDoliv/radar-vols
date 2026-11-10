"""Récupère les trajets Omio (train, bus) depuis les catalogues Impact, une fois par jour.

Écrit docs/omio/<langue>.json, lu par l'onglet « Train & bus » de la page d'accueil :
  {"updated": ..., "currency": "EUR", "link": "<modèle de lien>", "tld": "fr",
   "cities": [[id, nom], ...], "routes": [[départ, arrivée, prix ou 0], ...], "links": {"o_d": url}}
Les lien de réservation passent par Impact avec le numéro de partenaire (commission Omio).
"""
import base64
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).parent
OUT = ROOT / "docs" / "omio"
API = "https://api.impact.com"
MAX_AGE = timedelta(hours=20)
# Langue du site -> catalogue Omio (les langues sans catalogue prennent l'anglais UK)
CATALOGS = {"fr": 12203, "en": 12215, "es": 12197, "de": 12200, "it": 12205, "pt": 12213, "nl": 12210, "zh": 12199}
FALLBACK = "en"


def credentials():
    sid, token = os.environ.get("IMPACT_ACCOUNT_SID", "").strip(), os.environ.get("AUTH_TOKEN_IMPACT", "").strip()
    if not sid or not token:
        sys.exit("omio : identifiants Impact absents, rien à faire")
    return sid, "Basic " + base64.b64encode(f"{sid}:{token}".encode()).decode()


def get(path, auth):
    for attempt in range(4):
        request = urllib.request.Request(API + path, headers={"Accept": "application/json", "Authorization": auth})
        try:
            with urllib.request.urlopen(request, timeout=90) as response:
                return json.loads(response.read())
        except urllib.error.HTTPError as error:
            if error.code in (429, 500, 502, 503, 504) and attempt < 3:
                time.sleep(10 * (attempt + 1))
                continue
            raise
        except urllib.error.URLError:
            if attempt < 3:
                time.sleep(10 * (attempt + 1))
                continue
            raise


def items(catalog, sid, auth):
    path = f"/Mediapartners/{sid}/Catalogs/{catalog}/Items?PageSize=1000"
    while path:
        page = get(path, auth)
        yield from page.get("Items", [])
        path = page.get("@nextpageuri") or ""
        time.sleep(0.3)


def link_parts(url):
    """Découpe un lien Omio : (modèle commun, tld) ou None si le format est inattendu."""
    parsed = urllib.parse.urlsplit(url)
    query = urllib.parse.parse_qs(parsed.query)
    target = query.get("u", [""])[0]
    page_id = urllib.parse.parse_qs(urllib.parse.urlsplit(target).query).get("id", [""])[0]
    try:
        kind, tld, origin, destination = base64.b64decode(page_id).decode().split(".")
    except ValueError:
        return None
    if kind != "connection_page_nt":
        return None
    template = (f"{parsed.scheme}://{parsed.netloc}{parsed.path}?prodsku={{o}}_{{d}}&u="
                + urllib.parse.quote(f"https://omio.{tld}/lps/?id=", safe="") + "{b64}"
                + "&intsrc=" + query.get("intsrc", [""])[0])
    return template, tld


def rebuild(template, tld, origin, destination):
    b64 = base64.b64encode(f"connection_page_nt.{tld}.{origin}.{destination}".encode()).decode()
    return template.replace("{o}", origin).replace("{d}", destination).replace("{b64}", urllib.parse.quote(b64, safe=""))


def price(item):
    for key in ("CurrentPrice", "Price", "OriginalPrice"):
        try:
            value = float(item.get(key) or 0)
        except ValueError:
            continue
        if value > 0:
            return round(value, 2)
    return 0


def build(raw):
    """Transforme les articles du catalogue en données compactes pour le site."""
    cities, index, routes, links = [], {}, [], {}
    template = tld = currency = None
    seen = set()
    for item in raw:
        sku = str(item.get("CatalogItemId") or "")
        name = str(item.get("Name") or "")
        if "_" not in sku or " - " not in name or not item.get("Url"):
            continue
        origin, destination = sku.split("_", 1)
        if (origin, destination) in seen:
            continue
        seen.add((origin, destination))
        origin_name = (item.get("ShippingLabel") or name.split(" - ", 1)[0]).strip()
        destination_name = (item.get("Text3") or name.split(" - ", 1)[1]).strip()
        currency = currency or item.get("Currency")
        if template is None:
            parts = link_parts(item["Url"])
            if parts:
                template, tld = parts
        if not template or rebuild(template, tld, origin, destination) != item["Url"]:
            links[sku] = item["Url"]
        for city_id, city_name in ((origin, origin_name), (destination, destination_name)):
            if city_id not in index:
                index[city_id] = len(cities)
                cities.append([city_id, city_name])
        routes.append([index[origin], index[destination], price(item)])
    return {"currency": currency or "EUR", "link": template or "", "tld": tld or "",
            "cities": cities, "routes": routes, "links": links}


def fresh(path, now):
    if not path.exists():
        return False
    try:
        updated = datetime.fromisoformat(json.loads(path.read_text())["updated"])
    except (ValueError, KeyError):
        return False
    return now - updated < MAX_AGE


def main():
    now = datetime.now(timezone.utc)
    sid, auth = credentials()
    OUT.mkdir(parents=True, exist_ok=True)
    for lang, catalog in CATALOGS.items():
        path = OUT / f"{lang}.json"
        if fresh(path, now) and "--force" not in sys.argv:
            print(f"omio {lang} : déjà à jour")
            continue
        try:
            data = build(items(catalog, sid, auth))
        except Exception as error:  # on garde l'ancien fichier si Impact ne répond pas
            print(f"omio {lang} : échec ({error})")
            continue
        if not data["routes"]:
            print(f"omio {lang} : catalogue vide, fichier conservé")
            continue
        data["updated"] = now.isoformat(timespec="seconds")
        path.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")))
        priced = sum(1 for route in data["routes"] if route[2])
        print(f"omio {lang} : {len(data['routes'])} trajets ({priced} avec prix), {len(data['cities'])} villes, "
              f"{len(data['links'])} liens à part, {path.stat().st_size // 1024} ko")


if __name__ == "__main__":
    main()
