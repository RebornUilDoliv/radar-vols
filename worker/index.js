const RADAR_REPOSITORY = "RebornUilDoliv/radar-vols";
// Serveur de test Radar Flight : il garde le jeton Duffel hors du navigateur.
const DUFFEL = "https://api.duffel.com";
const IATA = /^[A-Z]{3}$/;
const DAY = /^\d{4}-\d{2}-\d{2}$/;
const TITLES = new Set(["mr", "ms", "mrs", "miss", "dr"]);
const SEARCH_LIMIT = 20;
const visits = new Map();

function respond(body, status, origin) {
  return new Response(status === 204 ? null : JSON.stringify(body), {
    status,
    headers: {
      "Content-Type": "application/json",
      "Access-Control-Allow-Origin": origin,
      "Access-Control-Allow-Methods": "POST, OPTIONS",
      "Access-Control-Allow-Headers": "Content-Type",
      "Vary": "Origin",
    },
  });
}

function tooManySearches(request) {
  const visitor = request.headers.get("CF-Connecting-IP") || "unknown";
  const minute = Math.floor(Date.now() / 60000);
  const seen = visits.get(visitor);
  const count = seen?.minute === minute ? seen.count + 1 : 1;
  visits.set(visitor, { minute, count });
  if (visits.size > 5000) visits.clear();
  return count > SEARCH_LIMIT;
}

async function duffel(path, token, options = {}, allowLive = false) {
  const response = await fetch(`${DUFFEL}${path}`, {
    ...options,
    headers: {
      "Accept": "application/json",
      "Accept-Encoding": "gzip",
      "Content-Type": "application/json",
      "Duffel-Version": "v2",
      "Authorization": `Bearer ${token}`,
    },
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    const error = new Error("duffel");
    error.detail = { status: response.status, code: payload.errors?.[0]?.code, title: payload.errors?.[0]?.title };
    throw error;
  }
  if (payload.data?.live_mode === true && !allowLive) throw new Error("live_mode");
  return payload.data;
}

function simplifyAirport(airport) {
  return { code: airport.iata_code, name: airport.name, city: airport.city_name };
}

function simplifySegment(segment) {
  const carrier = segment.marketing_carrier || segment.operating_carrier || {};
  return {
    from: simplifyAirport(segment.origin),
    to: simplifyAirport(segment.destination),
    departing: segment.departing_at,
    arriving: segment.arriving_at,
    duration: segment.duration,
    carrier: carrier.name,
    flight: `${carrier.iata_code || ""}${segment.marketing_carrier_flight_number || ""}`,
  };
}

function simplifySlice(slice) {
  const first = slice.segments[0];
  const last = slice.segments[slice.segments.length - 1];
  return {
    from: slice.origin.iata_code,
    to: slice.destination.iata_code,
    departing: first.departing_at,
    arriving: last.arriving_at,
    stops: slice.segments.length - 1,
    duration: slice.duration,
    segments: slice.segments.map(simplifySegment),
  };
}

function simplifyOffer(offer) {
  return {
    id: offer.id,
    amount: offer.total_amount,
    currency: offer.total_currency,
    airline: offer.owner?.name || "Compagnie",
    slices: offer.slices.map(simplifySlice),
    passengers: offer.passengers.map((p) => p.id),
  };
}

function validSearch(body) {
  const adults = Number(body.adults);
  return IATA.test(body.from) && IATA.test(body.to) && body.from !== body.to &&
    DAY.test(body.depart) && (!body.back || DAY.test(body.back)) &&
    Number.isInteger(adults) && adults >= 1 && adults <= 6;
}

function validPassenger(p) {
  return p && typeof p.given_name === "string" && p.given_name.trim() &&
    typeof p.family_name === "string" && p.family_name.trim() &&
    DAY.test(p.born_on || "") && TITLES.has(p.title) && ["m", "f"].includes(p.gender) &&
    /^[^@\s]+@[^@\s]+$/.test(p.email || "") && /^\+\d{6,15}$/.test(p.phone_number || "");
}

async function search(body, token, live) {
  const slices = [{ origin: body.from, destination: body.to, departure_date: body.depart }];
  if (body.back) slices.push({ origin: body.to, destination: body.from, departure_date: body.back });
  const data = await duffel("/air/offer_requests?return_offers=true", token, {
    method: "POST",
    body: JSON.stringify({
      data: {
        slices,
        passengers: Array.from({ length: Number(body.adults) }, () => ({ type: "adult" })),
        cabin_class: "economy",
      },
    }),
  }, live);
  const offers = [...(data.offers || [])]
    .sort((a, b) => Number(a.total_amount) - Number(b.total_amount))
    .slice(0, 10);
  return { offers: offers.map(simplifyOffer), live };
}

// Avec les vrais prix, la réservation est simulée : le jeton réel ne sert qu'à chercher.
function simulatedOrder() {
  const reference = crypto.randomUUID().replaceAll("-", "").slice(0, 6).toUpperCase();
  return { reference: `TEST-${reference}`, simulated: true };
}

async function order(body, token) {
  // Le prix vient toujours de Duffel, jamais du navigateur.
  const offer = await duffel(`/air/offers/${encodeURIComponent(body.offer)}`, token);
  const ids = offer.passengers.map((p) => p.id);
  const passengers = body.passengers.map((p, index) => ({
    id: ids[index],
    given_name: p.given_name.trim(),
    family_name: p.family_name.trim(),
    born_on: p.born_on,
    title: p.title,
    gender: p.gender,
    email: p.email,
    phone_number: p.phone_number,
  }));
  const created = await duffel("/air/orders", token, {
    method: "POST",
    body: JSON.stringify({
      data: {
        type: "instant",
        selected_offers: [offer.id],
        passengers,
        payments: [{ type: "balance", currency: offer.total_currency, amount: offer.total_amount }],
      },
    }),
  });
  return {
    reference: created.booking_reference,
    airline: created.owner?.name || offer.owner?.name,
    amount: created.total_amount,
    currency: created.total_currency,
  };
}

async function startRadar(token) {
  if (!token) throw new Error("secret GITHUB_DISPATCH_TOKEN manquant");
  const response = await fetch(`https://api.github.com/repos/${RADAR_REPOSITORY}/actions/workflows/radar.yml/dispatches`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${token}`,
      Accept: "application/vnd.github+json",
      "Content-Type": "application/json",
      "User-Agent": "eunodia-radar",
      "X-GitHub-Api-Version": "2022-11-28",
    },
    body: JSON.stringify({ ref: "main", inputs: { auto: "true" } }),
  });
  if (!response.ok) throw new Error(`GitHub a refusé le lancement du radar (${response.status})`);
}

// Détection discrète des robots : le site envoie un signal à l'ouverture de la page, puis un second au premier geste réel
// (toucher, défilement, souris, clavier). Aucun cookie, aucune adresse IP gardée ; les lignes sont effacées après 30 jours.
const VISIT_ID = /^[a-z0-9]{8,20}$/;
const short = (value, max) => String(value ?? "").slice(0, max);
const number = (value, max) => Math.max(0, Math.min(max, Math.round(Number(value) || 0)));

let tableChecked = false;
async function ensureTable(db) {
  if (tableChecked) return;
  await db.batch([
    db.prepare("CREATE TABLE IF NOT EXISTS visites (id TEXT PRIMARY KEY, ts INTEGER, path TEXT, lang TEXT, country TEXT, asn INTEGER, org TEXT, ua TEXT, wd INTEGER DEFAULT 0, sw INTEGER, sh INTEGER, touch INTEGER, tz TEXT, ref TEXT, human INTEGER DEFAULT 0, gesture TEXT, ms INTEGER DEFAULT 0)"),
    db.prepare("CREATE INDEX IF NOT EXISTS visites_ts ON visites (ts)"),
  ]);
  tableChecked = true;
}

async function recordVisit(body, request, env) {
  if (!env.DB) throw new Error("base DB absente");
  let data;
  try {
    data = JSON.parse(body.slice(0, 2000));
  } catch {
    throw new Error("signal illisible");
  }
  if (!VISIT_ID.test(data.id || "")) throw new Error("identifiant invalide");
  await ensureTable(env.DB);
  if (data.e === "load") {
    const cf = request.cf || {};
    await env.DB.prepare(
      "INSERT OR IGNORE INTO visites (id, ts, path, lang, country, asn, org, ua, wd, sw, sh, touch, tz, ref) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)"
    ).bind(
      data.id, Date.now(), short(data.p, 200), short(data.l, 8), short(cf.country, 2), number(cf.asn, 1e7),
      short(cf.asOrganization, 80), short(request.headers.get("User-Agent"), 300), data.wd ? 1 : 0,
      number(data.sw, 20000), number(data.sh, 20000), data.t ? 1 : 0, short(data.tz, 40), short(data.r, 120)
    ).run();
  } else if (data.e === "human") {
    await env.DB.prepare("UPDATE visites SET human = 1, gesture = ?, ms = ? WHERE id = ?")
      .bind(short(data.g, 12), number(data.ms, 36e5), data.id).run();
  } else if (data.e === "leave") {
    await env.DB.prepare("UPDATE visites SET ms = MAX(ms, ?) WHERE id = ?").bind(number(data.ms, 36e5), data.id).run();
  }
}

// Tableau des visites (façon Web Analytics) : /tableau affiche la page, /stats donne les visites à qui a la clé STATS_KEY.
// TABLEAU-DEBUT (généré par outils/inline_tableau.py depuis worker/tableau.html, ne pas modifier à la main)
const DASHBOARD_HTML = "<!doctype html>\n<html lang=\"fr\">\n<head>\n<meta charset=\"utf-8\">\n<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n<meta name=\"robots\" content=\"noindex\">\n<title>eunodia · visites</title>\n<style>\n:root{--bg:#f2f2f2;--card:#fff;--line:#e3e3e3;--txt:#1d1d1d;--mut:#6b6b6b;--blue:#0051c3;--blue2:#d6e4fa;--red:#c4362b;--green:#1e7b34}\n@media (prefers-color-scheme:dark){:root{--bg:#141414;--card:#1e1e1e;--line:#333;--txt:#eee;--mut:#9a9a9a;--blue:#6ea8ff;--blue2:#21324d;--red:#ff7a6e;--green:#5fd07a}}\n*{box-sizing:border-box}\nbody{margin:0;background:var(--bg);color:var(--txt);font:14px/1.45 -apple-system,BlinkMacSystemFont,\"Segoe UI\",Roboto,sans-serif}\nheader{background:var(--card);border-bottom:1px solid var(--line);padding:14px 20px;display:flex;align-items:center;gap:10px}\nheader b{font-size:16px}\nheader span{color:var(--mut)}\nmain{max-width:1180px;margin:0 auto;padding:20px 16px 40px}\nh1{font-size:22px;font-weight:600;margin:0 0 14px}\n.bar{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin-bottom:16px}\n.chip{border:1px solid var(--line);background:var(--card);border-radius:6px;padding:6px 10px;color:var(--txt)}\nselect,button{font:inherit;color:var(--txt);background:var(--card);border:1px solid var(--line);border-radius:6px;padding:6px 10px;cursor:pointer}\nbutton.on{background:var(--blue);border-color:var(--blue);color:#fff}\n.card{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:16px 18px;margin-bottom:16px}\n.card h2{font-size:15px;font-weight:600;margin:0 0 4px}\n.card p.sub{color:var(--mut);margin:0 0 12px;font-size:13px}\n.kpis{display:flex;gap:28px;flex-wrap:wrap;margin-bottom:10px}\n.kpi small{display:block;color:var(--mut)}\n.kpi strong{font-size:26px;font-weight:600}\n.kpi em{font-style:normal;font-size:12px;margin-left:6px}\n.up{color:var(--green)}.down{color:var(--red)}\nsvg{display:block;width:100%;height:auto}\n.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,340px),1fr));gap:16px}\n.grid .card{margin:0}\n.row{position:relative;display:flex;justify-content:space-between;gap:10px;padding:6px 8px;margin:2px 0;border-radius:4px;overflow:hidden}\n.row i{position:absolute;inset:0 auto 0 0;background:var(--blue2);z-index:0}\n.row span,.row b{position:relative;z-index:1;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}\n.row b{font-weight:600}\n.empty{color:var(--mut);padding:8px}\n.tabs{display:flex;gap:4px;flex-wrap:wrap;margin-bottom:8px}\n.tabs button{padding:4px 9px;font-size:13px}\n#login{max-width:380px;margin:60px auto}\n#login input{width:100%;font:inherit;padding:8px 10px;border:1px solid var(--line);border-radius:6px;margin:10px 0;background:var(--card);color:var(--txt)}\n.err{color:var(--red)}\n.note{color:var(--mut);font-size:12px}\n</style>\n</head>\n<body>\n<header><svg viewBox=\"0 0 32 32\" width=\"26\" height=\"26\" style=\"width:26px\"><circle cx=\"16\" cy=\"16\" r=\"12.5\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"2.4\"/><path d=\"M9.5 18a6.5 6.5 0 0 1 13 0z\" fill=\"currentColor\"/><rect x=\"6.5\" y=\"19\" width=\"19\" height=\"1.8\" rx=\".9\" fill=\"currentColor\"/><rect x=\"10\" y=\"22.3\" width=\"12\" height=\"1.5\" rx=\".75\" fill=\"currentColor\"/></svg><b>eunodia</b><span>· Visites humaines et robots</span></header>\n<main>\n<div id=\"login\" class=\"card\" hidden>\n  <h2>Accès au tableau</h2>\n  <p class=\"sub\">Entre la clé que tu as enregistrée dans Cloudflare (STATS_KEY). Elle reste sur cet appareil.</p>\n  <form id=\"f\"><input id=\"k\" type=\"password\" autocomplete=\"current-password\" placeholder=\"Clé du tableau\"><button class=\"on\" type=\"submit\">Ouvrir</button></form>\n  <p id=\"lerr\" class=\"err\"></p>\n</div>\n<div id=\"app\" hidden>\n  <h1>Web Analytics pour eunodia.com</h1>\n  <div class=\"bar\">\n    <span class=\"chip\">Site : eunodia.com</span>\n    <span>Visiteurs :</span>\n    <button data-m=\"humains\" class=\"on\">Humains</button><button data-m=\"robots\">Robots</button><button data-m=\"tout\">Tout</button>\n    <select id=\"j\"><option value=\"1\">Dernières 24 heures</option><option value=\"7\">7 derniers jours</option><option value=\"30\">30 derniers jours</option></select>\n    <button id=\"r\" title=\"Actualiser\">↻</button>\n  </div>\n  <div class=\"card\">\n    <h2>Résumé des visites</h2>\n    <p class=\"sub\">Une visite commence quand quelqu'un arrive sur le site depuis l'extérieur. Une visite peut contenir plusieurs pages vues.</p>\n    <div class=\"kpis\" id=\"kpis\"></div>\n    <div id=\"chart\"></div>\n  </div>\n  <div class=\"grid\">\n    <div class=\"card\"><h2>Visites par pays</h2><div id=\"p-pays\"></div></div>\n    <div class=\"card\"><h2>Visites par source</h2><div class=\"tabs\" data-for=\"src\"></div><div id=\"p-src\"></div></div>\n    <div class=\"card\"><h2>Appareils et logiciels</h2><div class=\"tabs\" data-for=\"dev\"></div><div id=\"p-dev\"></div></div>\n    <div class=\"card\"><h2>Réseaux d'origine</h2><p class=\"sub\">Opérateur ou hébergeur d'où vient la visite. Un hébergeur (cloud) trahit souvent un robot.</p><div id=\"p-org\"></div></div>\n  </div>\n  <p class=\"note\" id=\"foot\"></p>\n</div>\n</main>\n<script>\n(function () {\n  var KEY = \"eunodia-tableau-cle\", mode = \"humains\", data = null;\n  var tabs = { src: [[\"Sources\", \"ref\"], [\"Pages\", \"path\"], [\"Pages d'entrée\", \"entry\"]], dev: [[\"Navigateurs\", \"browser\"], [\"Systèmes\", \"os\"], [\"Types d'appareil\", \"device\"]] };\n  var cur = { src: \"ref\", dev: \"browser\" };\n  var names = (function () { try { return new Intl.DisplayNames([\"fr\"], { type: \"region\" }); } catch (e) { return null; } })();\n  function $(id) { return document.getElementById(id); }\n  function esc(s) { return String(s).replace(/[&<>\"]/g, function (c) { return { \"&\": \"&amp;\", \"<\": \"&lt;\", \">\": \"&gt;\", '\"': \"&quot;\" }[c]; }); }\n  function getKey() { try { return localStorage.getItem(KEY) || \"\"; } catch (e) { return \"\"; } }\n  function setKey(v) { try { v ? localStorage.setItem(KEY, v) : localStorage.removeItem(KEY); } catch (e) {} }\n\n  function browser(ua) {\n    if (/bot|crawl|spider|headless/i.test(ua)) return \"Robot déclaré\";\n    if (/Instagram/i.test(ua)) return \"Instagram (appli)\";\n    if (/musical_ly|BytedanceWebview|TikTok/i.test(ua)) return \"TikTok (appli)\";\n    if (/FBAN|FBAV|FB_IAB/i.test(ua)) return \"Facebook (appli)\";\n    if (/Edg\\//.test(ua)) return \"Edge\";\n    if (/OPR\\/|Opera/.test(ua)) return \"Opera\";\n    if (/SamsungBrowser/.test(ua)) return \"Samsung Internet\";\n    if (/Firefox|FxiOS/.test(ua)) return \"Firefox\";\n    if (/CriOS|Chrome\\//.test(ua)) return /Mobile/.test(ua) ? \"Chrome Mobile\" : \"Chrome\";\n    if (/Safari\\//.test(ua) && /Version\\//.test(ua)) return /Mobile/.test(ua) ? \"Safari Mobile\" : \"Safari\";\n    return \"Inconnu\";\n  }\n  function os(ua) {\n    if (/iPhone|iPad|iPod/.test(ua)) return \"iOS\";\n    if (/Android/.test(ua)) return \"Android\";\n    if (/Windows/.test(ua)) return \"Windows\";\n    if (/Mac OS X|Macintosh/.test(ua)) return \"macOS\";\n    if (/CrOS/.test(ua)) return \"ChromeOS\";\n    if (/Linux/.test(ua)) return \"Linux\";\n    return \"Inconnu\";\n  }\n  function device(r) { return r.touch ? (r.sw && r.sw < 900 ? \"Mobile\" : \"Tablette\") : \"Ordinateur\"; }\n  function isHuman(r) { return r.human === 1 && r.wd !== 1; }\n  function internal(r) { return /(^|\\.)eunodia\\.com$/.test(r.ref || \"\"); }\n  function keep(r) { return mode === \"tout\" || (mode === \"humains\" ? isHuman(r) : !isHuman(r)); }\n\n  function load() {\n    var k = getKey();\n    if (!k) { $(\"login\").hidden = false; $(\"app\").hidden = true; return; }\n    $(\"foot\").textContent = \"Chargement…\";\n    fetch(\"/stats?jours=\" + $(\"j\").value, { headers: { Authorization: \"Bearer \" + k }, cache: \"no-store\" })\n      .then(function (res) { return res.json().then(function (b) { return { ok: res.ok, status: res.status, b: b }; }); })\n      .then(function (x) {\n        if (x.status === 401) { setKey(\"\"); $(\"lerr\").textContent = \"Clé incorrecte.\"; $(\"login\").hidden = false; $(\"app\").hidden = true; return; }\n        if (!x.ok) throw new Error(x.b.error || \"erreur\");\n        data = x.b; $(\"login\").hidden = true; $(\"app\").hidden = false; render();\n      })\n      .catch(function (e) { $(\"foot\").textContent = \"Impossible de charger les données (\" + e.message + \").\"; $(\"app\").hidden = false; });\n  }\n\n  function count(rows, fn) {\n    var m = {};\n    rows.forEach(function (r) { var k = fn(r) || \"Inconnu\"; m[k] = (m[k] || 0) + 1; });\n    return Object.keys(m).map(function (k) { return [k, m[k]]; }).sort(function (a, b) { return b[1] - a[1]; });\n  }\n  function list(id, items, label) {\n    var el = $(id), max = items.length ? items[0][1] : 0;\n    if (!items.length) { el.innerHTML = '<div class=\"empty\">Aucune donnée pour cette période.</div>'; return; }\n    el.innerHTML = items.slice(0, 10).map(function (it) {\n      return '<div class=\"row\"><i style=\"width:' + Math.max(2, Math.round(it[1] / max * 100)) + '%\"></i><span>' + esc(label ? label(it[0]) : it[0]) + \"</span><b>\" + it[1] + \"</b></div>\";\n    }).join(\"\");\n  }\n  function pct(a, b) {\n    if (!b) return \"\";\n    var p = Math.round((a - b) / b * 100);\n    return '<em class=\"' + (p >= 0 ? \"up\" : \"down\") + '\">' + (p >= 0 ? \"▲ \" : \"▼ \") + Math.abs(p) + \" %</em>\";\n  }\n  function chart(rows, days, now) {\n    var n = days === 1 ? 24 : days, step = days === 1 ? 36e5 : 864e5, start = now - n * step, b = [];\n    for (var i = 0; i < n; i++) b.push(0);\n    rows.forEach(function (r) { var i = Math.floor((r.ts - start) / step); if (i >= 0 && i < n && !internal(r)) b[i]++; });\n    var max = Math.max(1, Math.max.apply(null, b)), W = Math.max(300, $(\"chart\").clientWidth || 1000), H = 220, L = 34, B = 26, w = (W - L) / n, out = \"\";\n    var steps = Math.min(4, max);\n    for (var g = 0; g <= steps; g++) {\n      var y = 10 + (H - B - 10) * (1 - g / steps), v = Math.round(max * g / steps);\n      out += '<line x1=\"' + L + '\" x2=\"' + W + '\" y1=\"' + y + '\" y2=\"' + y + '\" stroke=\"var(--line)\"/><text x=\"' + (L - 6) + '\" y=\"' + (y + 4) + '\" text-anchor=\"end\" font-size=\"11\" fill=\"var(--mut)\">' + v + \"</text>\";\n    }\n    var tf = new Intl.DateTimeFormat(\"fr-FR\", days === 1 ? { hour: \"2-digit\", minute: \"2-digit\", timeZone: \"Europe/Paris\" } : { day: \"numeric\", month: \"short\", timeZone: \"Europe/Paris\" });\n    b.forEach(function (v, i) {\n      var h = (H - B - 10) * v / max, x = L + i * w;\n      out += '<rect x=\"' + (x + w * 0.15) + '\" y=\"' + (H - B - h) + '\" width=\"' + (w * 0.7) + '\" height=\"' + h + '\" rx=\"2\" fill=\"var(--blue)\"><title>' + tf.format(new Date(start + i * step)) + \" : \" + v + \" visite\" + (v > 1 ? \"s\" : \"\") + \"</title></rect>\";\n      if (i % Math.ceil(n / (W < 600 ? 4 : 8)) === 0) out += '<text x=\"' + (x + w / 2) + '\" y=\"' + (H - 8) + '\" text-anchor=\"middle\" font-size=\"11\" fill=\"var(--mut)\">' + tf.format(new Date(start + i * step)) + \"</text>\";\n    });\n    $(\"chart\").innerHTML = '<svg viewBox=\"0 0 ' + W + \" \" + H + '\" role=\"img\" aria-label=\"Visites dans le temps\">' + out + \"</svg>\";\n  }\n  function render() {\n    var days = data.jours, now = data.maintenant, cut = now - days * 864e5;\n    var all = data.visites.filter(keep), rows = all.filter(function (r) { return r.ts >= cut; }), prev = all.filter(function (r) { return r.ts < cut; });\n    var visits = rows.filter(function (r) { return !internal(r); }), pvisits = prev.filter(function (r) { return !internal(r); });\n    var total = data.visites.filter(function (r) { return r.ts >= cut; }), humans = total.filter(isHuman).length;\n    $(\"kpis\").innerHTML =\n      '<div class=\"kpi\"><small>Visites</small><strong>' + visits.length + \"</strong>\" + pct(visits.length, pvisits.length) + \"</div>\" +\n      '<div class=\"kpi\"><small>Pages vues</small><strong>' + rows.length + \"</strong>\" + pct(rows.length, prev.length) + \"</div>\" +\n      '<div class=\"kpi\"><small>Humains / robots (pages vues)</small><strong>' + humans + \" / \" + (total.length - humans) + \"</strong></div>\";\n    chart(rows, days, now);\n    list(\"p-pays\", count(visits, function (r) { return r.country; }), function (c) { return names && /^[A-Z]{2}$/.test(c) ? names.of(c) : c; });\n    var src = cur.src === \"ref\" ? count(visits, function (r) { return r.ref || \"Aucune (direct)\"; })\n      : cur.src === \"entry\" ? count(visits, function (r) { return r.path; }) : count(rows, function (r) { return r.path; });\n    list(\"p-src\", src);\n    list(\"p-dev\", count(visits, function (r) { return cur.dev === \"browser\" ? browser(r.ua || \"\") : cur.dev === \"os\" ? os(r.ua || \"\") : device(r); }));\n    list(\"p-org\", count(visits, function (r) { return r.org; }));\n    $(\"foot\").textContent = \"Mis à jour à \" + new Date(now).toLocaleTimeString(\"fr-FR\", { timeZone: \"Europe/Paris\" }) +\n      \". Humain = un vrai geste (toucher, souris, clavier) et un navigateur non automatisé. Les robots qui n'exécutent aucun script n'apparaissent pas ici.\";\n    Object.keys(tabs).forEach(function (t) {\n      document.querySelector('[data-for=\"' + t + '\"]').innerHTML = tabs[t].map(function (x) { return '<button data-t=\"' + t + '\" data-v=\"' + x[1] + '\"' + (cur[t] === x[1] ? ' class=\"on\"' : \"\") + \">\" + x[0] + \"</button>\"; }).join(\"\");\n    });\n  }\n  document.addEventListener(\"click\", function (e) {\n    var b = e.target.closest(\"button\"); if (!b) return;\n    if (b.dataset.m) { mode = b.dataset.m; document.querySelectorAll(\"[data-m]\").forEach(function (x) { x.classList.toggle(\"on\", x === b); }); if (data) render(); }\n    if (b.dataset.t) { cur[b.dataset.t] = b.dataset.v; if (data) render(); }\n    if (b.id === \"r\") load();\n  });\n  $(\"j\").addEventListener(\"change\", load);\n  var resized; addEventListener(\"resize\", function () { clearTimeout(resized); resized = setTimeout(function () { if (data) render(); }, 200); });\n  $(\"f\").addEventListener(\"submit\", function (e) { e.preventDefault(); var v = $(\"k\").value.trim(); if (!v) { $(\"lerr\").textContent = \"Entre la clé d'abord.\"; return; } $(\"lerr\").textContent = \"\"; setKey(v); load(); });\n  load();\n})();\n</script>\n</body>\n</html>\n";
// TABLEAU-FIN

async function sameSecret(a, b) {
  const hash = async (text) => new Uint8Array(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text)));
  const [x, y] = await Promise.all([hash(a), hash(b)]);
  let diff = 0;
  for (let i = 0; i < x.length; i++) diff |= x[i] ^ y[i];
  return diff === 0;
}

async function stats(request, env, url) {
  const reply = (body, status) => new Response(JSON.stringify(body), {
    status, headers: { "Content-Type": "application/json", "Cache-Control": "no-store", "X-Robots-Tag": "noindex" },
  });
  const key = env.STATS_KEY || "";
  if (key.length < 8) return reply({ error: "clé STATS_KEY non configurée dans Cloudflare" }, 503);
  const given = (request.headers.get("Authorization") || "").replace(/^Bearer\s+/i, "");
  if (!given || !(await sameSecret(given, key))) return reply({ error: "clé incorrecte" }, 401);
  if (!env.DB) return reply({ error: "base DB absente" }, 503);
  await ensureTable(env.DB);
  const days = { 1: 1, 7: 7, 30: 30 }[url.searchParams.get("jours")] || 1;
  const now = Date.now();
  const { results } = await env.DB.prepare(
    "SELECT ts, path, country, org, ua, sw, touch, human, wd, ref FROM visites WHERE ts >= ? ORDER BY ts LIMIT 50000"
  ).bind(now - 2 * days * 864e5).all();
  return reply({ jours: days, maintenant: now, visites: results }, 200);
}

export default {
  async scheduled(event, env) {
    if (env.DB) {
      try {
        await ensureTable(env.DB);
        await env.DB.prepare("DELETE FROM visites WHERE ts < ?").bind(Date.now() - 30 * 864e5).run();
      } catch (error) {
        console.error("nettoyage des visites impossible :", error?.message || String(error));
      }
    }
    await startRadar(env.GITHUB_DISPATCH_TOKEN);
  },

  async fetch(request, env, ctx) {
    const origin = env.ALLOWED_ORIGIN || "";
    const url = new URL(request.url);
    if (request.method === "GET" && url.pathname === "/tableau") {
      return new Response(DASHBOARD_HTML, { headers: {
        "Content-Type": "text/html; charset=utf-8", "Cache-Control": "no-store", "X-Robots-Tag": "noindex",
        "Content-Security-Policy": "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'self'; img-src 'self' data:; form-action 'none'; frame-ancestors 'none'",
      } });
    }
    if (request.method === "GET" && url.pathname === "/stats") {
      try {
        return await stats(request, env, url);
      } catch (error) {
        console.error("tableau indisponible :", error?.message || String(error));
        return new Response(JSON.stringify({ error: "tableau indisponible" }), { status: 502, headers: { "Content-Type": "application/json" } });
      }
    }
    if (request.method === "POST" && url.pathname === "/v") {
      // Le signal est enregistré avant de répondre ; une erreur est notée dans les journaux sans jamais gêner le visiteur.
      if (request.headers.get("Origin") === origin) {
        try {
          await recordVisit(await request.text(), request, env);
        } catch (error) {
          console.error("visite non enregistrée :", error?.message || String(error));
        }
      }
      return new Response(null, { status: 204, headers: { "Access-Control-Allow-Origin": origin } });
    }
    if (request.method === "OPTIONS") return respond({}, 204, origin);
    if (request.method !== "POST") return respond({ error: "méthode refusée" }, 405, origin);
    if (request.headers.get("Origin") !== origin) return respond({ error: "origine refusée" }, 403, origin);
    const token = env.DUFFEL_TEST_TOKEN || "";
    if (!token.startsWith("duffel_test_")) return respond({ error: "jeton de test requis" }, 503, origin);
    const liveToken = env.DUFFEL_LIVE_SEARCH_TOKEN || "";
    if (liveToken && !liveToken.startsWith("duffel_live_")) return respond({ error: "jeton de recherche invalide" }, 503, origin);
    const path = new URL(request.url).pathname;
    let body;
    try {
      body = await request.json();
    } catch {
      return respond({ error: "demande invalide" }, 400, origin);
    }
    try {
      if (path === "/search") {
        if (!validSearch(body)) return respond({ error: "recherche invalide" }, 400, origin);
        if (tooManySearches(request)) return respond({ error: "trop de recherches" }, 429, origin);
        return respond(await search(body, liveToken || token, Boolean(liveToken)), 200, origin);
      }
      if (path === "/order") {
        const valid = typeof body.offer === "string" && Array.isArray(body.passengers) &&
          body.passengers.length >= 1 && body.passengers.length <= 6 && body.passengers.every(validPassenger);
        if (!valid) return respond({ error: "réservation invalide" }, 400, origin);
        if (liveToken) return respond(simulatedOrder(), 200, origin);
        return respond(await order(body, token), 200, origin);
      }
      return respond({ error: "introuvable" }, 404, origin);
    } catch (error) {
      return respond({ error: "service indisponible", detail: error.detail || error.message }, 502, origin);
    }
  },
};
