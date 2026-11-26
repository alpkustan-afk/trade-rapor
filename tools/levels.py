"""Kural bazli seviye hesaplayici: kripto (4 saatlik mumlar) + ABD hisseleri (gunluk mumlar).

Her varlik icin kurallar (yalnizca TAMAMLANMIS mumlar):
  breakout_20   son kapanis, onceki 20 mumun en yuksek degerinin ustunde
  reclaim_ma20  onceki kapanis 20'lik ortalamanin altinda, son kapanis ustunde
  oversold_bounce  RSI14 onceki mumda 30 alti, son mum yukari kapandi
  oversold      RSI14 30 alti
Seviyeler (tum kurallar icin ayni, mekanik):
  giris  = son kapanis
  stop   = giris - 1.5 x ATR14
  hedef  = giris + 2 x (giris - stop)   (2R)
Gecmis: ayni kural son ~180 mumda her tetiklendiginde, sonraki 12 mumda
hedef mi stop mu once geldi (ayni mumda ikisi de -> stop sayilir).

Kullanim:
  python3 tools/levels.py [--stocks N] [--orb] [--out trader/seviyeler.json]
Bu bir hesap aracidir, yatirim tavsiyesi degildir.
"""
import argparse, json, os, subprocess, sys, time, urllib.request
from datetime import datetime, timezone, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TRADER = os.path.join(ROOT, "trader")
UA = {"User-Agent": "Mozilla/5.0 (compatible; trade-levels/1.0)"}
SCAN = os.path.join(ROOT, "scanner", "scan.py")
if not os.path.exists(SCAN):
    SCAN = os.path.join(os.path.expanduser("~"), ".claude", "skills", "trader-scanner", "scan.py")

CRYPTO = ["BTC-USD", "ETH-USD", "SOL-USD", "XRP-USD", "BNB-USD", "DOGE-USD", "ADA-USD",
          "TRX-USD", "AVAX-USD", "LINK-USD", "DOT-USD", "LTC-USD", "BCH-USD", "XLM-USD",
          "HBAR-USD", "NEAR-USD", "ATOM-USD", "ETC-USD", "SHIB-USD", "FIL-USD"]

RULE_TR = {
    "breakout_20": "20 mumluk zirve kirilimi",
    "reclaim_ma20": "20'lik ortalamanin ustune donus",
    "oversold_bounce": "Asiri satimdan yukari donus",
    "oversold": "Asiri satim (RSI 30 alti)",
    "orb": "Acilis araligi kirilimi (5 dk)",
}
RULE_ORDER = ["breakout_20", "reclaim_ma20", "oversold_bounce", "oversold"]


def fetch(sym, interval, rng):
    last = None
    for host in ("query2", "query1"):
        url = "https://%s.finance.yahoo.com/v8/finance/chart/%s?range=%s&interval=%s" % (host, sym, rng, interval)
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=25) as r:
                res = json.load(r)["chart"]["result"][0]
            q = res["indicators"]["quote"][0]
            bars = []
            for i, t in enumerate(res.get("timestamp") or []):
                o, h, l, c = q["open"][i], q["high"][i], q["low"][i], q["close"][i]
                if None in (o, h, l, c):
                    continue
                bars.append({"t": t, "o": o, "h": h, "l": l, "c": c, "v": (q.get("volume") or [0] * (i + 1))[i] or 0})
            return bars, res["meta"]
        except Exception as e:  # noqa
            last = e
            time.sleep(1)
    raise RuntimeError("%s: %s" % (sym, last))


def to_4h(bars, now):
    """1 saatlik mumlari UTC 00/04/08/12/16/20 hizali 4 saatlik mumlara cevir, bitmemis son mumu at."""
    out, cur = [], None
    for b in bars:
        k = b["t"] - (b["t"] % 14400)
        if cur is None or cur["t"] != k:
            if cur:
                out.append(cur)
            cur = {"t": k, "o": b["o"], "h": b["h"], "l": b["l"], "c": b["c"], "v": b["v"]}
        else:
            cur["h"] = max(cur["h"], b["h"]); cur["l"] = min(cur["l"], b["l"]); cur["c"] = b["c"]; cur["v"] += b["v"]
    if cur:
        out.append(cur)
    if out and out[-1]["t"] + 14400 > now:
        out.pop()
    return out


def rsi_series(closes, n=14):
    r = [None] * len(closes)
    if len(closes) <= n:
        return r
    gains = [max(closes[i] - closes[i - 1], 0) for i in range(1, len(closes))]
    losses = [max(closes[i - 1] - closes[i], 0) for i in range(1, len(closes))]
    ag, al = sum(gains[:n]) / n, sum(losses[:n]) / n
    r[n] = 100 - 100 / (1 + ag / al) if al else 100.0
    for i in range(n + 1, len(closes)):
        ag = (ag * (n - 1) + gains[i - 1]) / n
        al = (al * (n - 1) + losses[i - 1]) / n
        r[i] = 100 - 100 / (1 + ag / al) if al else 100.0
    return r


def atr_series(bars, n=14):
    tr = [None] + [max(b["h"] - b["l"], abs(b["h"] - p["c"]), abs(b["l"] - p["c"])) for p, b in zip(bars, bars[1:])]
    a = [None] * len(bars)
    if len(bars) <= n:
        return a
    a[n] = sum(tr[1:n + 1]) / n
    for i in range(n + 1, len(bars)):
        a[i] = (a[i - 1] * (n - 1) + tr[i]) / n
    return a


def rules_at(bars, i, rsi):
    """i. mumda tetiklenen kurallar."""
    hits = []
    if i < 21:
        return hits
    c = bars[i]["c"]
    if c > max(b["h"] for b in bars[i - 20:i]):
        hits.append("breakout_20")
    ma_now = sum(b["c"] for b in bars[i - 19:i + 1]) / 20
    ma_prev = sum(b["c"] for b in bars[i - 20:i]) / 20
    if bars[i - 1]["c"] < ma_prev and c > ma_now:
        hits.append("reclaim_ma20")
    if rsi[i - 1] is not None and rsi[i - 1] < 30 and c > bars[i - 1]["c"]:
        hits.append("oversold_bounce")
    if rsi[i] is not None and rsi[i] < 30:
        hits.append("oversold")
    return hits


def history(bars, rule, rsi, atr, look=12, span=180):
    fired = tgt = stp = none = 0
    start = max(21, len(bars) - span - look)
    for i in range(start, len(bars) - 1):
        if rule not in rules_at(bars, i, rsi) or atr[i] is None:
            continue
        fired += 1
        e = bars[i]["c"]; s = e - 1.5 * atr[i]; t = e + 2 * (e - s)
        res = None
        for b in bars[i + 1:i + 1 + look]:
            if b["l"] <= s:
                res = "s"; break
            if b["h"] >= t:
                res = "t"; break
        if res == "t":
            tgt += 1
        elif res == "s":
            stp += 1
        else:
            none += 1
    return {"fired": fired, "target": tgt, "stop": stp, "neither": none, "look": look}


def rnd(x):
    if x >= 1000: return round(x, 2)
    if x >= 1: return round(x, 3)
    if x >= 0.01: return round(x, 5)
    return float("%.4g" % x)


def analyse(sym, kind, now):
    if kind == "crypto":
        raw, meta = fetch(sym, "1h", "60d")
        bars = to_4h(raw, now)
        bar_label = "4 saatlik"
    else:
        bars, meta = fetch(sym, "1d", "1y")
        ny = datetime.now(timezone(timedelta(hours=-5)))  # yaklasik ET
        if bars and datetime.fromtimestamp(bars[-1]["t"], ny.tzinfo).date() == ny.date() and ny.hour < 16:
            bars.pop()
        bar_label = "gunluk"
    if len(bars) < 40:
        return None
    closes = [b["c"] for b in bars]
    rsi = rsi_series(closes); atr = atr_series(bars)
    i = len(bars) - 1
    hits = rules_at(bars, i, rsi)
    if atr[i] is None:
        return None
    if not hits:
        if kind != "crypto":
            return None
        # izleme: 20 mumluk zirvenin ustunde kapanis olursa breakout_20 tetiklenir
        trig = max(b["h"] for b in bars[i - 19:i + 1])
        s = trig - 1.5 * atr[i]; t = trig + 2 * (trig - s)
        return {
            "symbol": sym, "kind": kind, "bar": bar_label, "rules": [], "rule": "watch",
            "rule_tr": "Izleme: 20 mumluk zirve kirilimi bekleniyor",
            "bar_close_utc": datetime.fromtimestamp(bars[i]["t"], timezone.utc).isoformat(),
            "last_price": rnd(meta.get("regularMarketPrice") or bars[i]["c"]),
            "entry": rnd(trig), "stop": rnd(s), "target": rnd(t),
            "risk_pct": round((trig - s) / trig * 100, 2), "reward_pct": round((t - trig) / trig * 100, 2),
            "distance_pct": round((trig - bars[i]["c"]) / bars[i]["c"] * 100, 2),
            "rsi": round(rsi[i], 1) if rsi[i] is not None else None,
            "history": history(bars, "breakout_20", rsi, atr),
        }
    rule = next(r for r in RULE_ORDER if r in hits)
    e = bars[i]["c"]; s = e - 1.5 * atr[i]; t = e + 2 * (e - s)
    return {
        "symbol": sym, "kind": kind, "bar": bar_label, "rules": hits, "rule": rule,
        "rule_tr": RULE_TR[rule], "bar_close_utc": datetime.fromtimestamp(bars[i]["t"], timezone.utc).isoformat(),
        "last_price": rnd(meta.get("regularMarketPrice") or e),
        "entry": rnd(e), "stop": rnd(s), "target": rnd(t),
        "risk_pct": round((e - s) / e * 100, 2), "reward_pct": round((t - e) / e * 100, 2),
        "rsi": round(rsi[i], 1) if rsi[i] is not None else None,
        "history": history(bars, rule, rsi, atr),
    }


def orb_levels():
    """Seans icindeyse ABD acilis araligi kirilimlari (trader-scanner orb), stop = aralik ortasi, hedef 2R."""
    wl = os.path.join(TRADER, "watchlist_daily.json")
    args = [sys.executable, SCAN, "orb", "--json", "--no-write"]
    if os.path.exists(wl):
        args += ["--watchlist", wl]
    try:
        p = subprocess.run(args, capture_output=True, text=True, timeout=600, cwd=ROOT)
        data = json.loads(p.stdout) if p.stdout.strip().startswith("{") else None
    except Exception:
        data = None
    if not data:
        return [], (p.stdout.strip().splitlines() or [""])[-1] if 'p' in locals() else "orb calismadi"
    out = []
    for h in data.get("hits", [])[:12]:
        hi, lo = h.get("or_high"), h.get("or_low")
        e = h.get("price")
        if not (hi and lo and e):
            continue
        s = (hi + lo) / 2
        if s >= e:
            continue
        t = e + 2 * (e - s)
        out.append({"symbol": h["symbol"], "kind": "stock", "bar": "5 dakikalik", "rules": ["orb"], "rule": "orb",
                    "rule_tr": RULE_TR["orb"], "last_price": rnd(e), "entry": rnd(e), "stop": rnd(s), "target": rnd(t),
                    "risk_pct": round((e - s) / e * 100, 2), "reward_pct": round((t - e) / e * 100, 2),
                    "rsi": None, "history": None, "bar_close_utc": h.get("time") or h.get("at")})
    return out, None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stocks", type=int, default=12, help="gunluk listeden kac hisse")
    ap.add_argument("--orb", action="store_true", help="ABD seansi aciksa acilis araligi taramasi da")
    ap.add_argument("--out", default=os.path.join(TRADER, "seviyeler.json"))
    ap.add_argument("--exclude", default="", help="virgulle: bu sembolleri atla (yeni oneri icin)")
    a = ap.parse_args()
    now = time.time()
    excl = {x.strip().upper() for x in a.exclude.split(",") if x.strip()}
    os.makedirs(TRADER, exist_ok=True)
    result = {"created_at": datetime.now().astimezone().isoformat(timespec="minutes"),
              "crypto": [], "crypto_watch": [], "stocks": [], "orb": [], "failed": [], "notes": []}

    for sym in CRYPTO:
        if sym in excl:
            continue
        try:
            r = analyse(sym, "crypto", now)
            if r: result["crypto_watch" if r["rule"] == "watch" else "crypto"].append(r)
        except Exception as e:
            result["failed"].append(sym)
        time.sleep(0.2)

    # hisse adaylari: gunluk tarama listesi (trader-scanner daily)
    wl = os.path.join(TRADER, "watchlist_daily.json")
    if os.path.exists(wl):
        hits = json.load(open(wl, encoding="utf-8")).get("hits", [])
        hits.sort(key=lambda h: -(h.get("price", 0) * h.get("volume", 0)))
        checked = 0
        for h in hits:
            if checked >= a.stocks * 3 or len(result["stocks"]) >= a.stocks:
                break
            if h["symbol"] in excl:
                continue
            checked += 1
            try:
                r = analyse(h["symbol"], "stock", now)
                if r: result["stocks"].append(r)
            except Exception:
                result["failed"].append(h["symbol"])
            time.sleep(0.2)
    else:
        result["notes"].append("Gunluk hisse listesi yok (trader/watchlist_daily.json).")

    if a.orb:
        orb, note = orb_levels()
        result["orb"] = [o for o in orb if o["symbol"] not in excl]
        if note:
            result["notes"].append("ORB: " + note)

    for k in ("crypto", "stocks"):
        result[k].sort(key=lambda r: (RULE_ORDER.index(r["rule"]), -r["reward_pct"]))
    result["crypto_watch"].sort(key=lambda r: r["distance_pct"])
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=1)
    print("kripto %d, hisse %d, orb %d, basarisiz %d -> %s" % (
        len(result["crypto"]), len(result["stocks"]), len(result["orb"]), len(result["failed"]), a.out))


if __name__ == "__main__":
    main()
