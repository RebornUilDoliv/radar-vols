"""Prépare la newsletter du jeudi et la programme dans Brevo, une campagne par langue."""
import html
import json
import os
import sys
import tomllib
import urllib.error
import urllib.request
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import build_site

ROOT = Path(__file__).parent
PARIS = ZoneInfo("Europe/Paris")
BREVO = "https://api.brevo.com/v3"
ORIGINS = dict(build_site.DEFAULT_ORIGIN)   # ville de départ mise en avant pour chaque langue : la même que sur le site
START_NAMES = {("es", "MAD"): "Madrid"}   # le nom de la liste des villes dit « Ciudad de Madrid », trop lourd dans une phrase
FALLBACK_LANG = "en"              # un inscrit dont la langue n'a pas de numéro reçoit l'anglais
SEND_HOUR = 8
FAR, NEAR = 3, 3
MIN_DAYS = 14
SKIPPED = {"MED"}                 # villes qui ne conviennent pas à une offre grand public

esc = html.escape

TEXT = {
    "fr": {
        "title": "Les bons plans Eunodia",
        "subject": "{city} dès {price} : les bons plans de la semaine",
        "preview": "{city} dès {price} au départ de {origin}",
        "hidden": "{city} dès {price} et d'autres vols repérés cette semaine.",
        "headline": "{city} dès {price}",
        "intro": "Voici les meilleurs prix repérés cette semaine au départ de {origin}, en aller-retour.",
        "far": "Les grandes envies",
        "near": "Les escapades",
        "prepare": "Prépare ton voyage",
        "prepare_text": "Hôtel, activités, internet ou transfert : tout est prêt pour ton séjour.",
        "button": "Voir où je peux partir",
        "legal": "Prix relevés récemment, par personne et sans options : ils peuvent changer vite, vérifie toujours le prix final avant de réserver. Certains liens sont partenaires : Eunodia peut toucher une commission, sans frais pour toi.",
        "why": "Tu reçois cet e-mail car tu t'es inscrit sur",
        "contact": "Contact :",
        "unsubscribe": "Se désinscrire",
    },
    "en": {
        "title": "Eunodia deals",
        "subject": "{city} from {price}: this week's best deals",
        "preview": "{city} from {price}, departing {origin}",
        "hidden": "{city} from {price} and more flights spotted this week.",
        "headline": "{city} from {price}",
        "intro": "Here are the best round-trip prices we spotted this week from {origin}.",
        "far": "Big trips",
        "near": "Quick getaways",
        "prepare": "Plan your trip",
        "prepare_text": "Hotel, activities, internet or transfer: everything is ready for your stay.",
        "button": "See where I can go",
        "legal": "Prices spotted recently, per person and without extras: they can change quickly, so always check the final price before booking. Some links are partner links: Eunodia may earn a commission, at no cost to you.",
        "why": "You receive this email because you signed up on",
        "contact": "Contact:",
        "unsubscribe": "Unsubscribe",
    },
    "es": {
        "title": "Las ofertas de Eunodia",
        "subject": "{city} desde {price}: las mejores ofertas de la semana",
        "preview": "{city} desde {price}, saliendo de {origin}",
        "hidden": "{city} desde {price} y otros vuelos que hemos encontrado esta semana.",
        "headline": "{city} desde {price}",
        "intro": "Estos son los mejores precios de ida y vuelta que hemos visto esta semana saliendo de {origin}.",
        "far": "Los grandes viajes",
        "near": "Escapadas",
        "prepare": "Prepara tu viaje",
        "prepare_text": "Hotel, actividades, internet o traslado: todo listo para tu estancia.",
        "button": "Ver adónde puedo ir",
        "legal": "Precios vistos recientemente, por persona y sin extras: pueden cambiar rápido, comprueba siempre el precio final antes de reservar. Algunos enlaces son de socios: Eunodia puede recibir una comisión, sin coste para ti.",
        "why": "Recibes este correo porque te suscribiste en",
        "contact": "Contacto:",
        "unsubscribe": "Darte de baja",
    },
    "de": {
        "title": 'Die Eunodia-Angebote',
        "subject": '{city} ab {price}: die besten Angebote der Woche',
        "preview": '{city} ab {price}, Abflug ab {origin}',
        "hidden": '{city} ab {price} und weitere Flüge, die wir diese Woche entdeckt haben.',
        "headline": '{city} ab {price}',
        "intro": 'Hier sind die besten Preise für Hin- und Rückflug, die wir diese Woche ab {origin} gefunden haben.',
        "far": 'Die großen Reisen',
        "near": 'Kurztrips',
        "prepare": 'Plane deine Reise',
        "prepare_text": 'Hotel, Aktivitäten, Internet oder Transfer: alles bereit für deinen Aufenthalt.',
        "button": 'Sehen, wohin ich reisen kann',
        "legal": 'Kürzlich gefundene Preise, pro Person und ohne Extras: Sie können sich schnell ändern, prüfe vor der Buchung immer den Endpreis. Einige Links sind Partnerlinks: Eunodia kann eine Provision erhalten, ohne Kosten für dich.',
        "why": 'Du erhältst diese E-Mail, weil du dich angemeldet hast auf',
        "contact": 'Kontakt:',
        "unsubscribe": 'Abmelden',
    },
    "it": {
        "title": 'Le offerte di Eunodia',
        "subject": '{city} da {price}: le migliori offerte della settimana',
        "preview": '{city} da {price}, in partenza da {origin}',
        "hidden": '{city} da {price} e altri voli trovati questa settimana.',
        "headline": '{city} da {price}',
        "intro": 'Ecco i migliori prezzi andata e ritorno trovati questa settimana in partenza da {origin}.',
        "far": 'I grandi viaggi',
        "near": 'Le fughe brevi',
        "prepare": 'Prepara il tuo viaggio',
        "prepare_text": 'Hotel, attività, internet o transfer: tutto pronto per il tuo soggiorno.',
        "button": 'Vedi dove posso andare',
        "legal": 'Prezzi trovati di recente, a persona e senza extra: possono cambiare in fretta, controlla sempre il prezzo finale prima di prenotare. Alcuni link sono di partner: Eunodia può ricevere una commissione, senza costi per te.',
        "why": "Ricevi questa email perché hai effettuato l'iscrizione su",
        "contact": 'Contatto:',
        "unsubscribe": "Annulla l'iscrizione",
    },
    "pt": {
        "title": 'As ofertas da Eunodia',
        "subject": '{city} desde {price}: as melhores ofertas da semana',
        "preview": '{city} desde {price}, com partida de {origin}',
        "hidden": '{city} desde {price} e outros voos encontrados esta semana.',
        "headline": '{city} desde {price}',
        "intro": 'Estes são os melhores preços de ida e volta encontrados esta semana com partida de {origin}.',
        "far": 'As grandes viagens',
        "near": 'Escapadinhas',
        "prepare": 'Prepara a tua viagem',
        "prepare_text": 'Hotel, atividades, internet ou transfer: tudo pronto para a tua estadia.',
        "button": 'Ver para onde posso ir',
        "legal": 'Preços encontrados recentemente, por pessoa e sem extras: podem mudar depressa, confirma sempre o preço final antes de reservar. Alguns links são de parceiros: a Eunodia pode receber uma comissão, sem custos para ti.',
        "why": 'Recebes este e-mail porque te inscreveste em',
        "contact": 'Contacto:',
        "unsubscribe": 'Cancelar a subscrição',
    },
    "nl": {
        "title": 'De deals van Eunodia',
        "subject": '{city} vanaf {price}: de beste deals van de week',
        "preview": '{city} vanaf {price}, vertrek vanuit {origin}',
        "hidden": '{city} vanaf {price} en meer vluchten die we deze week vonden.',
        "headline": '{city} vanaf {price}',
        "intro": 'Dit zijn de beste retourprijzen die we deze week vonden vanuit {origin}.',
        "far": 'De grote reizen',
        "near": 'Korte tripjes',
        "prepare": 'Plan je reis',
        "prepare_text": 'Hotel, activiteiten, internet of transfer: alles klaar voor je verblijf.',
        "button": 'Bekijk waar ik heen kan',
        "legal": "Recent gevonden prijzen, per persoon en zonder extra's: ze kunnen snel veranderen, controleer altijd de eindprijs voordat je boekt. Sommige links zijn partnerlinks: Eunodia kan een commissie ontvangen, zonder kosten voor jou.",
        "why": 'Je ontvangt deze e-mail omdat je je hebt ingeschreven op',
        "contact": 'Contact:',
        "unsubscribe": 'Uitschrijven',
    },
    "tr": {
        "title": 'Eunodia fırsatları',
        "subject": '{city}, en düşük {price}: haftanın en iyi fırsatları',
        "preview": '{city}, en düşük {price}, kalkış: {origin}',
        "hidden": '{city}, en düşük {price} ve bu hafta bulduğumuz diğer uçuşlar.',
        "headline": '{city}, en düşük {price}',
        "intro": 'Bu hafta {origin} kalkışlı bulduğumuz en iyi gidiş-dönüş fiyatlar.',
        "far": 'Büyük seyahatler',
        "near": 'Kısa kaçamaklar',
        "prepare": 'Seyahatinizi planlayın',
        "prepare_text": 'Otel, aktiviteler, internet veya transfer: konaklamanız için her şey hazır.',
        "button": 'Nereye gidebileceğimi gör',
        "legal": 'Yakın zamanda bulunan fiyatlar, kişi başı ve ekstralar hariç: hızla değişebilir, rezervasyondan önce her zaman son fiyatı kontrol edin. Bazı bağlantılar iş ortağı bağlantılarıdır: Eunodia, sizin için ek ücret olmadan komisyon alabilir.',
        "why": 'Bu e-postayı, şu sitede kaydolduğunuz için alıyorsunuz:',
        "contact": 'İletişim:',
        "unsubscribe": 'Abonelikten çık',
    },
    "ar": {
        "title": 'عروض Eunodia',
        "subject": '{city} ابتداءً من {price}: أفضل عروض الأسبوع',
        "preview": '{city} ابتداءً من {price}، انطلاقًا من {origin}',
        "hidden": '{city} ابتداءً من {price} ورحلات أخرى رصدناها هذا الأسبوع.',
        "headline": '{city} ابتداءً من {price}',
        "intro": 'إليك أفضل أسعار الذهاب والعودة التي رصدناها هذا الأسبوع انطلاقًا من {origin}.',
        "far": 'الرحلات الكبرى',
        "near": 'رحلات قصيرة',
        "prepare": 'خطط لرحلتك',
        "prepare_text": 'فندق، أنشطة، إنترنت أو توصيل: كل شيء جاهز لإقامتك.',
        "button": 'اعرف إلى أين يمكنني الذهاب',
        "legal": 'أسعار رُصدت مؤخرًا، للشخص الواحد ودون إضافات: قد تتغير بسرعة، لذا تحقق دائمًا من السعر النهائي قبل الحجز. بعض الروابط روابط شركاء: قد يحصل Eunodia على عمولة دون أي تكلفة عليك.',
        "why": 'تصلك هذه الرسالة لأنك اشتركت في',
        "contact": 'للتواصل:',
        "unsubscribe": 'إلغاء الاشتراك',
    },
    "zh": {
        "title": 'Eunodia 特惠',
        "subject": '{city} {price} 起：本周最佳特惠',
        "preview": '{city} {price} 起，从{origin}出发',
        "hidden": '{city} {price} 起，以及本周发现的更多航班。',
        "headline": '{city} {price} 起',
        "intro": '以下是本周从{origin}出发的最佳往返价格。',
        "far": '远途旅行',
        "near": '短途出游',
        "prepare": '规划您的旅行',
        "prepare_text": '酒店、活动、上网或接送：为您的旅程准备好一切。',
        "button": '看看我能去哪里',
        "legal": '以上为近期发现的价格，每人往返，不含附加服务。价格可能很快变化，预订前请务必核实最终价格。部分链接为合作伙伴链接：Eunodia 可能获得佣金，您无需支付额外费用。',
        "why": '您收到此邮件，是因为您订阅了',
        "contact": '联系方式：',
        "unsubscribe": '退订',
    },
    "ko": {
        "title": 'Eunodia 특가',
        "subject": '{city} {price}부터: 이번 주 최고의 특가',
        "preview": '{city} {price}부터, {origin} 출발',
        "hidden": '{city} {price}부터, 이번 주에 찾은 다른 항공편도 있어요.',
        "headline": '{city} {price}부터',
        "intro": '이번 주 {origin} 출발 최저 왕복 가격을 모았습니다.',
        "far": '장거리 여행',
        "near": '짧은 여행',
        "prepare": '여행 준비하기',
        "prepare_text": '호텔, 액티비티, 인터넷, 공항 이동까지 여행에 필요한 모든 것.',
        "button": '어디로 갈 수 있는지 보기',
        "legal": '최근 확인된 1인 왕복 가격이며 부가 서비스는 포함되지 않습니다. 가격은 빠르게 바뀔 수 있으니 예약 전에 최종 가격을 꼭 확인하세요. 일부 링크는 제휴 링크로, Eunodia가 수수료를 받을 수 있지만 추가 비용은 없습니다.',
        "why": '이 이메일은 다음 사이트에서 구독하셨기 때문에 발송되었습니다:',
        "contact": '문의:',
        "unsubscribe": '구독 취소',
    },
    "hi": {
        "title": 'Eunodia ऑफ़र',
        "subject": '{city} {price} से: इस हफ़्ते के सबसे अच्छे ऑफ़र',
        "preview": '{city} {price} से, {origin} से रवाना',
        "hidden": '{city} {price} से, और इस हफ़्ते मिली दूसरी उड़ानें।',
        "headline": '{city} {price} से',
        "intro": 'इस हफ़्ते {origin} से आने-जाने की सबसे अच्छी कीमतें ये रहीं।',
        "far": 'लंबी यात्राएँ',
        "near": 'छोटी सैर',
        "prepare": 'अपनी यात्रा की योजना बनाएँ',
        "prepare_text": 'होटल, गतिविधियाँ, इंटरनेट या ट्रांसफ़र: आपके ठहरने के लिए सब कुछ तैयार।',
        "button": 'देखें मैं कहाँ जा सकता हूँ',
        "legal": 'हाल में मिली कीमतें, प्रति व्यक्ति और अतिरिक्त शुल्क के बिना: ये तेज़ी से बदल सकती हैं, बुक करने से पहले हमेशा अंतिम कीमत जाँचें। कुछ लिंक पार्टनर लिंक हैं: Eunodia को कमीशन मिल सकता है, आपको कोई अतिरिक्त ख़र्च नहीं।',
        "why": 'आपको यह ईमेल इसलिए मिला है क्योंकि आपने यहाँ सदस्यता ली थी:',
        "contact": 'संपर्क:',
        "unsubscribe": 'सदस्यता छोड़ें',
    },
    "ru": {
        "title": 'Выгодные предложения Eunodia',
        "subject": '{city} от {price}: лучшие предложения недели',
        "preview": '{city} от {price}, вылет {from_origin}',
        "hidden": '{city} от {price} и другие рейсы, найденные на этой неделе.',
        "headline": '{city} от {price}',
        "intro": 'Лучшие цены туда и обратно {from_origin}, которые мы нашли на этой неделе.',
        "far": 'Большие путешествия',
        "near": 'Короткие поездки',
        "prepare": 'Спланируйте поездку',
        "prepare_text": 'Отель, экскурсии, интернет или трансфер: всё готово для вашей поездки.',
        "button": 'Куда можно полететь',
        "legal": 'Цены найдены недавно, за человека и без дополнительных услуг: они могут быстро меняться, поэтому перед бронированием всегда проверяйте итоговую цену. Некоторые ссылки партнёрские: Eunodia может получить комиссию, для вас это бесплатно.',
        "why": 'Вы получили это письмо, потому что подписались на',
        "contact": 'Контакты:',
        "unsubscribe": 'Отписаться',
    },
}


def send_time(now):
    """Prochain jeudi à 8 h, heure de Paris."""
    local = now.astimezone(PARIS)
    days = (3 - local.weekday()) % 7
    moment = datetime.combine(local.date() + timedelta(days=days), time(SEND_HOUR), PARIS)
    return moment + timedelta(days=7) if moment <= local else moment


def sent_week(state, lang):
    """Semaine du dernier numéro programmé pour cette langue (l'ancien champ vaut pour le français)."""
    return state.get("newsletters", {}).get(lang) or (state.get("last_newsletter") if lang == "fr" else None)


def is_due(state, now, lang="fr"):
    """Le mercredi soir ou le jeudi tôt, une seule fois par semaine et par langue."""
    moment = send_time(now)
    left = moment - now.astimezone(PARIS)
    week = moment.strftime("%G-%V")
    return timedelta(minutes=20) < left <= timedelta(hours=14) and sent_week(state, lang) != week


def mailing_lists(settings):
    """Langues envoyées et liste Brevo de chacune. Sans réglage, seul le français part."""
    lists = {lang: int(value) for lang, value in (settings.get("lists") or {}).items() if lang in TEXT}
    return lists or {"fr": settings["list_id"]}


def text_for(lang):
    return TEXT.get(lang) or TEXT[FALLBACK_LANG]


def pick_routes(origin, geo, today):
    """Les meilleurs prix depuis la ville de départ : quelques longs courriers et quelques escapades."""
    start = today + timedelta(days=MIN_DAYS)
    here = geo.get(origin["code"])
    far, near, seen = [], [], set()
    for route in origin["routes"]:
        if route["to"] in seen or date.fromisoformat(route["depart"]) < start or route["to"] not in geo or not here:
            continue
        if not build_site.photo_exists(route["to"]) or route["to"] in SKIPPED:
            continue
        seen.add(route["to"])
        group = far if build_site.distance_km(here, geo[route["to"]]) >= 4000 else near
        group.append(route)
    return far[:FAR], near[:NEAR]


def route_url(origin, route, page):
    if build_site.has_page(page, origin, route):
        return f"{page.site['url']}{page.prefix}{build_site.route_path(origin, route)}"
    return route["link"]


def route_row(origin, route, page):
    city = esc(page.city(route["to"], route["to"]))
    dates = f'{esc(page.day(route["depart"], False))} → {esc(page.day(route["back"]))}'
    return f"""<tr><td style="padding:14px 0;border-bottom:1px solid #e4e4e4;font-family:Helvetica,Arial,sans-serif;">
<a href="{esc(route_url(origin, route, page))}" style="color:#0b0b0b;font-size:18px;font-weight:bold;text-decoration:none;">{city}</a>
<div style="margin-top:3px;color:#6a6a6a;font-size:14px;">{dates} · {esc(page.stops(route))}</div></td>
<td align="right" style="padding:14px 0;border-bottom:1px solid #e4e4e4;font-family:Helvetica,Arial,sans-serif;font-size:20px;font-weight:bold;white-space:nowrap;">{page.euro(route["price"])}</td></tr>"""


def heading(text):
    return f'<h2 style="margin:30px 0 4px;font-family:Helvetica,Arial,sans-serif;font-size:22px;line-height:1.2;color:#0b0b0b;">{esc(text)}</h2>'


def service_cell(url, title, text):
    return f"""<td width="50%" valign="top" style="padding:5px;"><a href="{esc(url)}" style="display:block;padding:15px;background:#f4f4f4;border-radius:12px;color:#0b0b0b;text-decoration:none;font-family:Helvetica,Arial,sans-serif;">
<strong style="display:block;font-size:16px;">{esc(title)}</strong><span style="display:block;margin-top:3px;color:#6a6a6a;font-size:13px;">{esc(text)}</span></a></td>"""


def build_email(page, origin, geo, today):
    text = text_for(page.lang)
    far, near = pick_routes(origin, geo, today)
    if not far and not near:
        return None
    best = (far or near)[0]
    city = page.city(best["to"], best["to"])
    start = START_NAMES.get((page.lang, origin["code"])) or page.city(origin["code"], origin["code"])
    from_start = page.from_city(origin["code"], start)  # russe : « из Москвы »
    price = page.euro(best["price"])
    url = page.site["url"]
    photo = best["to"] if build_site.photo_exists(best["to"]) else "BKK"
    services = build_site.stay_items(page, "")
    cells = [service_cell(u, title, label) for u, title, label, _ in services]
    grid = "".join(f"<tr>{cells[n]}{cells[n + 1]}</tr>" for n in range(0, len(cells) - 1, 2))
    far_block = heading(text["far"]) + f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0">{"".join(route_row(origin, r, page) for r in far)}</table>' if far else ""
    near_block = heading(text["near"]) + f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0">{"".join(route_row(origin, r, page) for r in near)}</table>' if near else ""
    body = f"""<!doctype html><html lang="{page.lang}"{' dir="rtl"' if page.lang in build_site.RTL_LANGS else ''}><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>{esc(text["title"])}</title></head>
<body style="margin:0;padding:0;background:#f4f4f4;">
<div style="display:none;max-height:0;overflow:hidden;">{esc(text["hidden"].format(city=city, price=price))}</div>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#f4f4f4;"><tr><td align="center" style="padding:24px 12px;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="width:100%;max-width:600px;background:#fff;border-radius:18px;overflow:hidden;">
<tr><td style="background:#0b0b0b;padding:20px 28px;"><table role="presentation" cellpadding="0" cellspacing="0"><tr><td style="padding-right:10px;"><img src="{url}assets/icon-192.png" width="30" height="30" alt="" style="display:block;border-radius:15px;"></td><td style="color:#fff;font-family:Helvetica,Arial,sans-serif;font-size:20px;font-weight:bold;">Eunodia</td></tr></table></td></tr>
<tr><td><img src="{url}assets/photos/{photo}.jpg" width="600" alt="{esc(city)}" style="display:block;width:100%;height:auto;"></td></tr>
<tr><td style="padding:30px 30px 34px;">
<h1 style="margin:0 0 10px;font-family:Helvetica,Arial,sans-serif;font-size:30px;line-height:1.2;color:#0b0b0b;">{esc(text["headline"].format(city=city, price=price))}</h1>
<p style="margin:0;font-family:Helvetica,Arial,sans-serif;font-size:16px;line-height:1.5;color:#3f3f3f;">{esc(text["intro"].format(origin=start, from_origin=from_start))}</p>
{far_block}{near_block}
{heading(text["prepare"])}
<p style="margin:0 0 10px;font-family:Helvetica,Arial,sans-serif;font-size:15px;color:#3f3f3f;">{esc(text["prepare_text"])}</p>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin:0 -5px;">{grid}</table>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin-top:26px;"><tr><td align="center" bgcolor="#0b0b0b" style="border-radius:12px;"><a href="{url}{page.prefix}vols/?origin={origin["code"]}" style="display:block;padding:16px 22px;color:#fff;font-family:Helvetica,Arial,sans-serif;font-size:16px;font-weight:bold;text-decoration:none;">{esc(text["button"])}</a></td></tr></table>
</td></tr>
<tr><td style="padding:20px 30px 26px;background:#f4f4f4;font-family:Helvetica,Arial,sans-serif;font-size:12px;line-height:1.5;color:#6a6a6a;">
{esc(text["legal"])}<br><br>
{esc(text["why"])} <a href="{url}{page.prefix}" style="color:#0b0b0b;">eunodia.com</a>. {esc(text["contact"])} <a href="mailto:contact@eunodia.com" style="color:#0b0b0b;">contact@eunodia.com</a>. <a href="{{{{ unsubscribe }}}}" style="color:#0b0b0b;">{esc(text["unsubscribe"])}</a>.
</td></tr></table></td></tr></table></body></html>"""
    return {"subject": text["subject"].format(city=city, price=price),
            "preview": text["preview"].format(city=city, price=price, origin=start, from_origin=from_start), "html": body}


def brevo(path, key, body):
    request = urllib.request.Request(f"{BREVO}{path}", data=json.dumps(body).encode(), method="POST",
                                     headers={"api-key": key, "content-type": "application/json", "accept": "application/json"})
    with urllib.request.urlopen(request, timeout=45) as response:
        text = response.read()
    return json.loads(text) if text else {}


def load_page(config, lang):
    site = dict(config["site"])
    after = site["url"].split("//", 1)[1]
    site["root"] = "/" + after.split("/", 1)[1] if "/" in after else "/"
    names = build_site.clean_names(json.loads((ROOT / "docs/assets/names.json").read_text()))
    page = build_site.Page(site, lang, names.get(lang) or names[FALLBACK_LANG])
    cases = ROOT / "docs/assets/cases.json"
    page.cases = (json.loads(cases.read_text()) if cases.exists() else {}).get(lang, {})
    return page, names["fr"]


def prepare(config, today, lang):
    page, world_names = load_page(config, lang)
    geo = json.loads((ROOT / "docs/assets/geo.json").read_text())
    world = {o["code"]: o for o in build_site.load_world(world_names) if o["routes"]}
    # ville de la langue, puis sa ville de secours (comme sur le site), puis Paris
    codes = (ORIGINS.get(lang, ORIGINS[FALLBACK_LANG]), build_site.BACKUP_ORIGIN.get(lang), "PAR")
    origin = next((world[code] for code in codes if code in world), None)
    return build_email(page, origin, geo, today) if origin else None


def main():
    config = tomllib.loads((ROOT / "config.toml").read_text())
    now = datetime.now(PARIS)
    if "--preview" in sys.argv:
        for lang in TEXT:
            email = prepare(config, now.date(), lang)
            if not email:
                print(f"{lang} : aucune offre.")
                continue
            name = "newsletter-apercu.html" if lang == "fr" else f"newsletter-apercu-{lang}.html"
            (ROOT / name).write_text(email["html"])
            print(f"{lang} : {email['subject']}")
        return 0
    key = os.environ.get("BREVO_API_KEY")
    state_path = ROOT / "data" / "state.json"
    state = json.loads(state_path.read_text()) if state_path.exists() else {}
    if not key:
        print("Newsletter : clé Brevo absente.")
        return 0
    settings = config["newsletter"]
    moment = send_time(now)
    failed = False
    for lang, list_id in mailing_lists(settings).items():
        if not is_due(state, now, lang):
            print(f"Newsletter {lang} : pas encore le moment.")
            continue
        email = prepare(config, now.date(), lang)
        if not email:
            print(f"Newsletter {lang} : aucune offre, envoi annulé.", file=sys.stderr)
            failed = True
            continue
        try:
            result = brevo("/emailCampaigns", key, {
                "name": f"Bons plans du {moment:%d/%m/%Y} ({lang})", "subject": email["subject"], "previewText": email["preview"],
                "sender": {"name": "Eunodia", "email": settings["sender"]}, "htmlContent": email["html"],
                "recipients": {"listIds": [list_id]}, "scheduledAt": moment.isoformat(),
            })
        except urllib.error.HTTPError as error:
            print(f"Newsletter {lang} : Brevo a refusé ({error.code}) : {error.read()[:300].decode(errors='replace')}", file=sys.stderr)
            failed = True
            continue
        week = moment.strftime("%G-%V")
        state.setdefault("newsletters", {})[lang] = week
        if lang == "fr":
            state["last_newsletter"] = week
        state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2))
        print(f"Newsletter {lang} programmée pour {moment:%d/%m/%Y %H:%M} (campagne {result.get('id')}).")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
