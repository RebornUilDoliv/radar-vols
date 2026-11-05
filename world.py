"""Relève les meilleurs prix depuis de grandes villes du monde entier."""
import json
import os
import sys
import tomllib
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import radar

ROOT = Path(__file__).parent
OUTPUT = ROOT / "docs" / "world.json"
MIN_HOURS = 20


def is_recent(path, now):
    if not path.exists():
        return False
    updated = json.loads(path.read_text()).get("updated")
    return bool(updated) and now - datetime.fromisoformat(updated) < timedelta(hours=MIN_HOURS)


def best_routes(origin, offers, places, site, today):
    """Garde le prix le plus bas de chaque destination connue."""
    best = {}
    for offer in offers:
        if offer.destination == origin or offer.destination not in places:
            continue
        if offer.depart <= today or offer.back <= offer.depart:
            continue
        if offer.destination not in best or offer.price < best[offer.destination].price:
            best[offer.destination] = offer
    search = {"origin_city": origin}
    return [
        {"from": origin, "to": code, "price": round(offer.price), "depart": str(offer.depart), "back": str(offer.back),
         "stops": offer.stops, "link": radar.partner_link(radar.aviasales_link(offer, search), site)}
        for code, offer in sorted(best.items(), key=lambda item: item[1].price)
    ]


def main():
    config = tomllib.loads((ROOT / "config.toml").read_text())
    token = os.environ.get("TRAVELPAYOUTS_TOKEN")
    if not token:
        print("TRAVELPAYOUTS_TOKEN manquant.", file=sys.stderr)
        return 2
    now = datetime.now(timezone.utc)
    if is_recent(OUTPUT, now):
        print("Relevé mondial récent : rien à faire.")
        return 0
    places = radar.load_places()
    routes = []
    for origin in config["world"]["origins"]:
        client = radar.Travelpayouts(token, {**config["search"], "origin_city": origin})
        found = best_routes(origin, client.discovery(), places, config["site"], date.today())
        print(f"{origin} : {len(found)} routes")
        routes += found
    if not routes:
        print("Aucun prix mondial : fichier conservé.", file=sys.stderr)
        return 1
    OUTPUT.write_text(json.dumps({"updated": now.isoformat(timespec="minutes"), "routes": routes},
                                 ensure_ascii=False, separators=(",", ":")) + "\n")
    print(f"{len(routes)} routes enregistrées.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
