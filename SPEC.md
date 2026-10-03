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
| 3 | Fibonacci-Golden-Zone | Der Rücksetzer seit dem letzten Hoch hat mind. 0,618 erreicht; tiefer ist erlaubt (oft das stärkere Setup, wenn sich dabei Divergenzen bilden), nur nicht unter das Schwungtief (> 1,0; Toleranz ± 0,03). Schwung = höchstes Hoch der letzten 150 Tage und tiefstes Tief davor. „★“ auf der Website = in der Golden Zone 0,618–0,79 |
| 4 | RSI-Divergenz (RSI 14) | klassisch oder versteckt; Pivot-Tiefs 3/3, Vergleich mit allen früheren Tiefs im Abstand von 4–60 Tagen |
| 5 | MACD (12/26/9) | rote Balken werden seit ≥ 3 Tagen kleiner, ≥ 50 % vom Tiefpunkt erholt **und die MACD-Linie fällt nicht mehr** (seitwärts oder steigend, verglichen mit vor 3 Tagen) |
| 6 | Momentum Bias Index (AlgoAlpha) | grünes X („Bullish TP Signal“) auf der Spitze der roten Balken über der Impulse Boundary |

Die Signale 4–6 müssen innerhalb von ~3 Wochen (15 Handelstage) zueinander auftreten, das
Bündel darf bis zu ~6 Wochen (30 Handelstage) alt sein.

### Score (0–100) – bevorzugt vollständige Setups, die noch NICHT gestiegen sind
Wird für jede Aktie berechnet (auch Watchlist-Aktien ohne vollständiges Setup).

| Merkmal | Punkte |
|---|---|
| **MACD-Histogramm noch rot und schrumpfend:** 9 + bis 10 je nach Nähe zur 0-Linie (Anteil des tiefsten roten Balkens der letzten 20 T., der schon aufgeholt ist) + 3, wenn die MACD-Linien nicht mehr fallen | bis 22 |
| MACD schon grün (seit ≤ 3 T.) / nur Signal im Fenster | 6 / 2 |
| **Einstiegsnähe:** Kurs höchstens +5 % über dem Tief der letzten 30 Tage → voll, ab +20 % → 0 | bis 16 |
| Divergenz klassisch / versteckt | 12 / 9 |
| Grüne MBI-X im Fenster: ≥ 2 / 1 | 12 / 8 |
| Umkehrkerze mit Volumen an einer Fib-Linie (letzte 3 Tage) | 8 |
| RSI an der gelben Signallinie (−2 … +5 Punkte) | 8 |
| Fibonacci: in der Golden Zone / darunter (bis Schwungtief) | 8 / 6 |
| Frische des jüngsten Signals | bis 5 |
| Rücksetzer ≥ 30 % / ≥ 20 % | 5 / 3 |
| Rote MBI-Balken rückläufig | 4 |

Der Ausbruch über die EMA 20 zählt nicht mehr (er belohnte bereits gestiegene Aktien).

### Setup-Status (regelbasiert, keine Kursprognose)
| Status | Regel |
|---|---|
| 🟢 Einstiegsbereit | vollständiges Setup, Kurs ≤ +8 % über dem Tief, kein neues Tief in den letzten 2 Tagen, MACD-Histogramm **noch rot** und schrumpfend, MACD-Linien fallen nicht mehr, Verkaufsdruck im MBI rückläufig (oder Käufer vorne) |
| 🟡 Abwarten | vollständiges Setup, aber noch nicht alle Einstiegsbedingungen – oder (Watchlist) mind. 3 von 6 Kriterien erfüllt |
| 🔴 Schon gelaufen | Kurs ≥ +15 % über dem Tief oder MACD seit > 10 Tagen grün |
| ⚪ Kein Setup | (nur Watchlist) weniger als 3 Kriterien erfüllt |

### Watchlist
Alle Aktien aus `site/watchlist.json` werden täglich bewertet – auch ohne vollständiges Setup und
unabhängig von Börsenwert/Liquidität. Die Website zeigt je Kriterium erfüllt ✓ / fehlt ✗.

### Musterbeispiel: Uber, 2. Oktober 2026 („nahezu perfekter Einstieg“)
- Analysten-Kursziel +48 %
- Fibonacci trifft zu: Rücksetzer bis an die letzte Fib-Grenze, dort gehalten
- MACD: Linien fallen nicht mehr, laufen seitwärts; rote Histogramme nehmen massiv ab, fast bei 0
- RSI: lila Linie liegt fast auf der gelben Signallinie; klare bullische Divergenz fehlt
  (Scanner erkennt eine versteckte Divergenz 1. Aug. → 28. Sep.)
- MBI: zwei grüne X hintereinander (16. und 23. Sep.), rote Balken rückläufig
- Letzte Kerze: stark bullisch mit sehr hohem Volumen, an der Fib-Grenze gehalten
- Einstieg *bevor* der Kurs steigt

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
