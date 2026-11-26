"""Tek giris noktasi (zamanlanmis gorevler bunu cagirir).

  python3 tools/run.py report --slot "Sabah 08:30"   tam rapor (gerekirse gunluk hisse taramasi + seviyeler + PDF)
  python3 tools/run.py check                         erken seviye kontrolu; olay varsa yeni seviyeler + ara rapor

Cikti son satirlari:
  PDF=<yol>
  BILDIRIM=<telefon icin tek satir ozet>
check'te olay yoksa 'OLAY YOK' basar ve cikis kodu 3 olur.
"""
import json, os, secrets, shutil, subprocess, sys, urllib.parse, urllib.request
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG = os.path.join(ROOT, "trader", "run.log")
if sys.stdout is None or sys.stderr is None:  # pythonw (Gorev Zamanlayici) konsolsuz calisir
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    sys.stdout = sys.stderr = open(LOG, "a", encoding="utf-8", buffering=1)
    print("\n=== %s %s" % (datetime.now().isoformat(timespec="seconds"), " ".join(sys.argv[1:])))

SLOTS = {"0830": "Sabah 08:30", "1230": "Öğle 12:30", "1730": "Akşamüstü 17:30", "2100": "Gece 21:00"}
TOPIC_FILE = os.path.join(ROOT, "tools", "ntfy_topic.txt")


def topic():
    if os.environ.get("NTFY_TOPIC"):
        return os.environ["NTFY_TOPIC"].strip()
    if not os.path.exists(TOPIC_FILE):
        open(TOPIC_FILE, "w").write("trade-" + secrets.token_hex(12))
    return open(TOPIC_FILE).read().strip()


def notify(title, message, pdf=None, priority="high"):
    """ntfy.sh ile telefona bildirim; pdf verilirse ek olarak gonderilir."""
    q = {"title": title, "message": message[:900], "tags": "chart_with_upwards_trend", "priority": priority}
    if pdf:
        q["filename"] = os.path.basename(pdf)
    url = "https://ntfy.sh/%s?%s" % (topic(), urllib.parse.urlencode(q))
    data = open(pdf, "rb").read() if pdf else b""
    try:
        req = urllib.request.Request(url, data=data, method="PUT" if pdf else "POST")
        urllib.request.urlopen(req, timeout=60).read()
        print("ntfy: gonderildi")
    except Exception as e:
        print("ntfy hatasi: %s" % e)
TOOLS = os.path.join(ROOT, "tools")
TRADER = os.path.join(ROOT, "trader")
_LOCAL_SCAN = os.path.join(ROOT, "scanner", "scan.py")
SCAN = _LOCAL_SCAN if os.path.exists(_LOCAL_SCAN) else os.path.join(
    os.path.expanduser("~"), ".claude", "skills", "trader-scanner", "scan.py")
PY = sys.executable


def run(args, timeout=900):
    p = subprocess.run([PY] + args, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", timeout=timeout)
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def ensure_daily_scan():
    # tarih isaretleri dosya icinde tutulur (bulutta dosya zamanlari her calismada sifirlanir)
    wl = os.path.join(TRADER, "watchlist_daily.json")
    mark = os.path.join(TRADER, "daily_date.txt")
    umark = os.path.join(TRADER, "universe_date.txt")
    today = datetime.now().strftime("%Y-%m-%d")
    if os.path.exists(wl) and os.path.exists(mark) and open(mark).read().strip() == today:
        return "gunluk hisse taramasi bugun zaten yapildi"
    uni = os.path.join(TRADER, "universe.txt")
    try:
        uage = (datetime.now() - datetime.strptime(open(umark).read().strip(), "%Y-%m-%d")).days
    except Exception:
        uage = 99
    if not os.path.exists(uni) or uage > 6:
        c, _ = run([SCAN, "universe"], 300)
        if c == 0:
            open(umark, "w").write(today)
    code, out = run([SCAN, "daily"], 900)
    src = os.path.join(TRADER, "watchlist.json")
    if os.path.exists(src) and code in (0, 1):
        shutil.copyfile(src, wl)
        open(mark, "w").write(today)
    return (out.strip().splitlines() or ["?"])[-3] if code in (0, 1) else "gunluk tarama hatasi"


def summary(prefix):
    d = json.load(open(os.path.join(TRADER, "seviyeler.json"), encoding="utf-8"))
    parts = []
    for r in (d["crypto"] + d["orb"] + d["stocks"])[:3]:
        parts.append("%s giris %s hedef %s stop %s" % (r["symbol"].replace("-USD", ""), r["entry"], r["target"], r["stop"]))
    if not parts and d.get("crypto_watch"):
        r = d["crypto_watch"][0]
        parts.append("kural yok; en yakin tetik %s %s" % (r["symbol"].replace("-USD", ""), r["entry"]))
    n = len(d["crypto"]) + len(d["orb"]) + len(d["stocks"])
    return "%s: %d kurulum. %s" % (prefix, n, " | ".join(parts))


def report(slot, events_file=None, exclude=""):
    args = [os.path.join(TOOLS, "levels.py"), "--orb"]
    if exclude:
        args += ["--exclude", exclude]
    code, out = run(args, 900)
    print(out.strip())
    if code != 0:
        print("HATA: seviye hesaplanamadi"); sys.exit(1)
    rargs = [os.path.join(TOOLS, "report.py"), "--title", slot]
    if events_file:
        rargs += ["--events", events_file]
    code, out = run(rargs, 300)
    if code != 0:
        print(out); print("HATA: PDF olusturulamadi")
        notify("Trade raporu HATA", "PDF olusturulamadi (%s)" % slot); sys.exit(1)
    pdf = out.strip().splitlines()[-1]
    print("PDF=" + pdf)
    return pdf


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in ("report", "check", "test-notify"):
        print(__doc__); sys.exit(2)
    os.makedirs(TRADER, exist_ok=True)
    send = "--no-notify" not in sys.argv
    if sys.argv[1] == "test-notify":
        notify("Trade test", "Bildirim calisiyor. Raporlar 08:30, 12:30, 17:30 ve 21:00'de gelecek.")
        return
    if sys.argv[1] == "report":
        slot = sys.argv[sys.argv.index("--slot") + 1] if "--slot" in sys.argv else datetime.now().strftime("%H:%M")
        slot = SLOTS.get(slot, slot)
        print(ensure_daily_scan())
        ev = os.path.join(TRADER, "olaylar_son.json")
        pdf = report(slot, ev if os.path.exists(ev) else None)
        if os.path.exists(ev):
            os.remove(ev)
        msg = summary("Rapor " + slot)
        print("BILDIRIM=" + msg)
        if send:
            notify("Trade raporu - " + slot, msg + "\nYatirim tavsiyesi degildir.", pdf)
        return
    code, out = run([os.path.join(TOOLS, "monitor.py")], 300)
    print(out.strip())
    if code == 3:
        sys.exit(3)
    if code != 0:
        print("HATA: takip calismadi"); sys.exit(1)
    excl = next((l.split("=", 1)[1] for l in out.splitlines() if l.startswith("EXCLUDE=")), "")
    ev = os.path.join(TRADER, "olaylar_son.json")
    pdf = report("Ara rapor " + datetime.now().strftime("%H:%M") + " (seviye geldi)", ev, excl)
    os.remove(ev)
    olay = "; ".join(l[6:].strip() for l in out.splitlines() if l.startswith("OLAY:"))
    msg = olay + "\n" + summary("Yeni seviyeler")
    print("BILDIRIM=" + msg)
    if send:
        notify("Seviye geldi!", msg + "\nYatirim tavsiyesi degildir.", pdf, priority="urgent")


if __name__ == "__main__":
    main()
