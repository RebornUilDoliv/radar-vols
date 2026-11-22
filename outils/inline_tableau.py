"""Copie worker/tableau.html dans worker/index.js (constante DASHBOARD_HTML), pour n'avoir qu'un fichier à coller dans Cloudflare.
Usage : python3 outils/inline_tableau.py  (depuis la racine du projet)"""
import json, re
html = open("worker/tableau.html", encoding="utf-8").read()
js = open("worker/index.js", encoding="utf-8").read()
line = "const DASHBOARD_HTML = " + json.dumps(html, ensure_ascii=False).replace("\u2028", "\\u2028").replace("\u2029", "\\u2029") + ";"
new, n = re.subn(r"(// TABLEAU-DEBUT[^\n]*\n).*?(\n// TABLEAU-FIN)", lambda m: m.group(1) + line + m.group(2), js, flags=re.S)
assert n == 1, "repères TABLEAU-DEBUT / TABLEAU-FIN introuvables"
open("worker/index.js", "w", encoding="utf-8").write(new)
print("tableau intégré :", len(html), "caractères")
