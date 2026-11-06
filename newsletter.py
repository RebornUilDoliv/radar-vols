"""Prépare la newsletter du jeudi et la programme dans Brevo."""
import html
import json
import os
import sys
import tomllib
import urllib.error
import urllib.request
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import build_site

ROOT = Path(__file__).parent
PARIS = ZoneInfo("Europe/Paris")
BREVO = "https://api.brevo.com/v3"
ORIGIN = "PAR"
SEND_HOUR = 8
FAR, NEAR = 3, 3
MIN_DAYS = 14
SKIPPED = {"MED"}                 # villes qui ne conviennent pas à une offre grand public

esc = html.escape


def send_time(now):
    """Prochain jeudi à 8 h, heure de Paris."""
    local = now.astimezone(PARIS)
    days = (3 - local.weekday()) % 7
    moment = datetime.combine(local.date() + timedelta(days=days), time(SEND_HOUR), PARIS)
    return moment + timedelta(days=7) if moment <= local else moment


def is_due(state, now):
    """Le mercredi soir ou le jeudi tôt, une seule fois par semaine."""
    moment = send_time(now)
    left = moment - now.astimezone(PARIS)
    week = moment.strftime("%G-%V")
    return timedelta(minutes=20) < left <= timedelta(hours=14) and state.get("last_newsletter") != week


def pick_routes(origin, geo, today):
    """Les meilleurs prix depuis Paris : quelques longs courriers et quelques escapades."""
    start = today + timedelta(days=MIN_DAYS)
    here = geo.get(origin["code"])
    far, near, seen = [], [], set()
    for route in origin["routes"]:
        if route["to"] in seen or date.fromisoformat(route["depart"]) < start or route["to"] not in geo or not here:
            continue
        if not build_site.photo_exists(route["to"]) or route["to"] in SKIPPED:
            continue
        seen.add(route["to"])
        group = far if build_site.distance_km(here, geo[route["to"]]) >= 4000 else near
        group.append(route)
    return far[:FAR], near[:NEAR]


def route_url(origin, route, page):
    if build_site.has_page(page, origin, route):
        return f"{page.site['url']}{build_site.route_path(origin, route)}"
    return route["link"]


def route_row(origin, route, page):
    city = esc(page.city(route["to"], route["to"]))
    dates = f'{esc(page.day(route["depart"], False))} → {esc(page.day(route["back"]))}'
    return f"""<tr><td style="padding:14px 0;border-bottom:1px solid #e4e4e4;font-family:Helvetica,Arial,sans-serif;">
<a href="{esc(route_url(origin, route, page))}" style="color:#0b0b0b;font-size:18px;font-weight:bold;text-decoration:none;">{city}</a>
<div style="margin-top:3px;color:#6a6a6a;font-size:14px;">{dates} · {esc(page.stops(route))}</div></td>
<td align="right" style="padding:14px 0;border-bottom:1px solid #e4e4e4;font-family:Helvetica,Arial,sans-serif;font-size:20px;font-weight:bold;white-space:nowrap;">{page.euro(route["price"])}</td></tr>"""


def heading(text):
    return f'<h2 style="margin:30px 0 4px;font-family:Helvetica,Arial,sans-serif;font-size:22px;line-height:1.2;color:#0b0b0b;">{esc(text)}</h2>'


def service_cell(url, title, text):
    return f"""<td width="50%" valign="top" style="padding:5px;"><a href="{esc(url)}" style="display:block;padding:15px;background:#f4f4f4;border-radius:12px;color:#0b0b0b;text-decoration:none;font-family:Helvetica,Arial,sans-serif;">
<strong style="display:block;font-size:16px;">{esc(title)}</strong><span style="display:block;margin-top:3px;color:#6a6a6a;font-size:13px;">{esc(text)}</span></a></td>"""


def build_email(page, origin, geo, today):
    far, near = pick_routes(origin, geo, today)
    if not far and not near:
        return None
    best = (far or near)[0]
    city = page.city(best["to"], best["to"])
    url = page.site["url"]
    photo = best["to"] if build_site.photo_exists(best["to"]) else "BKK"
    services = build_site.stay_items(page, "")
    cells = [service_cell(u, title, text) for u, title, text, _ in services]
    grid = "".join(f"<tr>{cells[n]}{cells[n + 1]}</tr>" for n in range(0, len(cells) - 1, 2))
    far_block = heading("Les grandes envies") + f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0">{"".join(route_row(origin, r, page) for r in far)}</table>' if far else ""
    near_block = heading("Les escapades") + f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0">{"".join(route_row(origin, r, page) for r in near)}</table>' if near else ""
    body = f"""<!doctype html><html lang="fr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Les bons plans Eunodia</title></head>
<body style="margin:0;padding:0;background:#f4f4f4;">
<div style="display:none;max-height:0;overflow:hidden;">{esc(city)} dès {page.euro(best["price"])} et d'autres vols repérés cette semaine.</div>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#f4f4f4;"><tr><td align="center" style="padding:24px 12px;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="width:100%;max-width:600px;background:#fff;border-radius:18px;overflow:hidden;">
<tr><td style="background:#0b0b0b;padding:20px 28px;"><table role="presentation" cellpadding="0" cellspacing="0"><tr><td style="padding-right:10px;"><img src="{url}assets/icon-192.png" width="30" height="30" alt="" style="display:block;border-radius:15px;"></td><td style="color:#fff;font-family:Helvetica,Arial,sans-serif;font-size:20px;font-weight:bold;">Eunodia</td></tr></table></td></tr>
<tr><td><img src="{url}assets/photos/{photo}.jpg" width="600" alt="{esc(city)}" style="display:block;width:100%;height:auto;"></td></tr>
<tr><td style="padding:30px 30px 34px;">
<h1 style="margin:0 0 10px;font-family:Helvetica,Arial,sans-serif;font-size:30px;line-height:1.2;color:#0b0b0b;">{esc(city)} dès {page.euro(best["price"])}</h1>
<p style="margin:0;font-family:Helvetica,Arial,sans-serif;font-size:16px;line-height:1.5;color:#3f3f3f;">Voici les meilleurs prix repérés cette semaine au départ de Paris, en aller-retour.</p>
{far_block}{near_block}
{heading("Prépare ton voyage")}
<p style="margin:0 0 10px;font-family:Helvetica,Arial,sans-serif;font-size:15px;color:#3f3f3f;">Hôtel, activités, internet ou transfert : tout est prêt pour ton séjour.</p>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin:0 -5px;">{grid}</table>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin-top:26px;"><tr><td align="center" bgcolor="#0b0b0b" style="border-radius:12px;"><a href="{url}vols/?origin=PAR" style="display:block;padding:16px 22px;color:#fff;font-family:Helvetica,Arial,sans-serif;font-size:16px;font-weight:bold;text-decoration:none;">Voir où je peux partir</a></td></tr></table>
</td></tr>
<tr><td style="padding:20px 30px 26px;background:#f4f4f4;font-family:Helvetica,Arial,sans-serif;font-size:12px;line-height:1.5;color:#6a6a6a;">
Prix relevés récemment, par personne et sans options : ils peuvent changer vite, vérifie toujours le prix final avant de réserver. Certains liens sont partenaires : Eunodia peut toucher une commission, sans frais pour toi.<br><br>
Tu reçois cet e-mail car tu t'es inscrit sur <a href="{url}" style="color:#0b0b0b;">eunodia.com</a>. Contact : <a href="mailto:contact@eunodia.com" style="color:#0b0b0b;">contact@eunodia.com</a>. <a href="{{{{ unsubscribe }}}}" style="color:#0b0b0b;">Se désinscrire</a>.
</td></tr></table></td></tr></table></body></html>"""
    return {"subject": f"{city} dès {page.euro(best['price'])} : les bons plans de la semaine", "preview": f"{city} dès {page.euro(best['price'])} au départ de Paris", "html": body}


def brevo(path, key, body):
    request = urllib.request.Request(f"{BREVO}{path}", data=json.dumps(body).encode(), method="POST",
                                     headers={"api-key": key, "content-type": "application/json", "accept": "application/json"})
    with urllib.request.urlopen(request, timeout=45) as response:
        text = response.read()
    return json.loads(text) if text else {}


def load_page(config):
    site = dict(config["site"])
    after = site["url"].split("//", 1)[1]
    site["root"] = "/" + after.split("/", 1)[1] if "/" in after else "/"
    names = build_site.clean_names(json.loads((ROOT / "docs/assets/names.json").read_text()))
    return build_site.Page(site, "fr", names["fr"]), names["fr"]


def prepare(config, today):
    page, names = load_page(config)
    geo = json.loads((ROOT / "docs/assets/geo.json").read_text())
    origin = next((o for o in build_site.load_world(names) if o["code"] == ORIGIN), None)
    return build_email(page, origin, geo, today) if origin else None


def main():
    config = tomllib.loads((ROOT / "config.toml").read_text())
    now = datetime.now(PARIS)
    if "--preview" in sys.argv:
        email = prepare(config, now.date())
        (ROOT / "newsletter-apercu.html").write_text(email["html"])
        print(email["subject"])
        return 0
    key = os.environ.get("BREVO_API_KEY")
    state_path = ROOT / "data" / "state.json"
    state = json.loads(state_path.read_text()) if state_path.exists() else {}
    if not key:
        print("Newsletter : clé Brevo absente.")
        return 0
    if not is_due(state, now):
        print("Newsletter : pas encore le moment.")
        return 0
    email = prepare(config, now.date())
    if not email:
        print("Newsletter : aucune offre, envoi annulé.", file=sys.stderr)
        return 1
    moment = send_time(now)
    settings = config["newsletter"]
    try:
        result = brevo("/emailCampaigns", key, {
            "name": f"Bons plans du {moment:%d/%m/%Y}", "subject": email["subject"], "previewText": email["preview"],
            "sender": {"name": "Eunodia", "email": settings["sender"]}, "htmlContent": email["html"],
            "recipients": {"listIds": [settings["list_id"]]}, "scheduledAt": moment.isoformat(),
        })
    except urllib.error.HTTPError as error:
        print(f"Newsletter : Brevo a refusé ({error.code}) : {error.read()[:300].decode(errors='replace')}", file=sys.stderr)
        return 1
    state["last_newsletter"] = moment.strftime("%G-%V")
    state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2))
    print(f"Newsletter programmée pour {moment:%d/%m/%Y %H:%M} (campagne {result.get('id')}).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
