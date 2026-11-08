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

  /* Voyage sur mesure : prépare l'e-mail de demande avec les réponses du formulaire */
  function initCustom() {
    var form = $("custom-form");
    if (!form) return;
    form.addEventListener("submit", function (event) {
      event.preventDefault();
      var data = new FormData(form), tastes = data.getAll("envies").join(", ") || "-";
      var lines = [
        "Prénom : " + data.get("prenom"), "E-mail : " + data.get("email"), "Destination : " + data.get("destination"),
        "Départ : " + (data.get("depart") || "-"), "Quand : " + data.get("dates"), "Voyageurs : " + data.get("voyageurs"),
        "Budget : " + data.get("budget"), "Envies : " + tastes, "", data.get("message") || ""
      ];
      var subject = "Voyage sur mesure : " + data.get("destination");
      location.href = "mailto:" + form.getAttribute("data-to") + "?subject=" + encodeURIComponent(subject) + "&body=" + encodeURIComponent(lines.join("\n"));
      $("custom-done").hidden = false;
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
  initCustom();
})();
