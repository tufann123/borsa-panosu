#!/usr/bin/env python3
"""
Borsa Panosu - gunluk otomatik F/K, PD/DD, temettu verimi, teknik trend ve
"ucuz/notr/pahali" siniflandirmasi guncelleyicisi.

Bu script Claude'u KULLANMAZ. Tamamen GitHub Actions runner'i uzerinde,
ucretsiz/anahtarsiz iki kaynaktan veri ceker:
  1) isyatirim.com.tr'nin "Sirket Karti" sayfasi (duz HTML, JS calistirmaya
     gerek yok) -> F/K, PD/DD ("Cari Degerler" tablosu) ve temettu verimi
     ("Temettu Tahmin" tablosunda secili/cari yil sutunu).
  2) Yahoo Finance'in herkese acik chart endpoint'i (refresh_prices.py'nin
     kullandigi ayni endpoint, sadece range=6mo) -> son ~6 aylik kapanis
     fiyatlari -> MA20/MA52 hesaplanip teknik trend belirlenir.

"Ucuz/notr/pahali" (val) siniflandirmasi tamamen deterministik bir
formuldur (medyan F/K'ya gore): AI/Claude gerekmez, bkz. classify_val().

Haberler, KAP, sektor, "Claude'un degerlendirmesi" gibi alanlara DOKUNMAZ.
divCount5y (son 5 yilda kac kez temettu odendigi) icin guvenilir/ucretsiz
bir kaynak bulunamadigindan bu alana DOKUNULMAZ (son bilinen deger kalir).
"""
import json
import re
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone, timedelta

FILE = "index.html"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36"}

TICKERS = [
    "AEFES", "AKBNK", "ASELS", "ASTOR", "BIMAS", "DSTKF", "EKGYO", "ENKAI", "EREGL", "FROTO",
    "GARAN", "GUBRF", "ISCTR", "KCHOL", "KRDMD", "MGROS", "PETKM", "PGSUS", "SAHOL", "SASA",
    "SISE", "TAVHL", "TCELL", "THYAO", "TOASO", "TRALT", "TTKOM", "TUPRS", "VAKBN", "YKBNK",
]


def fetch_text(url, timeout=20):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", errors="replace")


def fetch_json(url, timeout=15):
    return json.loads(fetch_text(url, timeout=timeout))


def tr_to_float(s):
    """'5,6' -> 5.6 ; '1.234,5' -> 1234.5 ; '-' veya 'A/D' -> None"""
    s = s.strip()
    if not s or s in ("-", "A/D", "n.a.", "N/A"):
        return None
    s = s.replace(".", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def fetch_pe_pb(ticker):
    """isyatirim 'Cari Degerler' tablosundan F/K ve PD/DD ceker."""
    url = f"https://www.isyatirim.com.tr/tr-tr/analiz/hisse/Sayfalar/sirket-karti.aspx?hisse={ticker}"
    html = fetch_text(url)
    m = re.search(r'<h3>Cari De.erler\*?</h3>.*?<table>(.*?)</table>', html, re.S)
    if not m:
        return None, None
    block = m.group(1)
    rows = re.findall(r'<th>(.*?)</th>\s*<td>(.*?)</td>', block, re.S)
    vals = {}
    for label, val in rows:
        label = re.sub('<[^>]+>', '', label).strip()
        val = re.sub('<[^>]+>', '', val).strip()
        vals[label] = val
    pe = tr_to_float(vals.get("F/K", ""))
    pb = tr_to_float(vals.get("PD/DD", ""))
    return pe, pb


def fetch_div_yield(ticker):
    """isyatirim 'Temettu Tahmin' tablosunda secili (cari) yila ait
    temettu verim (%) sutununu ceker."""
    url = f"https://www.isyatirim.com.tr/tr-tr/analiz/hisse/Sayfalar/sirket-karti.aspx?hisse={ticker}"
    html = fetch_text(url)
    sel = re.search(r'ddlTemettuTahminYil[^>]*>.*?<option selected="selected" value="(\d)">', html, re.S)
    if not sel:
        return None
    year_class = sel.group(1)
    blk = re.search(r'<!--[^>]*Verim-->(.*?)</td>', html, re.S)
    if not blk:
        return None
    m = re.search(r'temettuvarcol ' + re.escape(year_class) + r'">([^<]*)</div>', blk.group(1))
    if not m:
        return None
    return tr_to_float(m.group(1))


def fetch_trend(ticker):
    """Yahoo Finance chart endpoint'inden son ~6 aylik kapanislari cekip
    MA20/MA52'ye gore teknik trend hesaplar."""
    sym = ticker + ".IS"
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}?interval=1d&range=6mo"
    data = fetch_json(url)
    result = data["chart"]["result"][0]
    closes = result["indicators"]["quote"][0]["close"]
    closes = [c for c in closes if c is not None]
    if len(closes) < 52:
        return None
    last = closes[-1]
    ma20 = sum(closes[-20:]) / 20.0
    ma52 = sum(closes[-52:]) / 52.0
    above20 = last > ma20
    above52 = last > ma52
    if above20 and above52:
        return "yukselis"
    if (not above20) and (not above52):
        return "dususte"
    return "notr"


def classify_val(pe, median):
    """Medyan F/K'ya gore deterministik ucuz/notr/pahali/na siniflandirmasi.
    (Bu, projenin bastan beri kullandigi ayni formuldur - AI gerektirmez.)"""
    if pe is None or median is None:
        return "na"
    if pe < median * 0.7:
        return "ucuz"
    if pe > median * 1.3:
        return "pahali"
    return "notr"


def patch_field_num(html, ticker, field, value):
    pattern = re.compile(r'(\{t:"' + re.escape(ticker) + r'"[^\n]*?' + re.escape(field) + r':)(null|-?[\d.]+)')
    repl = f"null" if value is None else f"{value:.1f}" if field in ("pe", "pb") else f"{value:.2f}"
    new_html, n = pattern.subn(lambda m: m.group(1) + repl, html, count=1)
    return new_html, n


def patch_field_str(html, ticker, field, value):
    pattern = re.compile(r'(\{t:"' + re.escape(ticker) + r'"[^\n]*?' + re.escape(field) + r':")(ucuz|notr|pahali|na|yukselis|dususte)(")')
    new_html, n = pattern.subn(lambda m: m.group(1) + value + m.group(3), html, count=1)
    return new_html, n


def main():
    with open(FILE, "r", encoding="utf-8") as f:
        html = f.read()

    pe_map, pb_map, div_map, trend_map = {}, {}, {}, {}
    ok, failed = [], []
    for t in TICKERS:
        try:
            pe, pb = fetch_pe_pb(t)
            pe_map[t] = pe
            pb_map[t] = pb
        except Exception as e:
            print(f"  [F/K-PD/DD atlandi] {t}: {e}", file=sys.stderr)
        try:
            div_map[t] = fetch_div_yield(t)
        except Exception as e:
            print(f"  [temettu atlandi] {t}: {e}", file=sys.stderr)
        try:
            tr = fetch_trend(t)
            if tr:
                trend_map[t] = tr
        except Exception as e:
            print(f"  [trend atlandi] {t}: {e}", file=sys.stderr)
        if t in pe_map or t in div_map or t in trend_map:
            ok.append(t)
        else:
            failed.append(t)
        time.sleep(0.4)

    # medyan F/K (yalnizca bu turda F/K verisi bulunan hisseler uzerinden)
    pe_values = sorted([v for v in pe_map.values() if v is not None])
    if pe_values:
        n = len(pe_values)
        median = (pe_values[(n - 1) // 2] + pe_values[n // 2]) / 2.0
    else:
        median = None

    changed = []
    for t in TICKERS:
        touched = False
        if t in pe_map:
            html, n = patch_field_num(html, t, "pe", pe_map[t])
            touched = touched or n > 0
        if t in pb_map:
            html, n = patch_field_num(html, t, "pb", pb_map[t])
            touched = touched or n > 0
        if t in div_map:
            html, n = patch_field_num(html, t, "div", div_map[t])
            touched = touched or n > 0
        if t in trend_map:
            html, n = patch_field_str(html, t, "trend", trend_map[t])
            touched = touched or n > 0
        if t in pe_map:
            val = classify_val(pe_map[t], median)
            html, n = patch_field_str(html, t, "val", val)
            touched = touched or n > 0
        if touched:
            changed.append(t)

    ist = datetime.now(timezone.utc) + timedelta(hours=3)
    if changed:
        label = (
            f"F/K, PD/DD, temettü verimi ve teknik trend GitHub Actions ile {ist.strftime('%d.%m %H:%M')} "
            f"(İstanbul) itibarıyla otomatik güncellendi ({len(changed)}/{len(TICKERS)} hisse, Claude kullanılmadan). "
            f"\"Ucuz/pahalı\" etiketi güncel medyan F/K'ya ({median:.1f}x)" if median else
            f"F/K, PD/DD, temettü verimi ve teknik trend GitHub Actions ile {ist.strftime('%d.%m %H:%M')} "
            f"(İstanbul) itibarıyla otomatik güncellendi ({len(changed)}/{len(TICKERS)} hisse, Claude kullanılmadan)."
        )
        if median:
            label += " göre yeniden hesaplandı."
    else:
        label = (
            f"Temel veri kaynağına {ist.strftime('%d.%m %H:%M')} (İstanbul) itibarıyla ulaşılamadı, "
            f"bu deneme atlandı; bir sonraki günlük denemede tekrar denenecek."
        )
    pat = re.compile(r'(<span id="fundAutoText"[^>]*>)[^<]*(</span>)')
    html, n = pat.subn(lambda m: m.group(1) + label + m.group(2), html, count=1)
    if n == 0:
        print("UYARI: #fundAutoText elemani bulunamadi.", file=sys.stderr)

    with open(FILE, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"Guncellenen hisseler ({len(changed)}): {changed}")
    print(f"Medyan F/K: {median}")
    if failed:
        print(f"Hicbir veri alinamayan hisseler ({len(failed)}): {failed}")


if __name__ == "__main__":
    main()
