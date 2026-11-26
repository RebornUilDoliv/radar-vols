"""Signale à Bing (et aux autres moteurs IndexNow) les pages du site.

    python indexnow.py --nouvelles ancien_sitemap.xml   # seulement les adresses apparues depuis l'ancien plan
    python indexnow.py --tout                           # tout le plan du site (premier envoi)
"""
import html
import json
import re
import sys
import tomllib
import urllib.request
from pathlib import Path

ROOT = Path(__file__).parent
ENDPOINT = "https://api.indexnow.org/indexnow"
BATCH = 10000  # maximum accepté par envoi


def urls_of(sitemap):
    return [html.unescape(url) for url in re.findall(r"<loc>(.*?)</loc>", sitemap)]


def payloads(urls, site_url, key):
    host = site_url.split("//", 1)[1].strip("/")
    return [{"host": host, "key": key, "keyLocation": f"{site_url}{key}.txt", "urlList": urls[i:i + BATCH]}
            for i in range(0, len(urls), BATCH)]


def send(payload):
    request = urllib.request.Request(ENDPOINT, data=json.dumps(payload).encode(),
                                     headers={"Content-Type": "application/json; charset=utf-8"})
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.status


def main(args):
    site = tomllib.loads((ROOT / "config.toml").read_text())["site"]
    urls = urls_of((ROOT / "docs" / "sitemap.xml").read_text())
    if args[:1] == ["--nouvelles"]:
        old = Path(args[1])
        known = set(urls_of(old.read_text())) if old.exists() else set()
        if not known:
            print("Ancien plan du site introuvable : rien envoyé.")
            return 0
        urls = [url for url in urls if url not in known]
    elif args != ["--tout"]:
        print(__doc__, file=sys.stderr)
        return 2
    for payload in payloads(urls, site["url"], site["indexnow_key"]):
        print(f"{len(payload['urlList'])} adresses envoyées, réponse {send(payload)}")
    if not urls:
        print("Aucune nouvelle adresse.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
