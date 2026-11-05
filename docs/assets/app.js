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
      marker: "800338", trs: "595480", p: "4114", campaign_id: "100", u: url
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
      location.href = partner(url);
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
      "aria-label": "Prix de " + euro(prices[0]) + " le " + label(0) + " à " + euro(prices[last]) + " le " + label(last)
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

  /* Liste filtrable */
  function initFlights() {
    if (!$("offers")) return;
    var all = [], current = [], shown = PAGE;
    var clean = function (text) { return text.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase(); };

    function card(o) {
      var item = el("li", "row");
      var info = el("div", "row-info");
      var title = el("h3");
      var link = el("a", "", o.city);
      link.href = ROOT + "destinations/" + o.slug + "/";
      title.appendChild(link);
      info.appendChild(title);
      info.appendChild(el("p", "", fmt(o.depart, { day: "numeric", month: "short" }) + " → " + shortDate(o.back) + " · " + say("days", { count: days(o) }) + " · " + stops(o)));
      var cta = el("a", "go", RF.t.see);
      cta.href = link.href + "?mois=" + o.depart.slice(0, 7);
      item.appendChild(info); item.appendChild(el("p", "row-price", euro(o.price))); item.appendChild(cta);
      return item;
    }

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
      values.forEach(function (value) {
        var option = el("option", "", label ? label(value) : value);
        option.value = value;
        select.appendChild(option);
      });
    }

    fetch(ROOT + "prices.json", { cache: "no-cache" })
      .then(function (r) { if (!r.ok) throw new Error(); return r.json(); })
      .then(function (data) {
        all = data.offers || [];
        var regions = {}, months = {};
        all.forEach(function (o) { regions[o.region] = 1; months[o.depart.slice(0, 7)] = 1; });
        fill($("region"), Object.keys(regions).sort(function (a, b) { return a.localeCompare(b, "fr"); }));
        fill($("month"), Object.keys(months).sort(), function (m) { return fmt(m + "-15", { month: "long", year: "numeric" }); });
        new URLSearchParams(location.search).forEach(function (value, key) {
          if ($(key) && $(key).closest("#filters")) $(key).value = value;
        });
        render();
      })
      .catch(function () {
        $("offers").appendChild(el("li", "empty", RF.t.soon));
      });
    $("filters").addEventListener("input", render);
    $("filters").addEventListener("submit", function (event) { event.preventDefault(); });
    $("more").addEventListener("click", showMore);
  }

  function highlightMonth() {
    var month = new URLSearchParams(location.search).get("mois");
    var row = month && document.getElementById("m-" + month);
    if (row) row.classList.add("picked");
  }

  initSearch();
  highlightMonth();
  initCharts();
  initFlights();
})();
