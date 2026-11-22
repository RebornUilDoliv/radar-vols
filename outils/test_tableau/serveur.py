"""Serveur de test local du tableau des visites : sert worker/tableau.html et de fausses données sur /stats (clé : test-tableau)."""
import json, os, random, time, http.server, pathlib
ROOT = pathlib.Path(__file__).resolve().parents[2]
random.seed(4)
now = int(time.time() * 1000)
UA = {"iphone": "Mozilla/5.0 (iPhone; CPU iPhone OS 18_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.5 Mobile/15E148 Safari/604.1",
      "tiktok": "Mozilla/5.0 (iPhone; CPU iPhone OS 18_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 musical_ly_37.5.0 BytedanceWebview",
      "android": "Mozilla/5.0 (Linux; Android 15; SM-S921B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0 Mobile Safari/537.36",
      "bot": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) HeadlessChrome/141.0 Safari/537.36"}
rows = []
for i in range(400):
    ts = now - random.randint(0, 2 * 7 * 86400000)
    if random.random() < 0.6:
        rows.append(dict(ts=ts, path=random.choice(["/vers/pekin/", "/nl/vols/", "/pt/vols/"]), country="CN", org="Alibaba US Technology Co., Ltd.", ua=UA["bot"], sw=1920, touch=0, human=0, wd=random.choice([0, 1]), ref=""))
    else:
        c = random.choice(["FR", "FR", "FR", "ES", "IT", "DK", "BE"])
        rows.append(dict(ts=ts, path=random.choice(["/", "/vers/istanbul/", "/en/vers/copenhague/", "/vers/rovaniemi/"]), country=c, org=random.choice(["Orange", "Free SAS", "Bouygues Telecom SA", "SFR SA"]),
                         ua=random.choice([UA["iphone"], UA["tiktok"], UA["android"]]), sw=390, touch=1, human=1, wd=0, ref=random.choice(["", "", "www.tiktok.com", "eunodia.com"])))
rows.sort(key=lambda r: r["ts"])

class H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith("/stats"):
            ok = self.headers.get("Authorization") == "Bearer test-tableau"
            days = int((self.path.split("jours=") + ["1"])[1][:2].strip("&") or 1)
            body = json.dumps({"jours": days, "maintenant": now, "visites": [r for r in rows if r["ts"] >= now - 2 * days * 864e5]} if ok else {"error": "clé incorrecte"})
            self.send_response(200 if ok else 401); self.send_header("Content-Type", "application/json"); self.end_headers(); self.wfile.write(body.encode()); return
        self.send_response(200); self.send_header("Content-Type", "text/html; charset=utf-8"); self.end_headers()
        self.wfile.write((ROOT / "worker/tableau.html").read_bytes())
    def log_message(self, *a): pass

http.server.ThreadingHTTPServer(("127.0.0.1", int(os.environ.get("PORT", 8787))), H).serve_forever()
