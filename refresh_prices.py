#!/usr/bin/env python3
"""
Borsa Panosu - saatlik otomatik BIST fiyat/% degisim guncelleyici.
Bu script Claude'u KULLANMAZ; tamamen GitHub Actions runner'i uzerinde,
ucretsiz/anahtarsiz bir public API'den (Yahoo Finance'in herkese acik
chart endpoint'i) veri cekip index.html icindeki SADECE BIST30
hisselerinin fiyat (p) ve gunluk % degisim (chg) alanlarini gunceller.

Bitcoin/Altin/Gumus zaten sayfadaki "Guncelle" butonuyla tarayicidan
anlik cekilebiliyor, o yuzden bu script onlara dokunmuyor.

Haberler, KAP, F/K, PD/DD, sektor, temettu, "Claude'un degerlendirmesi"
gibi arastirma gerektiren alanlara DA DOKUNMAZ - onlar Claude'un ayri,
gunde iki kez calisan zamanlanmis gorevi tarafindan guncellenmeye
devam eder.
"""
import json
import re
import sys
import time
import urllib.request
from datetime import datetime, timezone, timedelta

FILE = "index.html"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

TICKERS = [
    "AEFES", "AKBNK", "ASELS", "ASTOR", "BIMAS", "DSTKF", "EKGYO", "ENKAI", "EREGL", "FROTO",
    "GARAN", "GUBRF", "ISCTR", "KCHOL", "KRDMD", "MGROS", "PETKM", "PGSUS", "SAHOL", "SASA",
    "SISE", "TAVHL", "TCELL", "THYAO", "TOASO", "TRALT", "TTKOM", "TUPRS", "VAKBN", "YKBNK",
]


def fetch_json(url, timeout=12):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def fetch_stock_quotes():
    """Her hisse icin Yahoo Finance'in herkese acik chart endpoint'inden
    anlik fiyat + onceki kapanisa gore % degisim ceker. Bir hisse
    basarisiz olursa atlanir (grace-degrade), is iptal edilmez."""
    out = {}
    failed = []
    for t in TICKERS:
        sym = t + ".IS"
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}?interval=1d&range=1d"
        try:
            data = fetch_json(url)
            meta = data["chart"]["result"][0]["meta"]
            price = meta.get("regularMarketPrice")
            prev = meta.get("previousClose") or meta.get("chartPreviousClose")
            if price is None or not prev:
                failed.append(t)
                continue
            chg = (price - prev) / prev * 100.0
            out[t] = (float(price), float(chg))
        except Exception as e:
            failed.append(t)
            print(f"  [atlandi] {t}: {e}", file=sys.stderr)
        time.sleep(0.15)
    return out, failed


def main():
    with open(FILE, "r", encoding="utf-8") as f:
        html = f.read()

    quotes, failed = fetch_stock_quotes()
    changed = []
    for t, (price, chg) in quotes.items():
        pattern = re.compile(
            r'(\{t:"' + re.escape(t) + r'"[^\n]*?p:)-?[\d.]+(, chg:)-?[\d.]+'
        )
        repl = rf"\g<1>{price:.2f}\g<2>{chg:.2f}"
        new_html, n = pattern.subn(repl, html, count=1)
        if n:
            html = new_html
            changed.append(t)

    ist = datetime.now(timezone.utc) + timedelta(hours=3)
    if changed:
        label = (
            f"BIST fiyatları GitHub Actions ile {ist.strftime('%H:%M')} (İstanbul) itibarıyla "
            f"otomatik güncellendi ({len(changed)}/{len(TICKERS)} hisse, Claude kullanılmadan). "
            f"F/K, haberler, KAP ve diğer alanlar son Claude taramasındaki gibidir."
        )
    else:
        label = (
            f"BIST fiyat kaynağına {ist.strftime('%H:%M')} (İstanbul) itibarıyla ulaşılamadı, "
            f"bu saatlik deneme atlandı; bir sonraki saatte tekrar denenecek."
        )
    pat = re.compile(r'(<span id="priceAutoText"[^>]*>)[^<]*(</span>)')
    html, n = pat.subn(lambda m: m.group(1) + label + m.group(2), html, count=1)
    if n == 0:
        print("UYARI: #priceAutoText elemani bulunamadi.", file=sys.stderr)

    with open(FILE, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"Guncellenen hisseler ({len(changed)}): {changed}")
    if failed:
        print(f"Alinamayan hisseler ({len(failed)}): {failed}")


if __name__ == "__main__":
    main()
