# Aktienfinder

Scannt den Aktienmarkt täglich nach bullischen Umkehrsignalen und zeigt die Treffer als
sortierbare Tabelle auf einer Website. Die Kriterien stehen in [SPEC.md](SPEC.md).

Pflichtsignale (innerhalb von ~3 Wochen zueinander, Bündel höchstens ~6 Wochen alt):
- bullische RSI-Divergenz (klassisch oder versteckt)
- MACD-Histogramm rot, aber kleiner werdend und kurz vor Grün
- grünes X im Momentum Bias Index (AlgoAlpha)

Kursrückgang, Fibonacci-Zone, Ausbruch über die EMA 20 und Volumen fließen nur in den Score ein.

## So funktioniert es
1. **Täglicher Scan** (`.github/workflows/scan.yml`): werktags 22:47 UTC, nach US-Börsenschluss
   - `aktienfinder/universe.py` stellt die Aktienliste zusammen (USA komplett, Europa, global)
   - `aktienfinder/scanner.py` lädt die Tageskerzen von Yahoo Finance und prüft jede Aktie
   - das Ergebnis (`site/data/results.json`) wird mit der Website auf GitHub Pages veröffentlicht
2. **Website** (`site/index.html`): sortierbare Tabelle mit Filtern (Region, Mindest-Score,
   MACD noch rot, Ausbruch über EMA 20, Fibonacci-Zone); Ticker öffnen den TradingView-Chart.
3. **Manuell starten:** GitHub → Actions → „Täglicher Scan“ → „Run workflow“.

## Lokal ausführen

```bash
pip install -r requirements-dev.txt
python -m pytest                                           # Tests
python -m aktienfinder.scanner AAPL MSFT SAP.DE            # einzelne Ticker
python -m aktienfinder.scanner --all --debug --file tickers/beispiele.txt   # Referenz-Trades mit allen Signalterminen
python -m aktienfinder.universe --out universe.csv --regions us   # Aktienliste
python -m aktienfinder.scanner --universe universe.csv --out site/data/results.json
python -m http.server -d site                              # Website unter http://localhost:8000
```

Parameter (Zeitfenster, RSI-Länge, MACD-Einstellungen …) stehen in `aktienfinder/config.py`.

## Stand
- [x] Indikatoren: RSI, MACD, Momentum Bias Index (1:1 nach dem Original-Pine-Code)
- [x] Signal-Erkennung und Score (abgestimmt auf 5 Referenz-Trades, alle 5 werden gefunden)
- [x] Ticker-Universum USA/Europa/global
- [x] Website + täglicher Auto-Scan (GitHub Actions/Pages)
- [ ] Trefferquote auf dem Gesamtmarkt kalibrieren

## Lizenz-Hinweis
`aktienfinder/mbi.py` ist eine Portierung des TradingView-Indikators
„Momentum Bias Index [AlgoAlpha]“ (© AlgoAlpha) und steht wie das Original unter der
[Mozilla Public License 2.0](https://mozilla.org/MPL/2.0/).
