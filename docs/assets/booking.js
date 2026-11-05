(function () {
  "use strict";
  var box = document.getElementById("booking");
  if (!box) return;
  var API = box.dataset.api || "";
  var AIRPORTS = [["CDG", "Paris Charles-de-Gaulle"], ["ORY", "Paris Orly"], ["LHR", "Londres Heathrow"], ["JFK", "New York JFK"], ["BCN", "Barcelone"], ["LIS", "Lisbonne"], ["FCO", "Rome Fiumicino"], ["BKK", "Bangkok"]];
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
  function money(amount, currency) {
    return Number(amount).toLocaleString("fr-FR", { style: "currency", currency: currency, maximumFractionDigits: 2 });
  }
  function when(iso) {
    return new Date(iso).toLocaleString("fr-FR", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
  }
  function dayAhead(days) {
    return new Date(Date.now() + days * 864e5).toISOString().slice(0, 10);
  }
  function show(title, step) {
    box.textContent = "";
    box.appendChild(el("p", "book-step", "Étape " + step + " sur 4"));
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
    return fetch(API + path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) })
      .then(function (r) { return r.json().then(function (data) { if (!r.ok) throw new Error(data.error); return data; }); });
  }

  function stepSearch() {
    show("Où veux-tu aller ?", 1);
    var form = el("form", "book-form");
    var from = select(AIRPORTS, "LHR"), to = select(AIRPORTS, "JFK");
    var depart = input("date", dayAhead(30), { min: dayAhead(1) });
    var back = input("date", dayAhead(37), { min: dayAhead(1) });
    back.required = false;
    var adults = select([["1", "1"], ["2", "2"], ["3", "3"]], "1");
    [field("Départ", from), field("Destination", to), field("Aller", depart), field("Retour (facultatif)", back), field("Adultes", adults)].forEach(function (node) { form.appendChild(node); });
    var submit = el("button", "search-go", "Voir les vols");
    submit.type = "submit";
    form.appendChild(submit);
    form.addEventListener("submit", function (event) {
      event.preventDefault();
      if (from.value === to.value) return problem("Choisis deux aéroports différents.");
      submit.disabled = true;
      state.adults = Number(adults.value);
      call("/search", { from: from.value, to: to.value, depart: depart.value, back: back.value, adults: state.adults })
        .then(function (data) { stepOffers(data.offers); })
        .catch(function () { submit.disabled = false; problem("La recherche n'a pas marché. Réessaie dans un instant."); });
    });
    box.appendChild(form);
  }

  function stepOffers(offers) {
    show("Choisis ton vol", 2);
    if (!offers.length) {
      box.appendChild(el("p", "sub", "Aucun vol de test pour ce trajet."));
    }
    var list = el("ul", "rows");
    offers.slice().sort(function (a, b) {
      return (b.airline === "Duffel Airways") - (a.airline === "Duffel Airways");
    }).forEach(function (offer) {
      var row = el("li", "row");
      var info = el("div", "row-info");
      info.appendChild(el("h3", "", offer.airline));
      offer.slices.forEach(function (slice) {
        info.appendChild(el("p", "", slice.from + " → " + slice.to + ", " + when(slice.departing) + (slice.stops ? ", " + slice.stops + " escale" : ", direct")));
      });
      var pick = el("button", "linkish", "Choisir");
      pick.type = "button";
      pick.addEventListener("click", function () { state.offer = offer; stepPassengers(); });
      row.appendChild(info);
      row.appendChild(el("p", "row-price", money(offer.amount, offer.currency)));
      row.appendChild(pick);
      list.appendChild(row);
    });
    box.appendChild(list);
    box.appendChild(backButton(stepSearch));
  }

  function backButton(action) {
    var back = el("button", "linkish book-back", "Revenir en arrière");
    back.type = "button";
    back.addEventListener("click", action);
    return back;
  }

  function stepPassengers() {
    show("Qui voyage ?", 3);
    box.appendChild(el("p", "sub", "Garde ces données fictives : c'est un test."));
    var form = el("form", "book-form");
    var people = state.offer.passengers.map(function (_, index) {
      var person = {
        title: select([["ms", "Mme"], ["mr", "M."]], "ms"),
        given_name: input("text", "Test" + (index + 1), { autocomplete: "off" }),
        family_name: input("text", "Demo", { autocomplete: "off" }),
        born_on: input("date", "1990-01-0" + (index + 1), { max: dayAhead(-6600) }),
        gender: select([["f", "Femme"], ["m", "Homme"]], "f"),
        email: input("email", "test" + (index + 1) + "@example.com", { autocomplete: "off" }),
        phone_number: input("tel", "+442080160508", { autocomplete: "off", pattern: "\\+[0-9]{6,15}" })
      };
      var group = el("fieldset", "book-person");
      group.appendChild(el("legend", "", "Voyageur " + (index + 1)));
      [["Civilité", "title"], ["Prénom", "given_name"], ["Nom", "family_name"], ["Date de naissance", "born_on"], ["Genre", "gender"], ["E-mail", "email"], ["Téléphone", "phone_number"]].forEach(function (item) {
        group.appendChild(field(item[0], person[item[1]]));
      });
      form.appendChild(group);
      return person;
    });
    var submit = el("button", "search-go", "Continuer");
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
    show("Paiement simulé", 4);
    box.appendChild(el("p", "lead", state.offer.airline + ", total " + money(state.offer.amount, state.offer.currency)));
    box.appendChild(el("p", "sub", "Aucune carte n'est demandée et aucun argent n'est débité."));
    var pay = el("button", "search-go", "Simuler le paiement");
    pay.type = "button";
    pay.addEventListener("click", function () {
      pay.disabled = true;
      call("/order", { offer: state.offer.id, passengers: state.passengers })
        .then(stepDone)
        .catch(function () { pay.disabled = false; problem("La réservation de test a échoué. Le vol n'est peut-être plus disponible."); });
    });
    box.appendChild(pay);
    box.appendChild(backButton(stepPassengers));
  }

  function stepDone(order) {
    box.textContent = "";
    box.appendChild(el("h2", "", "Réservation de test confirmée"));
    box.appendChild(el("p", "lead", "Référence : " + order.reference));
    box.appendChild(el("p", "sub", order.airline + ", " + money(order.amount, order.currency) + ". Ce billet n'existe pas et ne permet pas de voyager."));
    var again = el("button", "search-go", "Recommencer");
    again.type = "button";
    again.addEventListener("click", stepSearch);
    box.appendChild(again);
    box.focus();
  }

  stepSearch();
})();
