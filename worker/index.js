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
    db.prepare("CREATE TABLE IF NOT EXISTS reglages (nom TEXT PRIMARY KEY, valeur TEXT)"),
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

// Tableau des visites (façon Web Analytics) : /tableau affiche la page (lue sur GitHub), /stats donne les visites à qui a le mot de passe.
const DASHBOARD_URL = "https://raw.githubusercontent.com/RebornUilDoliv/radar-vols/main/worker/tableau.html";

async function dashboard() {
  const page = await fetch(DASHBOARD_URL, { cf: { cacheTtl: 300, cacheEverything: true } });
  if (!page.ok) return new Response("Tableau indisponible, réessaie dans une minute.", { status: 502 });
  return new Response(await page.text(), { headers: {
    "Content-Type": "text/html; charset=utf-8", "Cache-Control": "no-store", "X-Robots-Tag": "noindex",
    "Content-Security-Policy": "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'self'; img-src 'self' data:; form-action 'none'; frame-ancestors 'none'",
  } });
}

const sha256 = async (text) => [...new Uint8Array(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text)))]
  .map((x) => x.toString(16).padStart(2, "0")).join("");

async function sameSecret(a, b) {
  const [x, y] = await Promise.all([sha256(a), sha256(b)]);
  let diff = 0;
  for (let i = 0; i < x.length; i++) diff |= x.charCodeAt(i) ^ y.charCodeAt(i);
  return diff === 0;
}

// Mot de passe du tableau : la variable STATS_KEY si elle existe, sinon celui que le propriétaire crée sur la page (gardé haché dans la base).
async function checkPassword(env, given) {
  if ((env.STATS_KEY || "").length >= 8) return given ? (await sameSecret(given, env.STATS_KEY)) ? "ok" : "non" : "non";
  const row = await env.DB.prepare("SELECT valeur FROM reglages WHERE nom = 'cle_tableau'").first();
  if (!row) return "aucun";
  const [salt, hash] = String(row.valeur).split(":");
  return given && (await sameSecret(await sha256(salt + given), hash)) ? "ok" : "non";
}

async function stats(request, env, url) {
  const reply = (body, status) => new Response(JSON.stringify(body), {
    status, headers: { "Content-Type": "application/json", "Cache-Control": "no-store", "X-Robots-Tag": "noindex" },
  });
  if (!env.DB) return reply({ error: "base DB absente" }, 503);
  if (tooManySearches(request)) return reply({ error: "trop d'essais, attends une minute" }, 429);
  await ensureTable(env.DB);
  if (url.pathname === "/stats/cle") {
    if (request.method !== "POST" || request.headers.get("Origin") !== url.origin) return reply({ error: "demande refusée" }, 403);
    if ((env.STATS_KEY || "").length >= 8) return reply({ error: "mot de passe déjà défini" }, 409);
    const body = await request.json().catch(() => ({}));
    const key = typeof body.cle === "string" ? body.cle : "";
    if (key.length < 8 || key.length > 200) return reply({ error: "8 caractères minimum" }, 400);
    const salt = crypto.randomUUID();
    const saved = await env.DB.prepare("INSERT OR IGNORE INTO reglages (nom, valeur) VALUES ('cle_tableau', ?)")
      .bind(salt + ":" + (await sha256(salt + key))).run();
    if (!saved.meta.changes) return reply({ error: "mot de passe déjà défini" }, 409);
    return reply({ ok: true }, 200);
  }
  const given = (request.headers.get("Authorization") || "").replace(/^Bearer\s+/i, "");
  const check = await checkPassword(env, given);
  if (check === "aucun") return reply({ error: "aucun mot de passe", premiere: true }, 401);
  if (check !== "ok") return reply({ error: "mot de passe incorrect" }, 401);
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
    if (request.method === "GET" && url.pathname === "/tableau") return dashboard();
    if (url.pathname === "/stats" || url.pathname === "/stats/cle") {
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
