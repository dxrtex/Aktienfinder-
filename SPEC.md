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

## Universum
Nur **Mid und Large Caps**: Börsenwert ab 2 Mrd. US-Dollar (umgerechnet), keine Small Caps.
Quelle ist der Yahoo-Finance-Screener, je Land nur die Heimatbörse (keine Zweitlistings an
Nebenbörsen, keine OTC-Werte). Länder und Börsen stehen in `aktienfinder/markets.py`:
USA, 16 europäische Länder, Japan, Hongkong, Kanada, Australien, Indien, Südkorea, Taiwan,
Singapur, Brasilien, Mexiko, Südafrika, Israel, Neuseeland.

Grundfilter im Scanner: Kurs ≥ 1 $ und durchschnittlicher Tagesumsatz ≥ 1 Mio. $ (umgerechnet).
Auf der Website lässt sich die Börsenwert-Grenze weiter anheben (10 / 50 / 200 Mrd. $).

## Kriterien – der Analyse-Trichter

Reihenfolge wie bei der manuellen Analyse; jede Stufe ist Pflicht:

| # | Stufe | Umsetzung |
|---|---|---|
| 1 | Analysten-Kursziel ≥ 40 % über Kurs | Ø Kursziel von Yahoo Finance (nur live, für Treffer abgefragt); Website-Filter, Standard „ab 40 %“ |
| 2 | Starker Rückgang | Rücksetzer-Tief der letzten 30 Handelstage mind. 20 % unter dem 52-Wochen-Hoch |
| 3 | Fibonacci-Golden-Zone | Der Rücksetzer seit dem letzten Hoch hat 0,618 erreicht und 0,886 nicht unterschritten (± 0,03); Schwung = höchstes Hoch der letzten 150 Tage und tiefstes Tief davor |
| 4 | RSI-Divergenz (RSI 14) | klassisch oder versteckt; Pivot-Tiefs 3/3, Vergleich mit allen früheren Tiefs im Abstand von 4–60 Tagen |
| 5 | MACD (12/26/9) | rote Balken werden seit ≥ 3 Tagen kleiner, ≥ 50 % vom Tiefpunkt erholt **und die MACD-Linie steigt** |
| 6 | Momentum Bias Index (AlgoAlpha) | grünes X („Bullish TP Signal“) auf der Spitze der roten Balken über der Impulse Boundary |

Die Signale 4–6 müssen innerhalb von ~3 Wochen (15 Handelstage) zueinander auftreten, das
Bündel darf bis zu ~6 Wochen (30 Handelstage) alt sein.

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
5b. Abgleich mit den Referenz-Trades auf echten Daten, Trefferquote kalibrieren
6. Ausbau des Universums (Stufe 2–4)
