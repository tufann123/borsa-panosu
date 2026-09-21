#!/usr/bin/env python3
"""
Borsa Panosu - haber ve KAP akisini birkac saatte bir otomatik guncelleyen
script.

Bu script Claude'u KULLANMAZ ve hicbir AI ozeti/yorumu YAZMAZ - yalnizca
gercek, herkese acik iki kaynaktan HAM baslik/metin/link/tarih ceker:

  1) Anadolu Ajansi Ekonomi RSS (aa.com.tr/tr/rss/default?cat=ekonomi):
     genel piyasa gundemi + her hisse icin sirket adi anahtar kelime
     eslesmesiyle (basit substring arama, AI degil) hisseye ozel haberler.
  2) Midas'in "KAP Haberleri" sayfasi (getmidas.com/kap-haberleri/):
     KAP'a yansimis gercek sirket bildirimlerinin duz HTML listesi
     (sunucu tarafinda render ediliyor, JS calistirmaya gerek yok).

Bir hisse icin haber bulunamazsa news:[] birakilir - sayfa zaten bu
durumda otomatik olarak genel gundem haberini gosteriyor (fallbackNews).
"""
import json
import re
import sys
import urllib.request
from datetime import datetime, timezone, timedelta
from html import unescape

FILE = "index.html"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

# ticker -> haber baslik/metin eslestirmesi icin anahtar kelime(ler)
KEYWORDS = {
    "AEFES": ["Anadolu Efes"],
    "AKBNK": ["Akbank"],
    "ASELS": ["Aselsan"],
    "ASTOR": ["Astor Enerji"],
    "BIMAS": ["BİM Birleşik", "BİM "],
    "DSTKF": ["Destek Finans", "Destek Faktoring"],
    "EKGYO": ["Emlak Konut"],
    "ENKAI": ["Enka İnşaat", "Enka'"],
    "EREGL": ["Ereğli Demir", "Erdemir"],
    "FROTO": ["Ford Otosan"],
    "GARAN": ["Garanti BBVA", "Garanti Bankası"],
    "GUBRF": ["Gübre Fabrikaları"],
    "ISCTR": ["İş Bankası"],
    "KCHOL": ["Koç Holding"],
    "KRDMD": ["Kardemir"],
    "MGROS": ["Migros"],
    "PETKM": ["Petkim"],
    "PGSUS": ["Pegasus"],
    "SAHOL": ["Sabancı Holding"],
    "SASA": ["Sasa Polyester", "SASA "],
    "SISE": ["Şişecam"],
    "TAVHL": ["TAV Havalimanları", "TAV'"],
    "TCELL": ["Turkcell"],
    "THYAO": ["Türk Hava Yolları", "THY "],
    "TOASO": ["Tofaş"],
    "TRALT": ["Türk Altın İşletmeleri"],
    "TTKOM": ["Türk Telekom"],
    "TUPRS": ["Tüpraş"],
    "VAKBN": ["VakıfBank", "Vakıfbank", "Vakıf Bank"],
    "YKBNK": ["Yapı Kredi", "YapıKredi"],
}


def fetch_text(url, timeout=20):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", errors="replace")


def parse_aa_rss(xml_text):
    items = []
    for m in re.finditer(r'<item>(.*?)</item>', xml_text, re.S):
        block = m.group(1)
        title_m = re.search(r'<title>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</title>', block, re.S)
        link_m = re.search(r'<link>(.*?)</link>', block, re.S)
        date_m = re.search(r'<pubDate>(.*?)</pubDate>', block, re.S)
        if not (title_m and link_m):
            continue
        title = unescape(title_m.group(1)).strip()
        link = unescape(link_m.group(1)).strip()
        date_raw = date_m.group(1).strip() if date_m else ""
        date_label = date_raw
        try:
            dt = datetime.strptime(date_raw[:25], "%a, %d %b %Y %H:%M:%S")
            date_label = dt.strftime("%d %B %Y").replace(
                "January", "Ocak").replace("February", "Şubat").replace("March", "Mart") \
                .replace("April", "Nisan").replace("May", "Mayıs").replace("June", "Haziran") \
                .replace("July", "Temmuz").replace("August", "Ağustos").replace("September", "Eylül") \
                .replace("October", "Ekim").replace("November", "Kasım").replace("December", "Aralık")
        except Exception:
            pass
        items.append({"title": title, "url": link, "src": "Anadolu Ajansı", "date": date_label})
    return items


def parse_kap_cards(html):
    items = []
    for m in re.finditer(r'<div class="kap-card__time">([^<]*)</div>.*?<p>(.*?)</p>', html, re.S):
        when = unescape(m.group(1)).strip()
        text = unescape(re.sub('<[^>]+>', '', m.group(2))).strip()
        if not text:
            continue
        if "," in text:
            head, rest = text.split(",", 1)
        else:
            head, rest = "", text
        items.append({"c": "KAP", "t": head.strip(), "d": rest.strip(), "when": when})
    return items


def js_str(s):
    return json.dumps(s, ensure_ascii=False)


def patch_stock_news(html, ticker, news_items):
    """stocks dizisindeki ilgili hissenin news:[...] alanini degistirir.
    news alani bos ([]) veya birden fazla ogeli olabilir, tek satirda veya
    coklu satirda olabilir - bu yuzden {t:"TICKER" ile baslayip ilk ust
    seviye news:[ ... ] blogunu (kose parantez dengesiyle) buluyoruz."""
    anchor = html.find('{t:"' + ticker + '"')
    if anchor == -1:
        return html, 0
    news_key = html.find("news:[", anchor)
    obj_end_bracket = html.find("]}", anchor)
    # news:[ ... ] bloğunun dengeli sonunu bul
    start = news_key + len("news:[")
    depth = 1
    i = start
    while i < len(html) and depth > 0:
        if html[i] == "[":
            depth += 1
        elif html[i] == "]":
            depth -= 1
        i += 1
    end = i  # html[end-1] == ']'
    if not news_items:
        new_arr = "[]"
    else:
        parts = []
        for n in news_items[:3]:
            parts.append(
                "{title:" + js_str(n["title"]) + ", url:" + js_str(n["url"]) +
                ", src:" + js_str(n["src"]) + ", date:" + js_str(n["date"]) + "}"
            )
        new_arr = "[" + ",".join(parts) + "]"
    new_html = html[:news_key] + "news:" + new_arr + html[end:]
    return new_html, 1


def patch_kap_array(html, items):
    arr_match = re.search(r'var kap\s*=\s*\[(.*?)\n  \];', html, re.S)
    if not arr_match:
        return html, 0
    parts = []
    for it in items[:8]:
        parts.append(
            "{c:" + js_str(it["c"]) + ", t:" + js_str(it["t"]) +
            ", d:" + js_str(it["d"]) + ", when:" + js_str(it["when"]) + "}"
        )
    new_block = "\n    " + ",\n    ".join(parts) + "\n  "
    new_html = html[:arr_match.start(1)] + new_block + html[arr_match.end(1):]
    return new_html, 1


def main():
    with open(FILE, "r", encoding="utf-8") as f:
        html = f.read()

    ok_parts, fail_parts = [], []

    aa_items = []
    try:
        xml = fetch_text("https://www.aa.com.tr/tr/rss/default?cat=ekonomi")
        aa_items = parse_aa_rss(xml)
        ok_parts.append(f"AA Ekonomi ({len(aa_items)} haber)")
    except Exception as e:
        fail_parts.append("AA Ekonomi RSS")
        print(f"  [atlandi] AA RSS: {e}", file=sys.stderr)

    matched_count = 0
    for ticker, kws in KEYWORDS.items():
        hits = []
        for it in aa_items:
            hay = it["title"]
            if any(kw.lower() in hay.lower() for kw in kws):
                hits.append(it)
        if hits:
            html, n = patch_stock_news(html, ticker, hits)
            if n:
                matched_count += 1

    try:
        kap_html = fetch_text("https://www.getmidas.com/kap-haberleri/")
        kap_items = parse_kap_cards(kap_html)
        if kap_items:
            html, n = patch_kap_array(html, kap_items)
            ok_parts.append(f"KAP ({len(kap_items)} bildirim)")
        else:
            fail_parts.append("KAP (bos liste)")
    except Exception as e:
        fail_parts.append("KAP (Midas)")
        print(f"  [atlandi] KAP: {e}", file=sys.stderr)

    ist = datetime.now(timezone.utc) + timedelta(hours=3)
    ts_label = ist.strftime("%d.%m %H:%M")
    if ok_parts:
        label = (
            f"Haberler ve KAP bildirimleri GitHub Actions ile {ts_label} (İstanbul) itibarıyla "
            f"otomatik güncellendi ({', '.join(ok_parts)}; {matched_count}/30 hisseye özel haber eşleşti; "
            f"Claude kullanılmadan, özet/yorum içermez, ham başlık ve linklerdir)."
        )
        if fail_parts:
            label += f" Alınamayan: {', '.join(fail_parts)}."
    else:
        label = f"Haber/KAP kaynaklarına {ts_label} (İstanbul) itibarıyla ulaşılamadı, bu deneme atlandı."

    pat = re.compile(r'(<span id="newsAutoText"[^>]*>)[^<]*(</span>)')
    html, n = pat.subn(lambda m: m.group(1) + label + m.group(2), html, count=1)
    if n == 0:
        print("UYARI: #newsAutoText elemani bulunamadi.", file=sys.stderr)

    with open(FILE, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"Eslesen hisse sayisi: {matched_count}/30")
    print(f"Basarili: {ok_parts}")
    if fail_parts:
        print(f"Basarisiz: {fail_parts}")


if __name__ == "__main__":
    main()
