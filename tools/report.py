"""trader/seviyeler.json -> raporlar/rapor_YYYY-MM-DD_HHMM.pdf (Edge headless ile).
Ayrica trader/aktif_seviyeler.json dosyasina takip edilecek seviyeleri yazar.

Kullanim: python3 tools/report.py [--title "Sabah 08:30"] [--events trader/olaylar_son.json]
"""
import argparse, html, json, os, subprocess, tempfile
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TRADER = os.path.join(ROOT, "trader")
OUTDIR = os.path.join(ROOT, "raporlar")
EDGE = [r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        "/usr/bin/google-chrome", "/usr/bin/google-chrome-stable", "/usr/bin/chromium", "/usr/bin/chromium-browser"]

RULE = {
    "breakout_20": "20 mumluk zirve kırılımı",
    "reclaim_ma20": "20'lik ortalamanın üstüne dönüş",
    "oversold_bounce": "Aşırı satımdan yukarı dönüş",
    "oversold": "Aşırı satım (RSI 30 altı)",
    "orb": "Açılış aralığı kırılımı",
    "watch": "Zirve kırılımı bekleniyor",
}


def fmt(x):
    if x is None: return "–"
    if x >= 1000: s = "{:,.2f}".format(x)
    elif x >= 1: s = "{:,.3f}".format(x)
    else: s = "{:.6g}".format(x)
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


def pct(x):
    return "–" if x is None else ("%.1f" % x).replace(".", ",")


def name(sym):
    return sym.replace("-USD", "") + ("/USD" if sym.endswith("-USD") else "")


def hist(h):
    if not h or not h.get("fired"):
        return '<span class="muted">Geçmişte tetiklenmedi</span>'
    f, t, s, n = h["fired"], h["target"], h["stop"], h["neither"]
    cls = "good" if t > s else ("bad" if s > t else "")
    return '<span class="%s">%d kez: <b>%d</b> hedef · <b>%d</b> stop · %d ikisi de değil</span>' % (cls, f, t, s, n)


def card(r, watch=False):
    entry_label = "Tetik seviyesi (bu seviyenin üstünde kapanış)" if watch else "Kuralın giriş seviyesi"
    extra = ""
    if watch:
        extra = '<div class="dist">Şu anki fiyat tetik seviyesinin <b>%%%s</b> altında</div>' % pct(r.get("distance_pct"))
    rsi = ('RSI %s · ' % pct(r["rsi"])) if r.get("rsi") is not None else ""
    return """
<div class="card">
  <div class="head"><span class="sym">{sym}</span><span class="rule">{rule}</span><span class="px">Son fiyat <b>{last}</b></span></div>
  <table class="lv">
    <tr><td class="k">{entry_label}</td><td class="v buy">{entry}</td></tr>
    <tr><td class="k">Kuralın satış (hedef) seviyesi</td><td class="v sell">{target} <small>(+%{rw})</small></td></tr>
    <tr><td class="k">Zararla çıkış (stop) seviyesi</td><td class="v stop">{stop} <small>(−%{rk})</small></td></tr>
  </table>
  {extra}
  <div class="meta">{rsi}{bar} mumlar · Aynı kural yakın geçmişte (sonraki {look} mumda): {hist}</div>
</div>""".format(sym=html.escape(name(r["symbol"])), rule=RULE.get(r["rule"], r["rule"]), last=fmt(r["last_price"]),
                 entry_label=entry_label, entry=fmt(r["entry"]), target=fmt(r["target"]), stop=fmt(r["stop"]),
                 rw=pct(r["reward_pct"]), rk=pct(r["risk_pct"]), extra=extra, rsi=rsi,
                 bar=r.get("bar", "").replace("gunluk", "Günlük").replace("4 saatlik", "4 saatlik"),
                 look=(r.get("history") or {}).get("look", 12), hist=hist(r.get("history")))


def section(title, sub, items, watch=False, empty="Şu an bu kurallara uyan yok."):
    body = "".join(card(r, watch) for r in items) if items else '<p class="muted">%s</p>' % empty
    return '<h2>%s</h2><p class="sub">%s</p>%s' % (title, sub, body)


def events_html(evs):
    if not evs:
        return ""
    rows = []
    for e in evs:
        what = {"target": "Satış (hedef) seviyesine ulaştı", "stop": "Stop seviyesine indi",
                "triggered": "Tetik seviyesini geçti"}.get(e["event"], e["event"])
        rows.append("<tr><td><b>%s</b></td><td>%s</td><td>%s</td><td>%s</td></tr>" % (
            html.escape(name(e["symbol"])), what, fmt(e.get("level")), html.escape(e.get("time", ""))))
    return ('<h2>Önceki rapordan bu yana seviyesine gelenler</h2><table class="ev"><tr><th>Varlık</th><th>Olay</th>'
            '<th>Seviye</th><th>Zaman</th></tr>%s</table>' % "".join(rows))


CSS = """
@page { size: A4; margin: 14mm 12mm; }
body { font-family: 'Segoe UI', Arial, sans-serif; color: #1b1f24; font-size: 11pt; }
h1 { font-size: 20pt; margin: 0 0 2px; } h2 { font-size: 14pt; margin: 18px 0 2px; border-bottom: 2px solid #1b1f24; padding-bottom: 3px; }
.sub { color: #555; margin: 2px 0 8px; font-size: 9.5pt; } .muted { color: #777; }
.top { color: #555; font-size: 10pt; margin-bottom: 8px; }
.warn { background: #fff6e0; border: 1px solid #e8c56d; padding: 7px 10px; border-radius: 6px; font-size: 9pt; }
.card { border: 1px solid #d6dbe1; border-radius: 8px; padding: 8px 10px; margin: 8px 0; page-break-inside: avoid; }
.head { display: flex; gap: 10px; align-items: baseline; margin-bottom: 4px; }
.sym { font-size: 14pt; font-weight: 700; } .rule { background: #eef2f6; padding: 1px 7px; border-radius: 10px; font-size: 9pt; }
.px { margin-left: auto; font-size: 10pt; }
table.lv { width: 100%; border-collapse: collapse; } table.lv td { padding: 3px 4px; border-top: 1px solid #eef0f3; }
td.k { color: #333; width: 60%; } td.v { font-weight: 700; font-size: 12pt; text-align: right; }
.buy { color: #0b57d0; } .sell { color: #137333; } .stop { color: #b3261e; } small { font-weight: 400; color: #666; font-size: 9pt; }
.meta { font-size: 8.5pt; color: #555; margin-top: 4px; } .good { color: #137333; } .bad { color: #b3261e; }
.dist { font-size: 9pt; margin-top: 3px; }
table.ev { width: 100%; border-collapse: collapse; font-size: 10pt; } table.ev td, table.ev th { border: 1px solid #d6dbe1; padding: 4px 6px; text-align: left; }
.foot { margin-top: 16px; font-size: 8.5pt; color: #555; }
"""


def build(d, title, evs):
    created = d.get("created_at", "")
    parts = ['<h1>Trade Seviye Raporu — %s</h1>' % html.escape(title),
             '<div class="top">Oluşturma: %s · Veri: Yahoo Finance (ücretsiz, gecikmeli olabilir)</div>' % html.escape(created.replace("T", " ")),
             '<div class="warn"><b>Yatırım tavsiyesi değildir.</b> Aşağıdaki seviyeler sabit kurallarla hesaplanır: '
             'giriş = son tamamlanan mumun kapanışı, stop = giriş − 1,5 × ATR(14), satış hedefi = giriş + 2 × risk (2R). '
             '"Geçmiş" satırı aynı kuralın yakın geçmişte kaç kez hedefe, kaç kez stopa gittiğini gösterir. İşleme girip girmemek sizin kararınız.</div>',
             events_html(evs)]
    parts.append(section("Kripto — kurala uyanlar", "4 saatlik mumlar, 7/24", d.get("crypto", [])))
    parts.append(section("Kripto — izleme listesi", "Henüz kural yok. 4 saatlik kapanış tetik seviyesinin üstünde olursa 20 mumluk zirve kırılımı kuralı tetiklenir. Tetiğe en yakın olanlar üstte.",
                         d.get("crypto_watch", [])[:10], watch=True))
    if d.get("orb"):
        parts.append(section("ABD hisseleri — açılış aralığı kırılımı (gün içi)", "5 dakikalık mumlar. Stop = açılış aralığının ortası. Gün sonunda (23:55 TR) pozisyon kapatılır.", d["orb"]))
    parts.append(section("ABD hisseleri — günlük kurallar", "Günlük mumlar, son tamamlanan kapanışa göre. Borsa TR saatiyle 17:30–00:00 açık.", d.get("stocks", [])))
    notes = d.get("notes", []) + (["Veri alınamayanlar: " + ", ".join(d["failed"])] if d.get("failed") else [])
    if notes:
        parts.append('<div class="foot">%s</div>' % "<br>".join(html.escape(n) for n in notes))
    parts.append('<div class="foot">Stop bir plandır, garanti değildir: hızlı piyasada fiyat stopun ötesinde gerçekleşebilir. '
                 'Fiyatı işlem yapacağınız platformda kontrol edin.</div>')
    return '<!doctype html><html lang="tr"><head><meta charset="utf-8"><title>%s</title><style>%s</style></head><body>%s</body></html>' % (
        html.escape(title), CSS, "".join(parts))


def to_pdf(html_path, pdf_path):
    exe = next((e for e in EDGE if os.path.exists(e)), None)
    if not exe:
        raise SystemExit("Edge bulunamadi")
    prof = tempfile.mkdtemp(prefix="edgepdf_")
    args = [exe, "--headless", "--disable-gpu", "--no-pdf-header-footer", "--user-data-dir=" + prof,
            "--print-to-pdf=" + pdf_path, "file:///" + html_path.replace("\\", "/").lstrip("/")]
    if os.name != "nt":
        args.insert(1, "--no-sandbox")
    subprocess.run(args, capture_output=True, timeout=120)
    if not os.path.exists(pdf_path):
        raise SystemExit("PDF olusturulamadi")


def write_active(d):
    now = d.get("created_at")
    items = []
    for k in ("crypto", "stocks", "orb", "crypto_watch"):
        for r in d.get(k, []):
            items.append({"symbol": r["symbol"], "kind": r["kind"], "rule": r["rule"], "entry": r["entry"],
                          "stop": r["stop"], "target": r["target"], "since": now, "status": "open"})
    json.dump({"created_at": now, "items": items}, open(os.path.join(TRADER, "aktif_seviyeler.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--title", default="")
    ap.add_argument("--events", default="")
    ap.add_argument("--in", dest="inp", default=os.path.join(TRADER, "seviyeler.json"))
    ap.add_argument("--no-track", action="store_true")
    a = ap.parse_args()
    d = json.load(open(a.inp, encoding="utf-8"))
    evs = json.load(open(a.events, encoding="utf-8")) if a.events and os.path.exists(a.events) else []
    title = a.title or datetime.now().strftime("%d.%m.%Y %H:%M")
    os.makedirs(OUTDIR, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M")
    hp = os.path.join(OUTDIR, "rapor_%s.html" % stamp); pp = os.path.join(OUTDIR, "rapor_%s.pdf" % stamp)
    open(hp, "w", encoding="utf-8").write(build(d, title, evs))
    to_pdf(hp, pp)
    os.remove(hp)
    if not a.no_track:
        write_active(d)
    print(pp)


if __name__ == "__main__":
    main()
