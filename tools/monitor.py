"""Erken seviye takipcisi: trader/aktif_seviyeler.json'daki acik seviyeleri 5 dakikalik mumlarla kontrol eder.

Rapordan bu yana:
  - kurala uyan varliklarda: once hedef mi (yuksek >= hedef) once stop mu (dusuk <= stop) geldi
  - izleme listesinde: fiyat tetik seviyesini gecti mi
Olay varsa trader/olaylar_son.json'a yazar, trader/olaylar.log'a ekler ve
'OLAY:' satirlari basar; cikis kodu 0. Olay yoksa 'OLAY YOK', cikis kodu 3.
"""
import json, os, sys, time, urllib.request
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TRADER = os.path.join(ROOT, "trader")
ACTIVE = os.path.join(TRADER, "aktif_seviyeler.json")
UA = {"User-Agent": "Mozilla/5.0 (compatible; trade-monitor/1.0)"}


def bars5(sym):
    for host in ("query2", "query1"):
        try:
            u = "https://%s.finance.yahoo.com/v8/finance/chart/%s?range=2d&interval=5m" % (host, sym)
            with urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=20) as r:
                res = json.load(r)["chart"]["result"][0]
            q = res["indicators"]["quote"][0]
            return [(t, q["high"][i], q["low"][i]) for i, t in enumerate(res.get("timestamp") or [])
                    if q["high"][i] is not None and q["low"][i] is not None]
        except Exception:
            time.sleep(1)
    return None


def main():
    if not os.path.exists(ACTIVE):
        print("OLAY YOK (aktif seviye dosyasi yok)"); sys.exit(3)
    d = json.load(open(ACTIVE, encoding="utf-8"))
    since = datetime.fromisoformat(d["created_at"]).timestamp()
    events = []
    for it in d["items"]:
        if it["status"] != "open":
            continue
        b = bars5(it["symbol"])
        if not b:
            continue
        for t, h, l in b:
            if t + 300 <= since:  # rapordan once biten mumlar sayilmaz
                continue
            ev = None
            if it["rule"] == "watch":
                if h >= it["entry"]:
                    ev, lvl = "triggered", it["entry"]
            elif l <= it["stop"]:
                ev, lvl = "stop", it["stop"]
            elif h >= it["target"]:
                ev, lvl = "target", it["target"]
            if ev:
                it["status"] = ev
                it["event_time"] = datetime.fromtimestamp(t).strftime("%d.%m %H:%M")
                events.append({"symbol": it["symbol"], "event": ev, "level": lvl, "time": it["event_time"],
                               "entry": it["entry"], "stop": it["stop"], "target": it["target"]})
                break
        time.sleep(0.15)
    json.dump(d, open(ACTIVE, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    if not events:
        print("OLAY YOK"); sys.exit(3)
    json.dump(events, open(os.path.join(TRADER, "olaylar_son.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    with open(os.path.join(TRADER, "olaylar.log"), "a", encoding="utf-8") as f:
        for e in events:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")
    tr = {"target": "satis (hedef) seviyesine ulasti", "stop": "stop seviyesine indi", "triggered": "tetik seviyesini gecti"}
    for e in events:
        print("OLAY: %s %s (%s) saat %s" % (e["symbol"].replace("-USD", ""), tr[e["event"]], e["level"], e["time"]))
    print("EXCLUDE=" + ",".join(e["symbol"] for e in events))
    sys.exit(0)


if __name__ == "__main__":
    main()
