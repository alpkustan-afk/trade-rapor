# Trade seviye raporlari

Her gun 08:30, 12:30, 17:30 ve 21:00'de (Turkiye saati) kripto + ABD hisseleri icin
kural bazli seviye raporu (PDF) uretir ve ntfy ile telefona gonderir. Her 30 dakikada
son rapordaki hedef/stop/tetik seviyelerini kontrol eder; gelen olursa bildirir ve yeni
seviyeleri gonderir.

- `tools/` : seviye hesaplama, PDF rapor, takip, ntfy bildirimi
- `scanner/scan.py` : ABD hisse tarayicisi, Jake Schincariol'un day-trader-skill projesinden (MIT, bkz. `scanner/LICENSE`)
- `.github/workflows/trade.yml` : zamanlama
- Gizli ayar: `NTFY_TOPIC` (Settings > Secrets and variables > Actions)

Seviyeler sabit kurallarla hesaplanir. Yatirim tavsiyesi degildir.
