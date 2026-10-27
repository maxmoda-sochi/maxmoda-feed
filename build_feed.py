#!/usr/bin/env python3
"""Собирает YML-фиды товаров maxmoda.ru для Яндекс Бизнеса.

Берёт товары из каталога Тильды (тот же источник, что и сайт) и пишет два файла:
  public/marella.yml  — товары бренда Marella (карточка Marella, ТРЦ «Море Молл»)
  public/maxmoda.yml  — остальные бренды (карточка Max Moda, Навагинская 3/4)

В фид попадают только товары в наличии и с фото. Ссылки ведут на карточки
моделей на сайте с UTM-метками, чтобы переходы было видно в Метрике.

Запуск:  python3 build_feed.py              (берёт данные с сайта)
         python3 build_feed.py --from-json sample.json   (офлайн-проверка)
"""
import argparse
import json
import sys
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from xml.sax.saxutils import escape

API = ("https://store.tildaapi.com/api/getproductslist/"
       "?storepartuid=138778991497&recid=179055022&getparts=true&getoptions=true"
       "&flag_root=withroot&size=100&slice={slice}&c={ts}")
SITE = "https://www.maxmoda.ru"

# Разделы-«витрины», которые не являются категорией товара
SKIP_PARTS = {138778991497, 796453380076, 562760764911, 729257145111, 460713276991,
              605194389841, 544866648962, 533599596383}
# Подраздел -> родительский раздел (Обувь / Сумки / Аксессуары / Одежда)
SHOES, BAGS, ACC, RTW = 429066460061, 105675765319, 865956359370, 714592167323
PARENT = {
    987369287300: SHOES, 799178449235: SHOES, 829798581845: SHOES, 706279535813: SHOES,
    347692689411: SHOES, 545348831835: SHOES, 252080828313: SHOES, 580474688641: SHOES,
    309171220231: SHOES, 626613605801: SHOES,
    579235748529: ACC, 173675415474: ACC, 455989322416: ACC,
    641197643272: BAGS,
    303438718417: RTW, 412746386786: RTW, 541473689359: RTW, 193154863233: RTW,
    376170903042: RTW, 300168644452: RTW, 843191618848: RTW, 597629182168: RTW,
    526246303753: RTW, 117570029841: RTW, 528131270120: RTW, 107768038219: RTW,
    885701200351: RTW, 235608726861: RTW,
}
BRAND_NAMES = {"PREMIATA": "Premiata", "DOUCAL'S": "Doucal's", "PAIGE": "Paige", "MARELLA": "Marella"}

FEEDS = [
    # (файл, название магазина, utm_campaign, фильтр по бренду)
    ("marella.yml", "Marella", "marella", lambda b: b == "MARELLA"),
    ("maxmoda.yml", "Max Moda", "maxmoda_navaginskaya", lambda b: b != "MARELLA"),
]
MIN_PRODUCTS = 20  # если с сайта пришло меньше — считаем сбоем и ничего не публикуем


def fetch_all():
    products, parts, slice_no = [], [], 1
    while True:
        url = API.format(slice=slice_no, ts=int(time.time() * 1000))
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (maxmoda-feed)",
            "Referer": SITE + "/", "Origin": SITE,
        })
        for attempt in range(4):
            try:
                with urllib.request.urlopen(req, timeout=60) as r:
                    data = json.load(r)
                break
            except Exception as e:  # noqa: BLE001
                if attempt == 3:
                    raise
                print(f"retry slice {slice_no}: {e}", file=sys.stderr)
                time.sleep(5 * (attempt + 1))
        if not parts and data.get("parts"):
            parts = data["parts"]
        page = data.get("products") or []
        products += page
        nxt = data.get("nextslice")
        if not nxt or not page:
            break
        slice_no = nxt
        if slice_no > 50:
            break
    return products, parts


def as_list(v):
    if isinstance(v, list):
        return v
    if not v:
        return []
    try:
        return json.loads(v)
    except (TypeError, ValueError):
        return []


def num(v):
    try:
        return float(str(v).replace(" ", "").replace(",", ".")) if str(v).strip() else 0.0
    except ValueError:
        return 0.0


def in_stock(q):
    return str(q).strip() == "" or num(q) > 0


def build_offer(p, campaign, part_titles, used_cats):
    editions = as_list(p.get("editions"))
    if editions:
        live = [e for e in editions if in_stock(e.get("quantity", ""))]
        if not live:
            return None
    else:
        if not in_stock(p.get("quantity", "")):
            return None
        live = []
    pics = [g.get("img") for g in as_list(p.get("gallery")) if g.get("img")]
    if not pics:
        return None

    parts = [u for u in as_list(p.get("partuids")) if u not in SKIP_PARTS]
    cat = next((u for u in parts if u in PARENT), parts[0] if parts else RTW)
    used_cats.add(cat)
    if cat in PARENT:
        used_cats.add(PARENT[cat])

    price = round(num(p.get("price")))
    old = max([round(num(p.get("priceold")))] + [round(num(e.get("priceold"))) for e in live] + [0])
    if price <= 0:
        return None

    brand_raw = (p.get("brand") or "").strip()
    brand = BRAND_NAMES.get(brand_raw.upper(), brand_raw)
    sizes = list(dict.fromkeys(str(e["Размер"]) for e in live if e.get("Размер")))
    colors = list(dict.fromkeys(str(e["Цвет"]) for e in editions if e.get("Цвет")))
    chars = [c for c in as_list(p.get("characteristics")) if c.get("title") and c.get("value")]

    url = p["url"].replace("http://", "https://", 1)
    url += ("&" if "?" in url else "?") + (
        f"utm_source=yandex_business&utm_medium=organic&utm_campaign={campaign}")

    desc = [p.get("descr") or p.get("title")]
    if brand:
        desc.append(f"Бренд: {brand}")
    desc += [f"{c['title']}: {c['value']}" for c in chars]
    if sizes:
        desc.append("Размеры в наличии: " + ", ".join(sizes))
    desc.append("Примерка в бутике, бесплатная доставка по России")

    x = [f'<offer id="{p["uid"]}" available="true">',
         f"<url>{escape(url)}</url>", f"<price>{price}</price>"]
    if old > price:
        x.append(f"<oldprice>{old}</oldprice>")
    x += ["<currencyId>RUR</currencyId>", f"<categoryId>{cat}</categoryId>"]
    x += [f"<picture>{escape(i)}</picture>" for i in pics[:5]]
    x.append(f"<name>{escape(p['title'])}</name>")
    if brand:
        x.append(f"<vendor>{escape(brand)}</vendor>")
    x.append(f"<description>{escape('. '.join(desc))}.</description>")
    if colors:
        x.append(f'<param name="Цвет">{escape(", ".join(colors))}</param>')
    if sizes:
        x.append(f'<param name="Размер">{escape(", ".join(sizes))}</param>')
    x += [f'<param name="{escape(c["title"])}">{escape(str(c["value"]))}</param>' for c in chars]
    x.append("</offer>")
    return "".join(x)


def build_feed(products, part_titles, shop_name, campaign):
    used_cats, offers = set(), []
    for p in products:
        o = build_offer(p, campaign, part_titles, used_cats)
        if o:
            offers.append(o)
    cats = "".join(
        f'<category id="{u}"' + (f' parentId="{PARENT[u]}"' if u in PARENT else "")
        + f">{escape(part_titles.get(u, 'Товары'))}</category>"
        for u in sorted(used_cats))
    date = datetime.now(timezone(timedelta(hours=3))).strftime("%Y-%m-%d %H:%M")
    xml = ('<?xml version="1.0" encoding="UTF-8"?>\n'
           f'<yml_catalog date="{date}"><shop><name>{escape(shop_name)}</name>'
           f"<company>Max Moda</company><url>{SITE}</url>"
           '<currencies><currency id="RUR" rate="1"/></currencies>'
           f"<categories>{cats}</categories><offers>\n" + "\n".join(offers) +
           "\n</offers></shop></yml_catalog>\n")
    return xml, len(offers)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--from-json", help="взять товары из файла вместо сайта (для проверки)")
    ap.add_argument("--out", default="public")
    a = ap.parse_args()

    if a.from_json:
        data = json.loads(Path(a.from_json).read_text(encoding="utf-8"))
        products, parts = data["products"], data.get("parts", [])
        min_products = 1
    else:
        products, parts = fetch_all()
        min_products = MIN_PRODUCTS
    if len(products) < min_products:
        sys.exit(f"Слишком мало товаров с сайта ({len(products)}), фид не обновляю")

    part_titles = {p["uid"]: p["title"] for p in parts}
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    summary = []
    for fname, shop, campaign, keep in FEEDS:
        subset = [p for p in products if keep((p.get("brand") or "").strip().upper())]
        xml, n = build_feed(subset, part_titles, shop, campaign)
        if n == 0:
            sys.exit(f"{fname}: 0 товаров — фид не обновляю")
        (out / fname).write_text(xml, encoding="utf-8")
        summary.append(f"{fname}: {n}")
    (out / "index.html").write_text(
        "<!doctype html><meta charset='utf-8'><title>Max Moda — фиды</title>"
        "<p>Фиды товаров maxmoda.ru для Яндекс Бизнеса:</p><ul>"
        "<li><a href='marella.yml'>marella.yml</a></li>"
        "<li><a href='maxmoda.yml'>maxmoda.yml</a></li></ul>"
        f"<p>Обновлено: {datetime.now(timezone(timedelta(hours=3))):%Y-%m-%d %H:%M} МСК. "
        f"{'; '.join(summary)}</p>\n", encoding="utf-8")
    print(f"Товаров с сайта: {len(products)}. " + "; ".join(summary))


if __name__ == "__main__":
    main()
