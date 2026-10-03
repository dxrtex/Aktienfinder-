# Aktienfinder – Spezifikation

Stand: 2026-10-03

## Ziel
Täglicher automatischer Scan des weltweiten Aktienmarkts nach Aktien mit
bullischen Umkehrsignalen. Die Ergebnisse erscheinen als sortierbare Tabelle auf einer Website.

## Technik
- **Scanner:** Python (pandas, yfinance), Tageskerzen
- **Ausführung:** GitHub Actions, werktags nach US-Börsenschluss
- **Website:** GitHub Pages (statische Seite, fester Link), sortierbare Tabelle
- **Benachrichtigung:** keine

## Universum (stufenweiser Ausbau)
1. USA, große Werte (S&P 500, Nasdaq 100)
2. Gesamter US-Markt
3. Deutschland/Europa (DAX, MDAX, SDAX, STOXX 600 …)
4. Weitere globale Börsen

Grundfilter: Mindestkurs und Mindest-Tagesumsatz (keine Pennystocks/illiquiden Werte).

## Kriterien

### Pflicht (alle drei müssen erfüllt sein)
Die drei Signale müssen **dicht beieinander** auftreten: höchstens ~3 Wochen
(15 Handelstage) zwischen dem ersten und dem letzten Signal. Das Bündel darf bis zu
~6 Wochen (30 Handelstage) alt sein, weil der Einstieg oft erst Wochen später beim
Ausbruch aus der Bodenzone erfolgt.

| Kriterium | Definition (Startwerte, anpassbar in `aktienfinder/config.py`) |
|---|---|
| RSI-Divergenz (RSI 14) | **Klassisch:** Kurs tieferes Tief, RSI höheres Tief. **Versteckt:** Kurs höheres Tief, RSI tieferes Tief. Pivot-Tiefs auf dem RSI (3 Balken links/rechts). Jedes Tief wird mit **allen** früheren Tiefs im Abstand von 4–60 Tagen verglichen. |
| MACD-Histogramm (12/26/9) | Histogramm noch negativ, die Balken werden seit ≥ 3 Tagen kleiner und haben sich um ≥ 50 % vom Tiefpunkt erholt (kurz vor dem Wechsel ins Positive). |
| Momentum Bias Index (AlgoAlpha, close 10 5 10 30 3) | Grünes X = Spitze eines roten Bergs, die mindestens die gepunktete Linie (Impulse Boundary) erreicht. |

### Weich (Score 0–100, kein Ausschluss)
| Kriterium | Punkte |
|---|---|
| Divergenzart | klassisch 15, nur versteckt 12 |
| Bündel | bis 15: je enger und frischer, desto mehr |
| MACD jetzt | rot und schrumpfend 10, seit ≤ 10 Tagen grün 8, sonst 4 |
| MBI jetzt | grüne Balken (Käufer übernehmen) 5 |
| Kursrückgang | Abstand zum 52-Wochen-Hoch, ab −20 % volle 15 |
| Fibonacci | Rücksetzer bis in die Zone 0,618–0,886 des letzten Aufwärtsschwungs 15 |
| Einstiegs-Trigger | Ausbruch über die EMA 20 in den letzten 5 Tagen 15 (länger darüber 7) |
| Volumen | Spike am Tief 5, erhöhtes Volumen in den letzten 5 Tagen 5 |

### Referenz-Trades
Aus Chart-Screenshots abgeleitet (D-Wave, Rocket Lab, Infineon, Uber, TUI; `tickers/beispiele.txt`):
- Das grüne MBI-X kommt nur bei Spitzen über der gepunkteten Linie, mehrere Spitzen können je ein X erzeugen.
- Divergenzen beziehen sich oft auf ein Tief, das Wochen zurückliegt (Uber: versteckt, 1. Aug. → Ende Sep.).
- Die Signale liegen 0–3 Wochen auseinander. Eingestiegen wird entweder früh (Uber: MACD noch rot) oder
  beim Ausbruch aus der Bodenzone über die EMA 20 (Infineon, TUI, D-Wave).

## Ausgabe (Website)
Sortierbare Tabelle mit diesen Spalten: Ticker, Name, Börse/Land, Kurs, Abstand zum Hoch in %, RSI,
Divergenzart, MACD-Status, MBI-Signal (vor wie vielen Tagen), Volumen-Signal, Score
und Link zum TradingView-Chart.

## Umsetzungsschritte
1. Indikatoren in Python (RSI, MACD, MBI-Nachbau) und Abgleich mit TradingView
2. Signal-Erkennung (Divergenzen, MACD, MBI-X) und Scoring
3. Scanner für Stufe 1 (große US-Werte), lokaler Testlauf
4. Website (sortierbare Tabelle)
5. GitHub Actions + GitHub Pages (täglicher Auto-Scan, Link)
5b. Abgleich mit den Referenz-Trades auf echten Daten, MBI-Original-Code einbauen
6. Ausbau des Universums (Stufe 2–4)
