(function () {
  "use strict";
  var RF = window.RF;
  var ROOT = RF.root;
  var BASE = RF.base;
  var say = function (key, values) {
    return RF.t[key].replace(/\{(\w+)\}/g, function (_, name) { return values[name]; });
  };
  var PAGE = 40;
  var $ = function (id) { return document.getElementById(id); };
  var euro = function (n) { return Math.round(n).toLocaleString(RF.locale, { style: "currency", currency: "EUR", maximumFractionDigits: 0 }); };
  var dateOf = function (iso) { return new Date(iso + "T12:00:00Z"); };
  var fmt = function (iso, options) {
    return dateOf(iso).toLocaleDateString(RF.locale, Object.assign({ timeZone: "UTC" }, options));
  };
  var shortDate = function (iso) { return fmt(iso, { day: "numeric", month: "short", year: "numeric" }); };
  var days = function (o) { return Math.round((dateOf(o.back) - dateOf(o.depart)) / 864e5); };
  var stops = function (o) {
    if (o.stops === null || o.stops === undefined) return RF.t.stops_unknown;
    if (o.stops === 0) return RF.t.direct;
    return say(o.stops > 1 ? "stops" : "stop", { count: o.stops });
  };
  var el = function (tag, className, text) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  };
  var svg = function (tag, attrs, text) {
    var node = document.createElementNS("http://www.w3.org/2000/svg", tag);
    Object.keys(attrs).forEach(function (key) { node.setAttribute(key, attrs[key]); });
    if (text !== undefined) node.textContent = text;
    return node;
  };
  var partner = function (url) {
    return "https://tp.media/r?" + new URLSearchParams({
      marker: "800338", trs: "597805", p: "4114", campaign_id: "100", u: url
    }).toString();
  };

  /* Recherche mondiale */
  function initSearch() {
    var form = $("search");
    if (!form) return;
    var cities = null;
    var loading = null;
    var load = function () {
      loading = loading || fetch(BASE + "assets/cities-" + RF.lang + ".json").then(function (r) { return r.json(); })
        .then(function (rows) { cities = rows; }).catch(function () { loading = null; });
      return loading;
    };
    var clean = function (text) {
      return text.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase().trim();
    };
    function matches(term) {
      var wanted = clean(term);
      if (!wanted || !cities) return [];
      var starts = [], inside = [];
      cities.forEach(function (row) {
        var name = clean(row[1]);
        if (row[0].toLowerCase() === wanted || name.indexOf(wanted) === 0) starts.push(row);
        else if (name.indexOf(wanted) > 0 || clean(row[2]).indexOf(wanted) === 0) inside.push(row);
      });
      return starts.concat(inside).slice(0, 8);
    }
    ["from", "to"].forEach(function (id) {
      var input = $(id);
      var list = input.parentNode.querySelector(".suggest");
      var close = function () { list.hidden = true; list.textContent = ""; };
      var pick = function (row) {
        input.value = row[1] + " (" + row[0] + ")";
        input.dataset.code = row[0];
        close();
      };
      var show = function () {
        var found = matches(input.value);
        list.textContent = "";
        list.hidden = !found.length;
        found.forEach(function (row) {
          var option = el("button");
          option.type = "button";
          option.textContent = row[1] + " (" + row[0] + ")";
          if (row[2]) option.appendChild(el("small", "", " · " + row[2]));
          option.addEventListener("mousedown", function (event) { event.preventDefault(); pick(row); });
          option.addEventListener("click", function () { pick(row); });
          list.appendChild(option);
        });
      };
      input.addEventListener("focus", load);
      input.addEventListener("input", function () {
        delete input.dataset.code;
        load().then(show);
      });
      input.addEventListener("blur", function () { setTimeout(close, 120); });
      input.addEventListener("keydown", function (event) {
        if (event.key === "Escape") close();
        if (event.key === "Enter" && !list.hidden && list.firstChild) {
          event.preventDefault();
          list.firstChild.click();
        }
      });
    });
    var today = new Date().toISOString().slice(0, 10);
    $("out").min = today; $("back").min = today;
    $("out").addEventListener("change", function () {
      $("back").min = $("out").value;
      if ($("back").value && $("back").value < $("out").value) $("back").value = "";
    });
    form.addEventListener("submit", function (event) {
      event.preventDefault();
      var error = $("search-error");
      var from = $("from").dataset.code, to = $("to").dataset.code;
      var problem = !from ? RF.t.pick_from : !to ? RF.t.pick_to : from === to ? RF.t.same : "";
      error.textContent = problem;
      error.hidden = !problem;
      if (problem) return;
      var part = function (iso) { return iso.slice(8, 10) + iso.slice(5, 7); };
      var url = form.dataset.target + from + part($("out").value) + to +
        ($("back").value ? part($("back").value) : "") + $("pax").value;
      if (form.dataset.results) {
        location.href = form.dataset.results + "?" + new URLSearchParams({
          flightSearch: url.slice(form.dataset.target.length), locale: RF.lang, currency: form.dataset.currency || "EUR"
        }).toString();
        return;
      }
      location.href = partner(url);
    });
  }

  /* Moteur de vols intégré : mêmes formes et couleurs que le reste du site */
  var WL_STYLE = [
    '[class*="DefaultSearch-module__root"]{gap:10px!important}',
    '[class*="DefaultSearch-module__mergedInputs"],[class*="DateRangePicker-module__mergedInputs"]{gap:10px!important;background:transparent!important;border:0!important;box-shadow:none!important}',
    '[class*="Input-module__root"]{background:#f4f4f4!important;border:1px solid transparent!important;border-radius:12px!important;box-shadow:none!important}',
    '[class*="Input-module__root"]:hover{border-color:#e4e4e4!important}',
    '[class*="Input-module__button"],[class*="Input-module__button"] *{background:transparent!important}',
    '[class*="Input-module__input"]{font-family:"Geist",system-ui,sans-serif!important;font-size:16px!important;font-weight:500!important;color:#0b0b0b!important}',
    '[class*="Input-module__valueHint"]{color:#9a9a9a!important;font-size:13px!important;font-weight:500!important}',
    '[class*="Input-module__subvalue"]{color:#6a6a6a!important;font-size:13px!important}',
    '[class*="swapButton"]{background:#fff!important;border:1px solid #e4e4e4!important;border-radius:50%!important;z-index:2}',
    '[class*="cancelButton"]{opacity:.55}[class*="cancelButton"]:hover{opacity:1}',
    '[class*="cancelButton"] svg,[class*="swapButton"] svg,[class*="iconContainer"] svg{color:#0b0b0b!important}',
    '[class*="cancelButton"] svg [fill]:not([fill="none"]),[class*="swapButton"] svg [fill]:not([fill="none"]),[class*="iconContainer"] svg [fill]:not([fill="none"]){fill:#0b0b0b!important}',
    '[class*="DefaultSearch-module__submitBtn"]{display:flex!important;align-items:center!important;justify-content:center!important;line-height:1!important;min-height:46px!important;height:46px!important;padding:0 24px!important;border-radius:10px!important;background:#0b0b0b!important;font-family:"Clash Display","Geist",sans-serif!important;font-size:15px!important;font-weight:600!important;letter-spacing:.01em!important}',
    '[class*="DefaultSearch-module__submitBtn"]:hover{background:#333!important}',
    '[class*="LocalizationDropdown-module__btn"]{font-family:"Geist",sans-serif!important;font-size:13px!important;font-weight:600!important;color:#6a6a6a!important}',
    '[class*="SearchEdit-module__line"]{font-family:"Geist",sans-serif!important;font-size:14px!important;color:#6a6a6a!important}',
    '[class*="SearchEdit-module__referral"],[class*="SearchEdit-module__hotelsLabel"]{display:none!important}',
    '[class*="FlightCard-module__card___"]{border:1px solid #e4e4e4!important;border-radius:16px!important;box-shadow:none!important}',
    '[class*="cardLeftPrice"]{font-family:"Clash Display","Geist",sans-serif!important;font-weight:600!important;color:#0b0b0b!important}',
    '[class*="cardFlightTime"]{font-family:"Clash Display","Geist",sans-serif!important;font-weight:500!important;color:#0b0b0b!important}',
    '[class*="cardLeftButton"],[class*="Button-module__primary"]{background:#0b0b0b!important;border-radius:10px!important;font-family:"Clash Display","Geist",sans-serif!important;font-weight:600!important;font-size:15px!important}',
    '[class*="Button-module__primary"]:not([class*="cardLeftButton"]):not([class*="submitBtn"]){min-height:46px!important;height:46px!important;display:flex!important;align-items:center!important;justify-content:center!important}',
    '[class*="cardBadges"],[class*="cardBadges"] *{background:#0b0b0b!important;background-color:#0b0b0b!important;color:#fff!important;border-radius:999px!important}',
    '[class*="cancelButton"] svg *,[class*="iconContainer"] svg *{stroke:#0b0b0b!important}',
    '[class*="Button-module__secondary"]{border-radius:10px!important;border-color:#e4e4e4!important;color:#0b0b0b!important}',
    '[class*="FlightFiltersMobileMenu-module__chip"]{border-radius:999px!important}'
  ].join("");
  /* Textes que le moteur Travelpayouts laisse en anglais */
  var WL_WORDS = {
    fr: { "Show more options": "Voir plus d'options", "Show": "Afficher", "Show more": "Voir plus" },
    es: { "Show more options": "Ver más opciones", "Show": "Mostrar", "Show more": "Ver más" },
    de: { "Show more options": "Weitere Optionen", "Show": "Anzeigen", "Show more": "Mehr anzeigen" },
    it: { "Show more options": "Mostra altre opzioni", "Show": "Mostra", "Show more": "Mostra altro" },
    pt: { "Show more options": "Ver mais opções", "Show": "Mostrar", "Show more": "Ver mais" },
    nl: { "Show more options": "Meer opties", "Show": "Tonen", "Show more": "Meer tonen" },
    tr: { "Show more options": "Daha fazla seçenek", "Show": "Göster", "Show more": "Daha fazla" }
  };
  /* « 1 passagers » → « 1 passager », et traductions manquantes */
  function singular(root) {
    var words = WL_WORDS[RF.lang] || {};
    var fix = function (text) {
      var trimmed = text.trim();
      if (words[trimmed]) return text.replace(trimmed, words[trimmed]);
      return text.replace(/\b1 passagers\b/, "1 passager").replace(/\b1 passengers\b/, "1 passenger");
    };
    var walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    var node;
    while ((node = walker.nextNode())) {
      if (fix(node.nodeValue) !== node.nodeValue) node.nodeValue = fix(node.nodeValue);
    }
    Array.prototype.forEach.call(root.querySelectorAll("input"), function (input) {
      if (fix(input.value) !== input.value) input.value = fix(input.value);
    });
  }
  function initWhiteLabel() {
    var ids = ["tpwl-search", "tpwl-tickets", "tpwl-modals"];
    if (!$("tpwl-search")) return;
    /* La case « hôtels » du moteur ouvre Hotellook, fermé depuis 2025 : on la décoche. */
    document.cookie = "hide_hotels=true; max-age=31536000; path=/; SameSite=Lax";
    var tries = 0;
    var timer = setInterval(function () {
      tries += 1;
      ids.forEach(function (id) {
        var host = $(id);
        var root = host && host.shadowRoot;
        if (root && !root.getElementById("eu-style")) {
          var style = document.createElement("style");
          style.id = "eu-style";
          style.textContent = WL_STYLE;
          root.appendChild(style);
          singular(root);
          new MutationObserver(function () { singular(root); }).observe(root, { childList: true, subtree: true, characterData: true });
          setInterval(function () { singular(root); }, 400);
        }
      });
      if (tries > 100) clearInterval(timer);
    }, 300);
  }

  /* Recherche d'hôtels Klook (onglet à côté des vols) */
  function initHotels() {
    var form = $("hotel-search");
    if (!form) return;
    var trains = $("train-search");
    document.querySelectorAll(".search-tabs button").forEach(function (button) {
      button.addEventListener("click", function () {
        document.querySelectorAll(".search-tabs button").forEach(function (b) {
          b.classList.toggle("on", b === button);
          var panel = $(b.dataset.show);
          if (panel) panel.hidden = b !== button;
        });
        if (button.dataset.show === "train-search" && trains) loadTrains(trains);
      });
    });
    var cities = JSON.parse(form.dataset.cities || "[]");
    var input = $("h-city");
    var list = input.parentNode.querySelector(".suggest");
    var clean = function (text) { return text.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase().trim(); };
    var close = function () { list.hidden = true; list.textContent = ""; };
    var pick = function (row) { input.value = row[0]; input.dataset.id = row[1]; close(); $("hotel-error").hidden = true; };
    var show = function () {
      var wanted = clean(input.value);
      var found = wanted ? cities.filter(function (row) { return clean(row[0]).indexOf(wanted) === 0; })
        .concat(cities.filter(function (row) { return clean(row[0]).indexOf(wanted) > 0; })).slice(0, 8) : cities.slice(0, 8);
      list.textContent = "";
      list.hidden = !found.length;
      found.forEach(function (row) {
        var option = el("button");
        option.type = "button";
        option.textContent = row[0];
        option.addEventListener("mousedown", function (event) { event.preventDefault(); pick(row); });
        option.addEventListener("click", function () { pick(row); });
        list.appendChild(option);
      });
    };
    input.addEventListener("focus", show);
    input.addEventListener("input", function () { delete input.dataset.id; show(); });
    input.addEventListener("blur", function () { setTimeout(close, 120); });
    var today = new Date().toISOString().slice(0, 10);
    $("h-in").min = today; $("h-out").min = today;
    $("h-in").addEventListener("change", function () {
      $("h-out").min = $("h-in").value;
      if ($("h-out").value && $("h-out").value < $("h-in").value) $("h-out").value = "";
    });
    form.addEventListener("submit", function (event) {
      event.preventDefault();
      var id = input.dataset.id;
      if (!id) { $("hotel-error").hidden = false; return; }
      var params = { adult_num: $("h-guests").value, child_num: "0", room_num: "1" };
      if (id.charAt(0) === "p" || id.charAt(0) === "d") { params.stype = id.charAt(0) === "p" ? "province" : "district"; params.svalue = id.slice(1); params.city_id = ""; }
      else { params.city_id = id; params.stype = "city"; params.svalue = id; }
      if ($("h-in").value) params.check_in = $("h-in").value;
      if ($("h-out").value) params.check_out = $("h-out").value;
      var url = "https://www.klook.com/" + form.dataset.lang + "/hotels/searchresult/?" + new URLSearchParams(params).toString();
      var link = "https://tp.media/r?" + new URLSearchParams({ marker: "800338", trs: "597805", p: "4110", campaign_id: "137", u: url }).toString();
      window.open(link, "_blank", "noopener");
    });
  }

  /* Trains et bus Omio : trajets récupérés chaque jour (docs/omio/<langue>.json), recherche sur le site,
     réservation chez Omio via le lien de suivi Impact. Les données ne sont chargées qu'au premier clic sur l'onglet. */
  var trainState = null;
  function loadTrains(form) {
    if (trainState) return;
    var words = JSON.parse(form.dataset.words || "{}");
    var results = $("train-results") || el("div");
    trainState = { form: form, words: words, data: null };
    results.textContent = words.loading;
    fetch(form.dataset.src).then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); }).then(function (data) {
      results.textContent = "";
      trainState.data = prepareTrains(data);
      initTrainForm(form, words, trainState.data);
    }).catch(function () { results.textContent = ""; trainState = null; });
  }

  function prepareTrains(data) {
    var clean = function (text) { return text.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase().trim(); };
    var names = data.cities.map(function (c) { return c[1]; });
    var byOrigin = {}, priced = {};
    data.routes.forEach(function (r) {
      var o = names[r[0]];
      (byOrigin[o] = byOrigin[o] || []).push(r);
      if (r[2] || r[3]) priced[o] = (priced[o] || 0) + 1;
    });
    /* villes de départ triées par nombre de trajets avec prix (les plus utiles d'abord) */
    var origins = Object.keys(byOrigin).sort(function (a, b) { return (priced[b] || 0) - (priced[a] || 0) || byOrigin[b].length - byOrigin[a].length; });
    return { raw: data, names: names, byOrigin: byOrigin, origins: origins, clean: clean };
  }

  function trainLink(d, route) {
    var o = d.raw.cities[route[0]][0], t = d.raw.cities[route[1]][0], key = o + "_" + t;
    if (d.raw.links[key]) return d.raw.links[key];
    var b64 = btoa("connection_page_nt." + d.raw.site + "." + o + "." + t);
    if (!d.raw.pad) b64 = b64.replace(/=+$/, "");
    return d.raw.link.replace("{o}", o).replace("{d}", t).replace("{b64}", encodeURIComponent(b64));
  }

  function omioHome(d) {
    /* lien de suivi Impact vers l'accueil Omio (quand le trajet n'est pas dans le catalogue) */
    return d.raw.link.split("?")[0] + "?u=" + encodeURIComponent(d.raw.home || "https://www.omio.com/");
  }

  function suggestBox(input, source, onPick) {
    var list = input.parentNode.querySelector(".suggest");
    var close = function () { list.hidden = true; list.textContent = ""; };
    var show = function () {
      var clean = trainState.data.clean, wanted = clean(input.value), pool = source();
      var found = wanted ? pool.filter(function (n) { return clean(n).indexOf(wanted) === 0; })
        .concat(pool.filter(function (n) { return clean(n).indexOf(wanted) > 0; })).slice(0, 8) : pool.slice(0, 8);
      list.textContent = "";
      list.hidden = !found.length;
      found.forEach(function (name) {
        var option = el("button", null, name);
        option.type = "button";
        var choose = function () { input.value = name; input.dataset.picked = name; close(); onPick(name); };
        option.addEventListener("mousedown", function (event) { event.preventDefault(); choose(); });
        option.addEventListener("click", choose);
        list.appendChild(option);
      });
    };
    input.addEventListener("focus", show);
    input.addEventListener("input", function () { delete input.dataset.picked; show(); });
    input.addEventListener("blur", function () { setTimeout(close, 120); });
  }

  function initTrainForm(form, words, d) {
    var from = $("t-from"), to = $("t-to"), results = $("train-results") || el("div"), error = $("train-error");
    var lang = form.dataset.lang === "zh" ? "zh-CN" : form.dataset.lang;
    var money = function (value) {
      try { return new Intl.NumberFormat(lang, { style: "currency", currency: d.raw.currency, maximumFractionDigits: value < 100 ? 2 : 0 }).format(value); }
      catch (e) { return value + " " + d.raw.currency; }
    };
    /* photo du site pour la ville (« Lyon Part Dieu » -> photo de Lyon) quand Omio n'en fournit pas */
    var photos = JSON.parse(form.dataset.photos || "{}");
    var sitePhoto = function (name) {
      var words2 = name.toLowerCase().replace(/\(.*?\)/g, "").trim().split(/[\s-]+/);
      for (var n = words2.length; n > 0; n--) {
        var code = photos[words2.slice(0, n).join(" ")] || photos[words2.slice(0, n).join("-")];
        if (code) return form.dataset.photoRoot + code + "-m.jpg";
      }
      return "";
    };
    var today = new Date().toISOString().slice(0, 10);
    $("t-out").min = today; $("t-back").min = today;
    $("t-out").addEventListener("change", function () {
      $("t-back").min = $("t-out").value || today;
      if ($("t-back").value && $("t-back").value < $("t-out").value) $("t-back").value = "";
    });
    var exact = function (name) {
      /* accepte aussi une ville tapée sans passer par la liste, si elle existe telle quelle */
      var wanted = d.clean(name || "");
      return d.origins.filter(function (n) { return d.clean(n) === wanted; })[0];
    };
    suggestBox(from, function () { return d.origins; }, function () { error.hidden = true; });
    suggestBox(to, function () {
      var o = from.dataset.picked || exact(from.value);
      var routes = o ? d.byOrigin[o] || [] : [];
      var seen = {}, out = [];
      routes.forEach(function (r) { var n = d.names[r[1]]; if (!seen[n]) { seen[n] = 1; out.push(n); } });
      return out.sort(function (a, b) { return a.localeCompare(b); });
    }, function () {});
    var photoOf = function (route) {
      var photo = (d.raw.cities[route[1]] || [])[2];
      return photo ? (d.raw.images || "") + photo : sitePhoto(d.names[route[1]]);
    };
    /* trajets : [départ, arrivée, prix train, prix bus, minutes train, minutes bus, rang] */
    var best = function (r) { return Math.min(r[2] || 1e9, r[3] || 1e9); };
    var hours = function (m) { return m ? Math.floor(m / 60) + " h " + String(m % 60).padStart(2, "0") : ""; };
    var modeText = function (icon, price, minutes) {
      return price ? icon + " " + words.price_from + " " + money(price) + (minutes ? " · " + hours(minutes) : "") : "";
    };
    var priceText = function (route) { var b = best(route); return b < 1e9 ? words.price_from + " " + money(b) : ""; };
    /* ajoute les dates choisies à la page Omio (le trajet et les dates arrivent déjà remplis chez Omio) */
    var withDates = function (url) {
      var out = $("t-out").value, back = $("t-back").value;
      if (!out) return url;
      try {
        var link = new URL(url), target = new URL(link.searchParams.get("u"));
        target.searchParams.set("departure_date", out);
        if (back && back >= out) target.searchParams.set("return_date", back);
        link.searchParams.set("u", target.toString());
        return link.toString();
      } catch (e) { return url; }
    };
    /* Lien de redirection officiel Omio (suivi Impact) : ouvre directement la page de résultats Omio
       pour le départ, l'arrivée et les dates donnés (date d'aller obligatoire : demain par défaut). */
    var tomorrow = function () { var t = new Date(); t.setDate(t.getDate() + 1); return t.toISOString().slice(0, 10); };
    var searchLink = function (fromName, toName) {
      var out = $("t-out").value || tomorrow(), back = $("t-back").value;
      var params = new URLSearchParams({ departurePosTerm: fromName, arrivalPosTerm: toName, departureDate: out });
      if (back && back >= out) params.set("returnDate", back);
      if (form.dataset.omioLocale) params.set("locale", form.dataset.omioLocale);
      if (d.raw.currency) params.set("currency", d.raw.currency);
      return form.dataset.redirect + encodeURIComponent(form.dataset.omioLinks + "?" + params.toString());
    };
    var linkTo = function (item, route) {
      item.dataset.from = d.names[route[0]];
      item.dataset.to = d.names[route[1]];
      item.href = form.dataset.redirect ? searchLink(item.dataset.from, item.dataset.to) : withDates(trainLink(d, route));
      item.target = "_blank"; item.rel = "sponsored noopener";
      return item;
    };
    /* si les dates changent après la recherche, les liens affichés suivent */
    ["t-out", "t-back"].forEach(function (id) {
      $(id).addEventListener("change", function () {
        if (!form.dataset.redirect) return;
        results.querySelectorAll("a[data-to]").forEach(function (a) { a.href = searchLink(a.dataset.from, a.dataset.to); });
      });
    });
    var row = function (route) {
      /* ligne compacte pour les destinations sans photo */
      var item = linkTo(el("a", "train-row"), route);
      var place = el("span", "train-row-place");
      place.appendChild(el("strong", null, d.names[route[1]]));
      place.appendChild(el("span", null, d.names[route[0]]));
      item.appendChild(place);
      item.appendChild(el("span", "train-row-price", priceText(route)));
      var modes = [modeText("🚆", route[2], route[4]), modeText("🚌", route[3], route[5])].filter(Boolean).join("   ");
      if (modes) place.appendChild(el("span", "train-modes", modes));
      item.appendChild(el("span", "train-row-go", "↗"));
      return item;
    };
    var card = function (route) {
      /* carte photo comme les destinations du site : photo, destination en grand, départ et prix dessous */
      var item = linkTo(el("a", "card train-card"), route);
      var img = el("img");
      img.src = photoOf(route);
      img.alt = "";
      img.loading = "lazy";
      img.onerror = function () { img.remove(); };
      item.appendChild(img);
      item.appendChild(el("span", "train-chip", words.book + " ↗"));
      var label = el("span", "card-label");
      label.appendChild(el("strong", null, d.names[route[1]]));
      label.appendChild(el("span", null, d.names[route[0]]));
      [modeText("🚆", route[2], route[4]), modeText("🚌", route[3], route[5])].forEach(function (text) {
        if (text) label.appendChild(el("span", "train-mode", text));
      });
      item.appendChild(label);
      return item;
    };
    form.addEventListener("submit", function (event) {
      event.preventDefault();
      var fromName = from.value.trim(), toName = to.value.trim();
      var o = from.dataset.picked || exact(fromName);
      /* départ inconnu du catalogue : on accepte quand même s'il y a une arrivée (lien direct Omio) */
      if (!o && !(form.dataset.redirect && fromName && toName)) { error.hidden = false; return; }
      error.hidden = true;
      var target = d.clean(toName);
      /* « Paris » regroupe aussi les gares de la ville (Paris Gare de Lyon, Paris Gare du Nord…) */
      var all = [];
      if (o) d.origins.forEach(function (name) { if (name === o || name.indexOf(o + " ") === 0) all = all.concat(d.byOrigin[name]); });
      var routes = all.filter(function (r) { return !target || d.clean(d.names[r[1]]).indexOf(target) === 0; });
      /* trajets avec prix d'abord, du moins cher au plus cher, un seul par destination */
      /* seulement les trajets en train ou en bus ; destination choisie : du moins cher au plus cher,
         sinon les plus populaires d'abord (rang Omio) */
      routes = routes.filter(function (r) { return r[2] || r[3]; });
      routes.sort(target ? function (a, b) { return best(a) - best(b); }
                         : function (a, b) { return (a[6] || 1e9) - (b[6] || 1e9) || best(a) - best(b); });
      var shown = {};
      routes = routes.filter(function (r) { var key = d.names[r[1]]; if (shown[key]) return false; shown[key] = 1; return true; });
      results.textContent = "";
      routes = routes.slice(0, target ? 12 : 30);
      /* jusqu'à 8 grandes cartes photo, puis le reste en liste */
      var usedPhotos = {};
      var withPhoto = routes.filter(function (r) {
        var src = photoOf(r);
        if (!src || usedPhotos[src]) return false;
        usedPhotos[src] = 1;
        return true;
      }).slice(0, 8);
      var others = routes.filter(function (r) { return withPhoto.indexOf(r) < 0; });
      if (withPhoto.length) {
        var grid = el("div", "train-cards");
        withPhoto.forEach(function (r) { grid.appendChild(card(r)); });
        results.appendChild(grid);
      }
      if (others.length) {
        var list = el("div", "train-list");
        others.forEach(function (r) { list.appendChild(row(r)); });
        results.appendChild(list);
      }
      /* départ + arrivée : en tête, l'accès direct aux horaires et prix du jour chez Omio, pour les dates choisies */
      if (form.dataset.redirect && fromName && toName) {
        var cta = el("a", "train-cta");
        cta.dataset.from = fromName; cta.dataset.to = toName;
        cta.href = searchLink(fromName, toName); cta.target = "_blank"; cta.rel = "sponsored noopener";
        cta.appendChild(el("span", "train-cta-route", fromName + " → " + toName));
        cta.appendChild(el("span", "train-cta-go", words.book + " ↗"));
        results.insertBefore(cta, results.firstChild);
        return;
      }
      if (!routes.length) {
        results.appendChild(el("p", "train-none", words.none));
        var more = el("a", "train-more", words.more + " ↗");
        more.href = omioHome(d); more.target = "_blank"; more.rel = "sponsored noopener";
        results.appendChild(more);
      }
    });
  }

  /* Graphique du prix */
  function drawChart(box, points) {
    var W = Math.max(280, Math.round(box.clientWidth)), H = 170, left = 56, right = 12, top = 12, bottom = 26;
    var prices = points.map(function (p) { return p[1]; });
    var min = Math.min.apply(null, prices), max = Math.max.apply(null, prices);
    var pad = Math.max((max - min) * 0.15, 5), low = Math.max(0, min - pad), high = max + pad;
    var x = function (i) { return left + i * (W - left - right) / (points.length - 1); };
    var y = function (v) { return top + (high - v) * (H - top - bottom) / (high - low); };
    var label = function (i) { return fmt(points[i][0], { day: "numeric", month: "short" }); };
    var last = points.length - 1;
    var plot = svg("svg", {
      viewBox: "0 0 " + W + " " + H, role: "img",
      "aria-label": label(0) + " : " + euro(prices[0]) + " → " + label(last) + " : " + euro(prices[last])
    });
    [max, min].forEach(function (value) {
      plot.appendChild(svg("line", { class: "grid-line", x1: left, x2: W - right, y1: y(value), y2: y(value) }));
      plot.appendChild(svg("text", { class: "axis", x: left - 8, y: y(value) + 4, "text-anchor": "end" }, euro(value)));
    });
    plot.appendChild(svg("text", { class: "axis", x: left, y: H - 6 }, label(0)));
    plot.appendChild(svg("text", { class: "axis", x: W - right, y: H - 6, "text-anchor": "end" }, label(last)));
    plot.appendChild(svg("polyline", { class: "line", points: points.map(function (p, i) { return x(i) + "," + y(p[1]); }).join(" ") }));
    var cross = svg("line", { class: "cross", y1: top, y2: H - bottom, visibility: "hidden" });
    var dot = svg("circle", { class: "dot", r: 5, cx: x(last), cy: y(prices[last]) });
    plot.appendChild(cross); plot.appendChild(dot);
    box.appendChild(plot);
    var tip = el("div", "tip");
    tip.hidden = true;
    box.appendChild(tip);
    plot.addEventListener("pointermove", function (event) {
      var rect = plot.getBoundingClientRect();
      var ratio = (event.clientX - rect.left) / rect.width * W;
      var i = Math.min(last, Math.max(0, Math.round((ratio - left) * last / (W - left - right))));
      cross.setAttribute("x1", x(i)); cross.setAttribute("x2", x(i));
      cross.setAttribute("visibility", "visible");
      dot.setAttribute("cx", x(i)); dot.setAttribute("cy", y(prices[i]));
      tip.textContent = label(i) + " · " + euro(prices[i]);
      tip.hidden = false;
      var half = tip.offsetWidth / 2;
      tip.style.left = Math.min(rect.width - half, Math.max(half, x(i) / W * rect.width)) + "px";
    });
    plot.addEventListener("pointerleave", function () {
      tip.hidden = true;
      cross.setAttribute("visibility", "hidden");
      dot.setAttribute("cx", x(last)); dot.setAttribute("cy", y(prices[last]));
    });
  }

  function initCharts() {
    document.querySelectorAll("[data-history]").forEach(function (box) {
      try { drawChart(box, JSON.parse(box.dataset.history)); } catch (e) { box.remove(); }
    });
  }

    function flightCard(o) {
      var item = el("li", "row");
      var info = el("div", "row-info");
      var title = el("h3");
      var link = el("a", "", o.city);
      link.href = o.href || ROOT + "destinations/" + o.slug + "/";
      title.appendChild(link);
      info.appendChild(title);
      info.appendChild(el("p", "", fmt(o.depart, { day: "numeric", month: "short" }) + " → " + shortDate(o.back) + " · " + (days(o) === 1 ? RF.t.day_one : say("days", { count: days(o) })) + " · " + stops(o)));
      var cta = el("a", o.buy ? "go buy" : "go", o.buy ? RF.t.check : RF.t.see);
      cta.href = o.buy || o.href || link.href + "?mois=" + o.depart.slice(0, 7);
      if (o.external) { link.target = "_blank"; link.rel = "nofollow sponsored noopener"; }
      if (o.buy) { cta.target = "_blank"; cta.rel = "nofollow sponsored noopener"; }
      item.appendChild(info); item.appendChild(el("p", "row-price", euro(o.price))); item.appendChild(cta);
      return item;
    }

  /* Vols proches : la ville suit le fuseau horaire du visiteur, sans localisation */
  function initNearby() {
    var data = window.RFNEAR, soon = $("soon-list"), ahead = $("ahead-list");
    if (!data || !soon) return;
    var chosen = false;
    try { chosen = sessionStorage.getItem("eunodia-language") === RF.lang; } catch (error) {}
    if (chosen) return;
    var zone = "";
    try { zone = Intl.DateTimeFormat().resolvedOptions().timeZone || ""; } catch (error) {}
    var area = zone.split("/")[0], byZone = null, byArea = null, fallback = null;
    data.origins.forEach(function (o) {
      if (o[0] === data.default) fallback = o;
      if (o[2] === zone) byZone = byZone || o;
      if (RF.lang === "fr" && o[0] === "PAR" && area === "Europe") byArea = byArea || o;
      if (o[2] && o[2].split("/")[0] === area) byArea = byArea || o;
    });
    if (fallback && fallback[2] === zone) return; /* la ville par défaut est déjà dans le bon fuseau */
    var picked = byZone || (fallback && fallback[2] && fallback[2].split("/")[0] === area ? fallback : byArea) || fallback;
    if (!picked || picked[0] === data.default) return;
    fetch(BASE + "assets/routes/" + RF.lang + "/" + picked[0] + ".json")
      .then(function (r) { if (!r.ok) throw new Error(); return r.json(); })
      .then(function (rows) {
        var now = new Date();
        var pick = function (test) {
          var seen = {}, kept = [];
          rows.slice().sort(function (a, b) { return a.price - b.price; }).forEach(function (o) {
            var gap = (dateOf(o.depart) - now) / 864e5;
            if (test(gap) && !seen[o.city] && kept.length < 4) { seen[o.city] = 1; kept.push(o); }
          });
          return kept;
        };
        var fill = function (box, title, text, list) {
          if (!list.length) return;
          box.textContent = "";
          list.forEach(function (o) { box.appendChild(flightCard(o)); });
          title.textContent = text.replace("{city}", picked[1]);
        };
        fill(soon, $("soon-title"), data.titles[0], pick(function (g) { return g <= data.soon; }));
        fill(ahead, $("ahead-title"), data.titles[1], pick(function (g) { return g >= data.ahead; }));
      })
      .catch(function () {});
  }

  /* Liste filtrable */
  function initFlights() {
    if (!$("offers")) return;
    var all = [], current = [], shown = PAGE;
    var clean = function (text) { return text.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase(); };

    var card = flightCard;

    function filtered() {
      var q = clean($("q").value.trim()), region = $("region").value, month = $("month").value;
      var budget = Number($("budget").value), length = $("length").value.split("-").map(Number);
      var sort = $("sort").value;
      return all.filter(function (o) {
        return (!q || clean(o.city).indexOf(q) >= 0) && (!region || o.region === region) &&
          (!month || o.depart.slice(0, 7) === month) && (!budget || o.price <= budget) &&
          (length.length < 2 || (days(o) >= length[0] && days(o) <= length[1]));
      }).sort(function (a, b) {
        return sort === "depart" ? a.depart.localeCompare(b.depart) : a.price - b.price;
      });
    }

    function updateMore() {
      $("more").hidden = current.length <= shown;
      $("more").textContent = say("more", { shown: Math.min(shown, current.length), total: current.length });
    }

    function render() {
      current = filtered();
      shown = PAGE;
      var box = $("offers");
      box.textContent = "";
      if (!current.length) box.appendChild(el("li", "empty", RF.t.empty));
      current.slice(0, shown).forEach(function (o) { box.appendChild(card(o)); });
      $("count").textContent = say(current.length > 1 ? "count_many" : "count_one", { count: current.length });
      updateMore();
    }

    function showMore() {
      var added = current.slice(shown, shown + PAGE).map(card);
      added.forEach(function (item) { $("offers").appendChild(item); });
      shown += PAGE;
      updateMore();
      if (added.length) { added[0].tabIndex = -1; added[0].focus({ preventScroll: true }); }
    }

    function fill(select, values, label) {
      var keep = select.value;
      while (select.options.length > 1) select.remove(1);
      values.forEach(function (value) {
        var option = el("option", "", label ? label(value) : value);
        option.value = value;
        select.appendChild(option);
      });
      select.value = keep;
      if (select.selectedIndex < 0) select.selectedIndex = 0;
    }

    var query = new URLSearchParams(location.search), picked = false;
    function load() {
      var origin = $("origin");
      if (origin && query.get("origin")) origin.value = query.get("origin");
      if (origin && origin.selectedIndex < 0) origin.selectedIndex = 0;
      return fetch(origin ? BASE + "assets/routes/" + RF.lang + "/" + origin.value + ".json" : ROOT + "prices.json", { cache: "no-cache" })
      .then(function (r) { if (!r.ok) throw new Error(); return r.json(); })
      .then(function (data) {
        all = data.offers || data;
        var regions = {}, months = {};
        all.forEach(function (o) { regions[o.region] = 1; months[o.depart.slice(0, 7)] = 1; });
        fill($("region"), Object.keys(regions).sort(function (a, b) { return a.localeCompare(b, "fr"); }));
        fill($("month"), Object.keys(months).sort(), function (m) { return fmt(m + "-15", { month: "long", year: "numeric" }); });
        if (!picked) query.forEach(function (value, key) {
          if ($(key) && $(key).closest("#filters")) $(key).value = value;
        });
        picked = true;
        query = new URLSearchParams();
        render();
      })
      .catch(function () {
        $("offers").textContent = "";
        $("offers").appendChild(el("li", "empty", RF.t.soon));
      });
    }
    load();
    $("filters").addEventListener("input", function (event) {
      if (event.target.id === "origin") load(); else render();
    });
    $("filters").addEventListener("submit", function (event) { event.preventDefault(); });
    $("more").addEventListener("click", showMore);
  }

  function highlightMonth() {
    var month = new URLSearchParams(location.search).get("mois");
    var row = month && document.getElementById("m-" + month);
    if (row) row.classList.add("picked");
  }

  function initNewsletter() {
    var form = $("newsletter");
    if (!form) return;
    form.addEventListener("submit", function (event) {
      event.preventDefault();
      fetch(form.action, { method: "POST", mode: "no-cors", body: new FormData(form) })
        .then(function () {
          form.querySelector(".news-row").hidden = true;
          form.querySelector(".news-consent").hidden = true;
          $("news-done").textContent = RF.t.news_ok;
          $("news-done").hidden = false;
        })
        .catch(function () { form.submit(); });
    });
  }

  /* Une nouvelle photo chaque jour, sans dépendre d'un passage du serveur */
  function initMenu() {
    var button = $("menu-btn"), nav = document.querySelector(".nav");
    if (!button) return;
    button.addEventListener("click", function () {
      var open = nav.classList.toggle("open");
      button.setAttribute("aria-expanded", open ? "true" : "false");
    });
  }

  function initHeroVideo() {
    if (navigator.connection && navigator.connection.saveData) return;
    Array.prototype.forEach.call(document.querySelectorAll("[data-videos]"), function (hero) {
      if (hero.classList.contains("hero") || hero.classList.contains("page-hero") || !("IntersectionObserver" in window)) return startVideo(hero);
      var watch = new IntersectionObserver(function (entries) {
        if (!entries[0].isIntersecting) return;
        watch.disconnect();
        startVideo(hero);
      }, { rootMargin: "300px" });
      watch.observe(hero);
    });
  }

  function startVideo(hero) {
    var calm = matchMedia("(prefers-reduced-motion: reduce)").matches;
    var video = document.createElement("video");
    video.className = "hero-video";
    video.muted = true; video.loop = true; video.playsInline = true;
    video.setAttribute("muted", ""); video.setAttribute("playsinline", ""); video.setAttribute("aria-hidden", "true");
    var pause = el("button", "video-pause", "▶");
    pause.type = "button";
    pause.setAttribute("aria-label", "Play / pause");
    video.addEventListener("playing", function () { video.classList.add("on"); pause.textContent = "❚❚"; });
    video.addEventListener("pause", function () { pause.textContent = "▶"; });
    pause.addEventListener("click", function () {
      if (video.paused) { var again = video.play(); if (again && again.catch) again.catch(function () {}); } else { video.pause(); }
    });
    var bigScreen = screen.width * (window.devicePixelRatio || 1) >= 2400 && innerWidth >= 768;
    var names = hero.dataset.names.split(",");
    var name = names[Math.floor(Math.random() * names.length)];
    video.src = hero.dataset.videos + name + (bigScreen ? "-4k" : "") + ".mp4";
    hero.insertBefore(video, hero.querySelector(".hero-in, .page-hero-in, .trip-in"));
    hero.appendChild(pause);
    if (calm) return;
    var played = video.play();
    if (played && played.catch) played.catch(function () {});
  }

  function initLanguageMenu() {
    var menu = document.querySelector("details.langs");
    if (!menu) return;
    document.addEventListener("click", function (event) {
      if (!menu.contains(event.target)) menu.open = false;
    });
    menu.querySelectorAll(".langs-list a").forEach(function (link) {
      link.addEventListener("click", function () {
        try { sessionStorage.setItem("eunodia-language", link.lang); } catch (error) {}
      });
    });
  }

  function initMoreFilters() {
    var button = $("more-filters");
    if (!button) return;
    button.addEventListener("click", function () {
      $("filters").classList.add("all");
    });
  }

  /* Bons plans : regroupe les prix de la ville choisie par mois, région et budget */
  function initDeals() {
    var pick = $("deals-origin"), list = $("deals-list");
    if (!pick || !list) return;
    var text = JSON.parse(pick.getAttribute("data-text"));
    var wanted = new URLSearchParams(location.search).get("origin");
    if (wanted && Array.prototype.some.call(pick.options, function (o) { return o.value === wanted; })) pick.value = wanted;
    function block(title, items) {
      var section = el("section", "dest-group"), ul = el("ul", "links");
      section.appendChild(el("h2", "", title));
      items.forEach(function (item) {
        var li = el("li"), a = el("a");
        a.href = item.href;
        a.appendChild(el("span", "", item.label));
        a.appendChild(el("span", "", text.from.replace("{price}", euro(item.price)) + " · " + text.count.replace("{count}", item.count)));
        li.appendChild(a);
        ul.appendChild(li);
      });
      section.appendChild(ul);
      return section;
    }
    function show() {
      var code = pick.value, city = pick.options[pick.selectedIndex].text;
      fetch(BASE + "assets/routes/" + RF.lang + "/" + code + ".json")
        .then(function (r) { if (!r.ok) throw new Error(); return r.json(); })
        .then(function (rows) {
          if (!rows.length) return;
          var link = function (key, value) { return ROOT + "vols/?" + new URLSearchParams([["origin", code], [key, value]]).toString(); };
          var group = function (keyOf) {
            var found = {};
            rows.forEach(function (o) {
              var key = keyOf(o), seen = found[key] || (found[key] = { price: o.price, cities: {} });
              seen.price = Math.min(seen.price, o.price);
              seen.cities[o.city] = 1;
            });
            return found;
          };
          var months = group(function (o) { return o.depart.slice(0, 7); });
          var regions = group(function (o) { return o.region; });
          var monthItems = Object.keys(months).sort().map(function (m) {
            var label = fmt(m + "-15", { month: "long", year: "numeric" });
            return { label: label.charAt(0).toUpperCase() + label.slice(1), href: link("month", m), price: months[m].price, count: Object.keys(months[m].cities).length };
          });
          var regionItems = Object.keys(regions).sort(function (a, b) { return regions[a].price - regions[b].price; }).map(function (r) {
            return { label: r, href: link("region", r), price: regions[r].price, count: Object.keys(regions[r].cities).length };
          });
          var budgetItems = [100, 200, 300, 400, 600, 1000].map(function (limit) {
            var inside = rows.filter(function (o) { return o.price <= limit; }), cities = {};
            inside.forEach(function (o) { cities[o.city] = 1; });
            return inside.length && { label: text.under.replace("{price}", euro(limit)), href: link("budget", limit), price: Math.min.apply(null, inside.map(function (o) { return o.price; })), count: Object.keys(cities).length };
          }).filter(Boolean);
          list.textContent = "";
          list.appendChild(block(text.months, monthItems));
          list.appendChild(block(text.regions, regionItems));
          if (budgetItems.length) list.appendChild(block(text.budgets, budgetItems));
          var title = document.querySelector(".page-hero h1") || document.querySelector("h1");
          if (title) title.textContent = text.title.replace("{city}", city);
          var hero = document.querySelector(".page-hero .hero-img");
          if (hero) { hero.srcset = BASE + "assets/photos/" + code + "-m.jpg 640w, " + BASE + "assets/photos/" + code + ".jpg 1600w"; hero.src = BASE + "assets/photos/" + code + ".jpg"; }
        })
        .catch(function () {});
    }
    if (pick.value !== "PAR") show();
    pick.addEventListener("change", function () {
      try { history.replaceState(null, "", "?origin=" + pick.value); } catch (error) {}
      show();
    });
  }

  /* Voyage sur mesure : envoie la demande à contact@eunodia.com via FormSubmit (sans ouvrir de messagerie) */
  function initCustom() {
    var form = $("custom-form");
    if (!form) return;
    var button = form.querySelector("button[type=submit]"), done = $("custom-done"), fail = $("custom-fail");
    form.addEventListener("submit", function (event) {
      event.preventDefault();
      var data = new FormData(form), tastes = data.getAll("envies").join(", ") || "-";
      if (data.get("_honey")) return;
      var subject = "Voyage sur mesure : " + data.get("destination") + " (" + data.get("prenom") + ")";
      var payload = {
        "Prénom": data.get("prenom"), "E-mail": data.get("email"), "Destination": data.get("destination"),
        "Départ": data.get("depart") || "-", "Quand": data.get("dates"), "Voyageurs": data.get("voyageurs"),
        "Budget": data.get("budget"), "Envies": tastes, "Message": data.get("message") || "-",
        _subject: subject, _replyto: data.get("email"), _template: "box", _captcha: "false"
      };
      var mailto = "mailto:" + form.getAttribute("data-to") + "?subject=" + encodeURIComponent(subject) + "&body=" +
        encodeURIComponent(Object.keys(payload).filter(function (k) { return k.charAt(0) !== "_"; }).map(function (k) { return k + " : " + payload[k]; }).join("\n"));
      button.disabled = true;
      button.textContent = "Envoi en cours…";
      fetch(form.getAttribute("data-endpoint"), {
        method: "POST", headers: { "Content-Type": "application/json", "Accept": "application/json" }, body: JSON.stringify(payload)
      }).then(function (response) { return response.json(); }).then(function (result) {
        if (String(result.success) !== "true") throw new Error(result.message || "envoi refusé");
        form.reset();
        form.querySelector(".custom-grid").hidden = true;
        done.hidden = false; fail.hidden = true;
        button.hidden = true;
      }).catch(function () {
        fail.querySelector("a").href = mailto;
        fail.hidden = false;
        button.disabled = false;
        button.textContent = "Envoyer ma demande";
      });
    });
  }

  function rotatePhotos(today) {
    var cards = Array.prototype.slice.call(document.querySelectorAll(".mosaic .card"));
    if (cards.length < 2) return;
    var content = cards.map(function (card) { return { href: card.href, html: card.innerHTML }; });
    cards.forEach(function (card, index) {
      var next = content[(index + today) % content.length];
      card.href = next.href;
      card.innerHTML = next.html;
    });
  }

  initSearch();
  initNewsletter();
  initMenu();
  initNearby();
  initHeroVideo();
  initLanguageMenu();
  initMoreFilters();
  rotatePhotos(Math.floor(Date.now() / 864e5));
  highlightMonth();
  initCharts();
  initFlights();
  initDeals();
  /* « Les incontournables » : le widget d'activités Klook n'est chargé qu'à la première ouverture */
  document.addEventListener("toggle", function (event) {
    var fold = event.target;
    if (!fold.classList || !fold.classList.contains("musts-fold") || !fold.open) return;
    var box = fold.querySelector(".musts-widget");
    if (!box || box.dataset.loaded) return;
    box.dataset.loaded = "1";
    var script = el("script");
    script.async = true;
    script.charset = "utf-8";
    script.src = box.dataset.src;
    box.appendChild(script);
  }, true);

  initCustom(); initWhiteLabel(); initHotels();
})();
