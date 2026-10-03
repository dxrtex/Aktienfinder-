# Aktienfinder

Scannt den Aktienmarkt täglich nach bullischen Umkehrsignalen und zeigt die Treffer als
sortierbare Tabelle auf einer Website. Die Kriterien stehen in [SPEC.md](SPEC.md).

Pflichtsignale (innerhalb von ~3 Wochen zueinander, Bündel höchstens ~6 Wochen alt):
- bullische RSI-Divergenz (klassisch oder versteckt)
- MACD-Histogramm rot, aber kleiner werdend und kurz vor Grün
- grünes X im Momentum Bias Index (AlgoAlpha)

Kursrückgang, Fibonacci-Zone, Ausbruch über die EMA 20 und Volumen fließen nur in den Score ein.

## Lokal ausführen

```bash
pip install -r requirements-dev.txt
python -m pytest                              # Tests
python -m aktienfinder.scanner AAPL MSFT SAP.DE   # Scan einzelner Ticker
python -m aktienfinder.scanner --all NVDA     # auch Aktien ohne Treffer anzeigen
python -m aktienfinder.scanner --all --file tickers/beispiele.txt   # Referenz-Trades prüfen
```

Parameter (Zeitfenster, RSI-Länge, MACD-Einstellungen …) stehen in `aktienfinder/config.py`.

## Stand
- [x] Indikatoren: RSI, MACD, Momentum Bias Index (1:1 nach dem Original-Pine-Code)
- [x] Signal-Erkennung und Score (abgestimmt auf 5 Referenz-Trades)
- [x] Scanner-Kommandozeile
- [ ] Ticker-Listen (USA, Europa, global)
- [ ] Website + täglicher Auto-Scan (GitHub Actions/Pages)

## Lizenz-Hinweis
`aktienfinder/mbi.py` ist eine Portierung des TradingView-Indikators
„Momentum Bias Index [AlgoAlpha]“ (© AlgoAlpha) und steht wie das Original unter der
[Mozilla Public License 2.0](https://mozilla.org/MPL/2.0/).
