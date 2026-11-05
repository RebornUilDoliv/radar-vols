(function () {
  "use strict";
  var box = document.getElementById("booking");
  if (!box) return;
  var API = box.dataset.api || "";
  var RF = window.RF;
  var BASE = RF.base;
  var say = function (key, values) {
    return RF.t[key].replace(/\{(\w+)\}/g, function (_, name) { return (values || {})[name]; });
  };
  var cities = null;
  var loading = null;
  var NAMES = ["Alice", "Bruno", "Chloe", "David", "Emma", "Felix"];
  var LETTERS = "[A-Za-zÀ-ÿ' \\-]+";
  var state = {};

  function el(tag, className, text) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }
  function field(label, input) {
    var wrap = el("label", "book-field", label);
    wrap.appendChild(input);
    return wrap;
  }
  function input(type, value, attrs) {
    var node = el("input");
    node.type = type;
    node.value = value || "";
    node.required = true;
    Object.keys(attrs || {}).forEach(function (key) { node.setAttribute(key, attrs[key]); });
    return node;
  }
  function select(options, value) {
    var node = el("select");
    options.forEach(function (option) {
      var item = el("option", "", option[1]);
      item.value = option[0];
      node.appendChild(item);
    });
    node.value = value;
    return node;
  }
  function loadCities() {
    loading = loading || fetch(BASE + "assets/cities-" + RF.lang + ".json").then(function (r) { return r.json(); })
      .then(function (rows) { cities = rows; }).catch(function () { loading = null; });
    return loading;
  }
  function clean(text) {
    return text.normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase().trim();
  }
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
  function cityField(label, name, code) {
    var wrap = el("div", "field");
    var title = el("label", "", label);
    var text = input("text", name ? name + " (" + code + ")" : "", { placeholder: RF.search_place, autocomplete: "off" });
    var list = el("ul", "suggest");
    list.hidden = true;
    if (code) text.dataset.code = code;
    title.appendChild(text);
    wrap.appendChild(title);
    wrap.appendChild(list);
    function close() { list.hidden = true; list.textContent = ""; }
    function pick(row) {
      text.value = row[1] + " (" + row[0] + ")";
      text.dataset.code = row[0];
      close();
    }
    function suggest() {
      var found = matches(text.value);
      list.textContent = "";
      list.hidden = !found.length;
      found.forEach(function (row) {
        var option = el("button", "", row[1] + " (" + row[0] + ")");
        option.type = "button";
        if (row[2]) option.appendChild(el("small", "", " · " + row[2]));
        option.addEventListener("mousedown", function (event) { event.preventDefault(); pick(row); });
        option.addEventListener("click", function () { pick(row); });
        var item = el("li");
        item.appendChild(option);
        list.appendChild(item);
      });
    }
    text.addEventListener("focus", loadCities);
    text.addEventListener("input", function () { delete text.dataset.code; loadCities().then(suggest); });
    text.addEventListener("blur", function () { setTimeout(close, 120); });
    text.addEventListener("keydown", function (event) {
      if (event.key === "Escape") close();
      if (event.key === "Enter" && !list.hidden && list.querySelector("button")) {
        event.preventDefault();
        list.querySelector("button").click();
      }
    });
    return { node: wrap, input: text };
  }
  function money(amount, currency) {
    return Number(amount).toLocaleString(RF.locale, { style: "currency", currency: currency, maximumFractionDigits: 2 });
  }
  function when(iso) {
    return new Date(iso).toLocaleString(RF.locale, { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
  }
  function dayAhead(days) {
    return new Date(Date.now() + days * 864e5).toISOString().slice(0, 10);
  }
  function show(title, step) {
    box.textContent = "";
    box.appendChild(el("p", "book-step", say("step", { n: step })));
    box.appendChild(el("h2", "", title));
    box.focus();
    window.scrollTo(0, 0);
  }
  function problem(message) {
    var note = box.querySelector(".form-error") || box.appendChild(el("p", "form-error"));
    note.textContent = message;
  }

  /* Réponses simulées quand le serveur de test n'est pas branché */
  function demoSearch(query) {
    var base = 88 + (query.from.charCodeAt(0) + query.to.charCodeAt(1)) % 90;
    return ["Duffel Airways", "Air Démo", "Vol Fictif"].map(function (airline, index) {
      var hour = String(7 + index * 5).padStart(2, "0");
      var slices = [{ from: query.from, to: query.to, departing: query.depart + "T" + hour + ":10:00", arriving: query.depart + "T" + hour + ":55:00", stops: index === 2 ? 1 : 0 }];
      if (query.back) slices.push({ from: query.to, to: query.from, departing: query.back + "T" + hour + ":30:00", arriving: query.back + "T" + hour + ":59:00", stops: 0 });
      return {
        id: "demo_" + index, amount: ((base + index * 37) * query.adults).toFixed(2), currency: "EUR", airline: airline, slices: slices,
        passengers: Array.from({ length: query.adults }, function (_, i) { return "pas_" + i; })
      };
    });
  }
  function demoReference() {
    var letters = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789";
    return Array.from({ length: 6 }, function () { return letters[Math.floor(Math.random() * letters.length)]; }).join("");
  }
  function call(path, body) {
    if (!API) {
      return new Promise(function (resolve) {
        setTimeout(function () {
          resolve(path === "/search" ? { offers: demoSearch(body) } : { reference: demoReference(), airline: state.offer.airline, amount: state.offer.amount, currency: state.offer.currency });
        }, 250);
      });
    }
    return fetch(API + path, { method: "POST", headers: { "Content-Type": "text/plain" }, body: JSON.stringify(body) })
      .then(function (r) { return r.json().then(function (data) { if (!r.ok) throw new Error(data.error); return data; }); });
  }

  function stepSearch() {
    show(RF.t.where, 1);
    var form = el("form", "book-form");
    var from = cityField(RF.from_label, RF.from_name, "PAR"), to = cityField(RF.to_label, RF.to_name, "NYC");
    var depart = input("date", dayAhead(30), { min: dayAhead(1) });
    var back = input("date", dayAhead(37), { min: dayAhead(1) });
    back.required = false;
    var adults = select([["1", "1"], ["2", "2"], ["3", "3"]], "1");
    [from.node, to.node, field(RF.out_label, depart), field(RF.t.back_opt, back), field(RF.t.adults, adults)].forEach(function (node) { form.appendChild(node); });
    var submit = el("button", "search-go", RF.t.see_flights);
    submit.type = "submit";
    form.appendChild(submit);
    form.addEventListener("submit", function (event) {
      event.preventDefault();
      var origin = from.input.dataset.code, destination = to.input.dataset.code;
      if (!origin || !destination) return problem(RF.t.pick_list);
      if (origin === destination) return problem(RF.t.same_city);
      submit.disabled = true;
      state.adults = Number(adults.value);
      call("/search", { from: origin, to: destination, depart: depart.value, back: back.value, adults: state.adults })
        .then(function (data) { stepOffers(data.offers); })
        .catch(function () { submit.disabled = false; problem(RF.t.search_fail); });
    });
    box.appendChild(form);
  }

  function clock(iso) {
    return new Date(iso).toLocaleTimeString(RF.locale, { hour: "2-digit", minute: "2-digit" });
  }
  function duration(value) {
    var match = /^P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?/.exec(value || "");
    if (!match) return "";
    var hours = Number(match[1] || 0) * 24 + Number(match[2] || 0);
    return hours + " h " + String(Number(match[3] || 0)).padStart(2, "0");
  }
  function gap(from, to) {
    var minutes = Math.round((new Date(to) - new Date(from)) / 6e4);
    return Math.floor(minutes / 60) + " h " + String(minutes % 60).padStart(2, "0");
  }
  function airport(point) {
    return (point.city || point.name || point.code) + " (" + point.code + ")";
  }
  function itinerary(offer) {
    var box = el("details", "route");
    box.appendChild(el("summary", "", RF.t.itinerary));
    offer.slices.forEach(function (slice, index) {
      var part = el("div", "route-part");
      var total = duration(slice.duration);
      part.appendChild(el("h4", "", (index ? RF.t.inbound : RF.t.outbound) + (total ? ", " + say("trip", { time: total }) : "")));
      if (!slice.segments) {
        part.appendChild(el("p", "", slice.from + " → " + slice.to + ", " + RF.t.no_detail));
      }
      var stops = el("ol", "route-steps");
      (slice.segments || []).forEach(function (segment, position) {
        if (position) {
          var pause = el("li", "route-stop", say("stop_at", { place: airport(segment.from), time: gap(slice.segments[position - 1].arriving, segment.departing) }));
          stops.appendChild(pause);
        }
        var leg = el("li", "route-leg");
        leg.appendChild(el("strong", "", clock(segment.departing) + " " + airport(segment.from)));
        leg.appendChild(el("span", "", "↓ " + [segment.carrier, segment.flight, duration(segment.duration)].filter(Boolean).join(", ")));
        leg.appendChild(el("strong", "", clock(segment.arriving) + " " + airport(segment.to)));
        stops.appendChild(leg);
      });
      part.appendChild(stops);
      box.appendChild(part);
    });
    return box;
  }

  function stepOffers(offers) {
    show(RF.t.choose, 2);
    if (!offers.length) {
      box.appendChild(el("p", "sub", RF.t.none_test));
    }
    var list = el("ul", "rows");
    offers.slice().sort(function (a, b) {
      return (b.airline === "Duffel Airways") - (a.airline === "Duffel Airways");
    }).forEach(function (offer) {
      var row = el("li", "row");
      var info = el("div", "row-info");
      info.appendChild(el("h3", "", offer.airline));
      offer.slices.forEach(function (slice) {
        info.appendChild(el("p", "", slice.from + " → " + slice.to + ", " + when(slice.departing) + ", " + (slice.stops ? say("stop", { count: slice.stops }) : RF.t.direct)));
      });
      var pick = el("button", "linkish", RF.t.pick);
      pick.type = "button";
      pick.addEventListener("click", function () { state.offer = offer; stepPassengers(); });
      row.appendChild(info);
      row.appendChild(el("p", "row-price", money(offer.amount, offer.currency)));
      row.appendChild(pick);
      row.appendChild(itinerary(offer));
      list.appendChild(row);
    });
    box.appendChild(list);
    box.appendChild(backButton(stepSearch));
  }

  function backButton(action) {
    var back = el("button", "linkish book-back", RF.t.back_step);
    back.type = "button";
    back.addEventListener("click", action);
    return back;
  }

  function stepPassengers() {
    show(RF.t.who, 3);
    box.appendChild(el("p", "sub", RF.t.fake));
    var form = el("form", "book-form");
    var people = state.offer.passengers.map(function (_, index) {
      var person = {
        title: select([["ms", RF.t.ms], ["mr", RF.t.mr]], "ms"),
        given_name: input("text", NAMES[index % NAMES.length], { autocomplete: "off", pattern: LETTERS, title: RF.t.letters }),
        family_name: input("text", "Demo", { autocomplete: "off", pattern: LETTERS, title: RF.t.letters }),
        born_on: input("date", "1990-01-0" + (index + 1), { max: dayAhead(-6600) }),
        gender: select([["f", RF.t.f], ["m", RF.t.m]], "f"),
        email: input("email", "test" + (index + 1) + "@example.com", { autocomplete: "off" }),
        phone_number: input("tel", "+442080160508", { autocomplete: "off", pattern: "\\+[0-9]{6,15}" })
      };
      var group = el("fieldset", "book-person");
      group.appendChild(el("legend", "", say("traveller", { n: index + 1 })));
      [[RF.t.title, "title"], [RF.t.given, "given_name"], [RF.t.family, "family_name"], [RF.t.born, "born_on"], [RF.t.gender, "gender"], [RF.t.email, "email"], [RF.t.phone, "phone_number"]].forEach(function (item) {
        group.appendChild(field(item[0], person[item[1]]));
      });
      form.appendChild(group);
      return person;
    });
    var submit = el("button", "search-go", RF.t.next);
    submit.type = "submit";
    form.appendChild(submit);
    form.addEventListener("submit", function (event) {
      event.preventDefault();
      state.passengers = people.map(function (person) {
        var values = {};
        Object.keys(person).forEach(function (key) { values[key] = person[key].value; });
        return values;
      });
      stepPayment();
    });
    box.appendChild(form);
    box.appendChild(backButton(function () { stepOffers([state.offer]); }));
  }

  function stepPayment() {
    show(RF.t.pay, 4);
    box.appendChild(el("p", "lead", say("total", { airline: state.offer.airline, price: money(state.offer.amount, state.offer.currency) })));
    box.appendChild(el("p", "sub", RF.t.no_card));
    var pay = el("button", "search-go", RF.t.pay_go);
    pay.type = "button";
    pay.addEventListener("click", function () {
      pay.disabled = true;
      call("/order", { offer: state.offer.id, passengers: state.passengers })
        .then(stepDone)
        .catch(function () { pay.disabled = false; problem(RF.t.order_fail); });
    });
    box.appendChild(pay);
    box.appendChild(backButton(stepPassengers));
  }

  function stepDone(order) {
    box.textContent = "";
    box.appendChild(el("h2", "", RF.t.done));
    box.appendChild(el("p", "lead", say("ref", { ref: order.reference })));
    box.appendChild(el("p", "sub", say("not_real", { airline: order.airline, price: money(order.amount, order.currency) })));
    var again = el("button", "search-go", RF.t.again);
    again.type = "button";
    again.addEventListener("click", stepSearch);
    box.appendChild(again);
    box.focus();
  }

  stepSearch();
})();
