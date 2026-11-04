(function () {
  "use strict";
  var PAGE = 40;
  var STORAGE = "radar-consent";
  var all = [];
  var current = [];
  var shown = PAGE;
  var $ = function (id) { return document.getElementById(id); };
  var euro = function (n) { return Math.round(n).toLocaleString("fr-FR") + " €"; };
  var dateOf = function (iso) { return new Date(iso + "T12:00:00Z"); };
  var longDate = function (iso, options) {
    return dateOf(iso).toLocaleDateString("fr-FR", options || { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" });
  };
  var days = function (o) { return Math.round((dateOf(o.back) - dateOf(o.depart)) / 864e5); };
  var drop = function (o) { return o.usual && o.price < o.usual ? Math.round((1 - o.price / o.usual) * 100) : 0; };
  var stops = function (o) {
    if (o.stops === null || o.stops === undefined) return "escales non précisées";
    return o.stops === 0 ? "vol direct" : o.stops + " escale" + (o.stops > 1 ? "s" : "");
  };

  function el(tag, className, text) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  function svg(tag, attrs, text) {
    var node = document.createElementNS("http://www.w3.org/2000/svg", tag);
    Object.keys(attrs).forEach(function (key) { node.setAttribute(key, attrs[key]); });
    if (text !== undefined) node.textContent = text;
    return node;
  }

  function safeLink(url) {
    try { return new URL(url).hostname.endsWith("aviasales.com") ? url : "#"; } catch (e) { return "#"; }
  }

  function chart(offer, width) {
    var box = el("div", "chart");
    box.appendChild(el("h3", "", "Évolution du prix relevé"));
    var points = offer.history;
    var W = Math.max(280, Math.round(width)), H = 150, left = 54, right = 12, top = 12, bottom = 26;
    var prices = points.map(function (p) { return p[1]; });
    var min = Math.min.apply(null, prices), max = Math.max.apply(null, prices);
    var pad = Math.max((max - min) * 0.15, 5);
    var low = Math.max(0, min - pad), high = max + pad;
    var x = function (i) { return points.length < 2 ? left : left + i * (W - left - right) / (points.length - 1); };
    var y = function (v) { return top + (high - v) * (H - top - bottom) / (high - low); };
    var labels = points.map(function (p) { return longDate(p[0], { day: "numeric", month: "short", timeZone: "UTC" }); });
    var plot = svg("svg", {
      viewBox: "0 0 " + W + " " + H, role: "img",
      "aria-label": "Prix de " + euro(points[0][1]) + " le " + labels[0] + " à " + euro(prices[prices.length - 1]) + " le " + labels[labels.length - 1]
    });
    [high - pad, low + pad].forEach(function (value) {
      plot.appendChild(svg("line", { class: "grid", x1: left, x2: W - right, y1: y(value), y2: y(value), "vector-effect": "non-scaling-stroke" }));
      plot.appendChild(svg("text", { class: "axis", x: left - 8, y: y(value) + 4, "text-anchor": "end" }, euro(value)));
    });
    plot.appendChild(svg("text", { class: "axis", x: left, y: H - 6 }, labels[0]));
    plot.appendChild(svg("text", { class: "axis", x: W - right, y: H - 6, "text-anchor": "end" }, labels[labels.length - 1]));
    plot.appendChild(svg("polyline", {
      class: "line", "vector-effect": "non-scaling-stroke",
      points: points.map(function (p, i) { return x(i) + "," + y(p[1]); }).join(" ")
    }));
    var cross = svg("line", { class: "cross", y1: top, y2: H - bottom, visibility: "hidden", "vector-effect": "non-scaling-stroke" });
    var dot = svg("circle", { class: "dot", r: 5, cx: x(points.length - 1), cy: y(prices[prices.length - 1]) });
    plot.appendChild(cross);
    plot.appendChild(dot);
    box.appendChild(plot);
    var tip = el("div", "tip");
    tip.hidden = true;
    box.appendChild(tip);

    function hover(event) {
      var rect = plot.getBoundingClientRect();
      var ratio = (event.clientX - rect.left) / rect.width * W;
      var i = points.length < 2 ? 0 : Math.round((ratio - left) * (points.length - 1) / (W - left - right));
      i = Math.min(points.length - 1, Math.max(0, i));
      cross.setAttribute("x1", x(i)); cross.setAttribute("x2", x(i));
      cross.setAttribute("visibility", "visible");
      dot.setAttribute("cx", x(i)); dot.setAttribute("cy", y(prices[i]));
      tip.textContent = labels[i] + " · " + euro(prices[i]);
      tip.hidden = false;
      var half = tip.offsetWidth / 2;
      var position = x(i) / W * rect.width;
      tip.style.left = Math.min(rect.width - half, Math.max(half, position)) + "px";
      tip.style.top = "34px";
    }
    plot.addEventListener("pointermove", hover);
    plot.addEventListener("pointerdown", hover);
    plot.addEventListener("pointerleave", function () {
      tip.hidden = true;
      cross.setAttribute("visibility", "hidden");
      dot.setAttribute("cx", x(points.length - 1)); dot.setAttribute("cy", y(prices[prices.length - 1]));
    });
    return box;
  }

  function card(offer) {
    var item = el("li", "offer");
    var row = el("div", "main-row");
    var place = el("div");
    place.appendChild(el("h2", "", offer.city));
    place.appendChild(el("span", "region", offer.region));
    row.appendChild(place);
    row.appendChild(el("div", "price", euro(offer.price)));
    var details = el("div", "details");
    details.appendChild(document.createTextNode(
      longDate(offer.depart) + " → " + longDate(offer.back) + " · " + days(offer) + " jours · " + stops(offer)
    ));
    if (drop(offer) >= 10) {
      details.appendChild(el("br"));
      details.appendChild(el("span", "tag", "−" + drop(offer) + " % par rapport au prix habituel"));
    }
    row.appendChild(details);
    var actions = el("div", "actions");
    if (offer.history.length >= 2) {
      var toggle = el("button", "link", "Voir l'évolution");
      toggle.type = "button";
      toggle.setAttribute("aria-expanded", "false");
      toggle.addEventListener("click", function () {
        var open = item.querySelector(".chart");
        if (open) open.remove(); else item.appendChild(chart(offer, item.clientWidth - 34));
        toggle.setAttribute("aria-expanded", String(!open));
        toggle.textContent = open ? "Voir l'évolution" : "Masquer l'évolution";
      });
      actions.appendChild(toggle);
    }
    var cta = el("a", "cta", "Voir ce vol");
    cta.href = safeLink(offer.link);
    cta.target = "_blank";
    cta.rel = "noopener sponsored";
    cta.setAttribute("aria-label", "Voir le vol pour " + offer.city + " à " + euro(offer.price));
    actions.appendChild(cta);
    row.appendChild(actions);
    item.appendChild(row);
    return item;
  }

  function filtered() {
    var region = $("region").value, month = $("month").value, budget = Number($("budget").value);
    var length = $("length").value.split("-").map(Number);
    return all.filter(function (o) {
      return (!region || o.region === region) && (!month || o.depart.slice(0, 7) === month) &&
        (!budget || o.price <= budget) &&
        (length.length < 2 || (days(o) >= length[0] && days(o) <= length[1]));
    });
  }

  function updateMore() {
    var total = current.length;
    var visible = Math.min(shown, total);
    $("more").hidden = total <= shown;
    $("more").textContent = "Afficher plus de vols (" + visible + " sur " + total + ")";
  }

  function render() {
    current = filtered();
    shown = PAGE;
    var box = $("offers");
    box.textContent = "";
    if (!current.length) box.appendChild(el("li", "empty", "Aucun vol avec ces filtres. Essaie un budget plus large ou un autre mois."));
    current.slice(0, shown).forEach(function (offer) { box.appendChild(card(offer)); });
    $("count").textContent = current.length + " vol" + (current.length > 1 ? "s" : "") + " · du moins cher au plus cher";
    updateMore();
  }

  function showMore() {
    var box = $("offers");
    var added = current.slice(shown, shown + PAGE).map(card);
    added.forEach(function (item) { box.appendChild(item); });
    shown += PAGE;
    updateMore();
    if (added.length) {
      added[0].tabIndex = -1;
      added[0].focus({ preventScroll: true });
    }
  }

  function fill(select, values, label) {
    values.forEach(function (value) {
      var option = el("option", "", label ? label(value) : value);
      option.value = value;
      select.appendChild(option);
    });
  }

  function start(data) {
    all = data.offers || [];
    var regions = {}, months = {};
    all.forEach(function (o) { regions[o.region] = 1; months[o.depart.slice(0, 7)] = 1; });
    fill($("region"), Object.keys(regions).sort(function (a, b) { return a.localeCompare(b, "fr"); }));
    fill($("month"), Object.keys(months).sort(), function (m) {
      return longDate(m + "-15", { month: "long", year: "numeric", timeZone: "UTC" });
    });
    if (data.updated) {
      $("updated").textContent = "Dernier relevé : " + new Date(data.updated).toLocaleString("fr-FR", {
        day: "numeric", month: "long", hour: "2-digit", minute: "2-digit"
      });
    }
    render();
  }

  $("filters").addEventListener("change", render);
  $("more").addEventListener("click", showMore);

  fetch("prices.json", { cache: "no-cache" })
    .then(function (response) { if (!response.ok) throw new Error(); return response.json(); })
    .then(start)
    .catch(function () {
      $("count").textContent = "";
      $("offers").appendChild(el("li", "empty", "Les prix arrivent bientôt. Reviens après le prochain relevé."));
    });

  function stored() {
    try { return localStorage.getItem(STORAGE); } catch (e) { return null; }
  }

  function store(value) {
    try { localStorage.setItem(STORAGE, value); } catch (e) { /* le choix vaut pour cette visite */ }
  }

  function loadPartner() {
    if (window.radarPartnerLoaded) return;
    window.radarPartnerLoaded = true;
    var script = document.createElement("script");
    script.async = 1;
    script.setAttribute("data-cmp-ab", "2");
    script.src = "https://tpembars.com/NTk1NDgw.js?t=595480";
    document.head.appendChild(script);
  }

  function choose(value) {
    var changed = stored() === "yes" && value === "no";
    store(value);
    $("consent").hidden = true;
    if (value === "yes") loadPartner();
    if (changed) location.reload();
  }

  $("accept").addEventListener("click", function () { choose("yes"); });
  $("refuse").addEventListener("click", function () { choose("no"); });
  $("manage").addEventListener("click", function () { $("consent").hidden = false; });
  if (stored() === "yes") loadPartner();
  else if (stored() !== "no") $("consent").hidden = false;
})();
