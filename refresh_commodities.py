#!/usr/bin/env python3
"""
Borsa Panosu - emtia (Gram Altin, Ons Altin, Gumus, Brent Petrol) ve
Bitcoin verilerini birkac saatte bir otomatik guncelleyen script.

Bu script Claude'u KULLANMAZ. Tamamen ucretsiz/anahtarsiz, CORS/API
kisitlamasi olmayan public kaynaklardan veri ceker (sayfadaki "Guncelle"
butonunun tarayicidan kullandigi ayni kaynaklar + Brent icin Yahoo
Finance):
  - Ons Altin (XAU), Gumus (XAG): gold-api.com
  - USD/TRY kuru (Gram Altin'i TL'ye cevirmek icin): open.er-api.com
  - Brent Petrol (BZ=F): Yahoo Finance chart endpoint (onceki kapanisa
    gore % degisim meta icinde hazir geliyor)
  - Bitcoin (USD/TRY, 24 saatlik ve 7 gunluk % degisim): CoinGecko

Trend (yukselis/dususte/notr) Gram Altin/Ons Altin/Gumus icin bir onceki
script calismasinda kaydedilen degere (data/commodity_state.json) gore,
Brent ve Bitcoin icin ise API'lerin kendi verdigi % degisime gore
deterministik olarak hesaplanir. AI/Claude yorum/ozet YAZMAZ.
"""
import json
import os
import re
import sys
import urllib.request
from datetime import datetime, timezone, timedelta

FILE = "index.html"
STATE_FILE = "data/commodity_state.json"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}


def fetch_json(url, timeout=15):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def fmt_tr(value, decimals=2):
    s = f"{value:,.{decimals}f}"
    return s.replace(",", "").replace(".", ",").replace("", ".")


def trend_from_change(chg):
    if chg is None:
        return None
    if chg > 0.05:
        return "yukselis"
    if chg < -0.05:
        return "dususte"
    return "notr"


def load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def save_state(state):
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def pct_change(new, old):
    if old is None or old == 0:
        return None
    return (new - old) / old * 100.0


def patch_commodity(html, index, price_str, chg, trend, note):
    """commodities dizisindeki index'inci elemanin price/chg/trend/note alanlarini gunceller."""
    pattern = re.compile(
        r'(\{lbl:"[^"]*",\s*price:)"[^"]*"(,\s*chg:)-?[\d.]+(,\s*trend:)"[^"]*"(,\s*note:)"[^"]*"'
    )
    matches = list(pattern.finditer(html))
    if index >= len(matches):
        return html, 0
    m = matches[index]
    repl = (
        m.group(1) + json.dumps(price_str, ensure_ascii=False) +
        m.group(2) + f"{chg:.2f}" +
        m.group(3) + json.dumps(trend, ensure_ascii=False) +
        m.group(4) + json.dumps(note, ensure_ascii=False)
    )
    new_html = html[:m.start()] + repl + html[m.end():]
    return new_html, 1


def patch_array_item(html, array_var, index, price_str, chg, trend, note):
    """Belirli bir JS dizisinin (commodities/btcTiles) icindeki index'inci
    {lbl:..., price:..., chg:..., trend:..., note:...} nesnesini gunceller."""
    arr_match = re.search(r'var ' + re.escape(array_var) + r'\s*=\s*\[(.*?)\n  \];', html, re.S)
    if not arr_match:
        return html, 0
    block = arr_match.group(1)
    item_pattern = re.compile(
        r'\{lbl:"[^"]*",\s*price:"[^"]*",\s*chg:-?[\d.]+,\s*trend:"[^"]*",\s*note:"(?:[^"\\]|\\.)*"\}'
    )
    items = list(item_pattern.finditer(block))
    if index >= len(items):
        return html, 0
    old_item = items[index].group(0)
    lbl_m = re.search(r'lbl:"([^"]*)"', old_item)
    lbl = lbl_m.group(1) if lbl_m else ""
    new_item = (
        '{lbl:' + json.dumps(lbl, ensure_ascii=False) +
        ', price:' + json.dumps(price_str, ensure_ascii=False) +
        ', chg:' + f"{chg:.2f}" +
        ', trend:' + json.dumps(trend, ensure_ascii=False) +
        ', note:' + json.dumps(note, ensure_ascii=False) + '}'
    )
    new_block = block[:items[index].start()] + new_item + block[items[index].end():]
    new_html = html[:arr_match.start(1)] + new_block + html[arr_match.end(1):]
    return new_html, 1


def main():
    with open(FILE, "r", encoding="utf-8") as f:
        html = f.read()

    state = load_state()
    ist = datetime.now(timezone.utc) + timedelta(hours=3)
    ts_label = ist.strftime("%d.%m %H:%M")
    ok_parts, fail_parts = [], []

    # ---- Ons Altin / Gumus (gold-api.com) + USD/TRY (open.er-api.com) ----
    xau = xag = usdtry = None
    try:
        xau = fetch_json("https://api.gold-api.com/price/XAU")["price"]
        ok_parts.append("Ons Altın")
    except Exception as e:
        fail_parts.append("Ons Altın"); print(f"  [atlandi] XAU: {e}", file=sys.stderr)
    try:
        xag = fetch_json("https://api.gold-api.com/price/XAG")["price"]
        ok_parts.append("Gümüş")
    except Exception as e:
        fail_parts.append("Gümüş"); print(f"  [atlandi] XAG: {e}", file=sys.stderr)
    try:
        usdtry = fetch_json("https://open.er-api.com/v6/latest/USD")["rates"]["TRY"]
    except Exception as e:
        print(f"  [atlandi] USD/TRY: {e}", file=sys.stderr)

    if xau is not None:
        prev = state.get("ons_altin_usd")
        chg = pct_change(xau, prev) or 0.0
        trend = trend_from_change(chg) or "notr"
        note = f"gold-api.com üzerinden {ts_label} (İstanbul) itibarıyla otomatik çekildi, önceki otomatik güncellemeye göre %{fmt_tr(abs(chg))} {'yükseldi' if chg>=0 else 'geriledi'}."
        html, n = patch_array_item(html, "commodities", 1, f"${fmt_tr(xau)}", chg, trend, note)
        state["ons_altin_usd"] = xau

    if xag is not None:
        prev = state.get("gumus_usd")
        chg = pct_change(xag, prev) or 0.0
        trend = trend_from_change(chg) or "notr"
        note = f"gold-api.com üzerinden {ts_label} (İstanbul) itibarıyla otomatik çekildi, önceki otomatik güncellemeye göre %{fmt_tr(abs(chg))} {'yükseldi' if chg>=0 else 'geriledi'}."
        html, n = patch_array_item(html, "commodities", 2, f"${fmt_tr(xag)}", chg, trend, note)
        state["gumus_usd"] = xag

    if xau is not None and usdtry is not None:
        gram_tl = (xau / 31.1035) * usdtry
        prev = state.get("gram_altin_tl")
        chg = pct_change(gram_tl, prev) or 0.0
        trend = trend_from_change(chg) or "notr"
        note = f"Ons altın (gold-api.com) × USD/TRY (open.er-api.com) ile {ts_label} (İstanbul) itibarıyla hesaplandı, önceki otomatik güncellemeye göre %{fmt_tr(abs(chg))} {'yükseldi' if chg>=0 else 'geriledi'}."
        html, n = patch_array_item(html, "commodities", 0, f"{fmt_tr(gram_tl)} TL", chg, trend, note)
        state["gram_altin_tl"] = gram_tl
        ok_parts.append("Gram Altın")
    else:
        fail_parts.append("Gram Altın")

    # ---- Brent Petrol (Yahoo Finance) ----
    try:
        data = fetch_json("https://query1.finance.yahoo.com/v8/finance/chart/BZ=F?interval=1d&range=5d")
        meta = data["chart"]["result"][0]["meta"]
        price = meta["regularMarketPrice"]
        chg = meta.get("regularMarketChangePercent", 0.0)
        trend = trend_from_change(chg) or "notr"
        note = f"Yahoo Finance (BZ=F, Brent Crude Oil futures) üzerinden {ts_label} (İstanbul) itibarıyla otomatik çekildi, önceki kapanışa göre %{fmt_tr(abs(chg))} {'yükseldi' if chg>=0 else 'geriledi'}."
        html, n = patch_array_item(html, "commodities", 3, f"${fmt_tr(price)}", chg, trend, note)
        ok_parts.append("Brent Petrol")
    except Exception as e:
        fail_parts.append("Brent Petrol"); print(f"  [atlandi] Brent: {e}", file=sys.stderr)

    # ---- Bitcoin (CoinGecko) ----
    try:
        j = fetch_json("https://api.coingecko.com/api/v3/coins/bitcoin?localization=false&tickers=false&market_data=true&community_data=false&developer_data=false")
        md = j["market_data"]
        usd = md["current_price"]["usd"]
        try_ = md["current_price"]["try"]
        chg24 = md.get("price_change_percentage_24h") or 0.0
        chg7 = md.get("price_change_percentage_7d") or 0.0
        trend24 = trend_from_change(chg24) or "notr"
        trend7 = trend_from_change(chg7) or "notr"
        note_usd = f"CoinGecko üzerinden {ts_label} (İstanbul) itibarıyla otomatik çekildi (USD)."
        note_try = f"CoinGecko üzerinden {ts_label} (İstanbul) itibarıyla otomatik çekildi (TRY)."
        note_7d = f"CoinGecko üzerinden {ts_label} (İstanbul) itibarıyla otomatik çekildi (7 günlük değişim)."
        html, n = patch_array_item(html, "btcTiles", 0, f"${fmt_tr(usd,0)}", chg24, trend24, note_usd)
        html, n = patch_array_item(html, "btcTiles", 1, f"₺{fmt_tr(try_,0)}", chg24, trend24, note_try)
        html, n = patch_array_item(html, "btcTiles", 2, f"%{fmt_tr(chg7)}", chg7, trend7, note_7d)
        ok_parts.append("Bitcoin")
    except Exception as e:
        fail_parts.append("Bitcoin"); print(f"  [atlandi] Bitcoin: {e}", file=sys.stderr)

    save_state(state)

    if ok_parts:
        label = (
            f"Emtia ve Bitcoin GitHub Actions ile {ts_label} (İstanbul) itibarıyla otomatik güncellendi "
            f"({', '.join(ok_parts)}, Claude kullanılmadan)."
        )
        if fail_parts:
            label += f" Alınamayan: {', '.join(fail_parts)}."
    else:
        label = f"Emtia/Bitcoin kaynaklarına {ts_label} (İstanbul) itibarıyla ulaşılamadı, bu deneme atlandı."

    pat = re.compile(r'(<span id="commodityAutoText"[^>]*>)[^<]*(</span>)')
    html, n = pat.subn(lambda m: m.group(1) + label + m.group(2), html, count=1)
    if n == 0:
        print("UYARI: #commodityAutoText elemani bulunamadi.", file=sys.stderr)

    with open(FILE, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"Basarili: {ok_parts}")
    if fail_parts:
        print(f"Basarisiz: {fail_parts}")


if __name__ == "__main__":
    main()
