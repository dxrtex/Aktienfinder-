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
| 3 | Fibonacci-Golden-Zone | Der Rücksetzer seit dem letzten Hoch hat mind. 0,618 erreicht; tiefer ist erlaubt (oft das stärkere Setup, wenn sich dabei Divergenzen bilden), nur nicht unter das Schwungtief (> 1,0; Toleranz ± 0,03). Schwung = höchstes Hoch der letzten 150 Tage bis zum Tief davor. Geprüft werden zwei Schwünge: der kurze (Tief im selben 150-Tage-Fenster) und der große (Tief bis 300 Handelstage vor dem Hoch, so wie man die Fibonacci in TradingView vom Tief der ganzen Aufwärtsbewegung zieht). Passt einer, ist das Kriterium erfüllt. „★“ auf der Website = in der Golden Zone 0,618–0,79 |
| 4 | RSI-Divergenz (RSI 14) | klassisch oder versteckt; Pivot-Tiefs 3/3, Vergleich mit allen früheren Tiefs im Abstand von 4–60 Tagen |
| 5 | MACD (12/26/9) | rote Balken werden seit ≥ 3 Tagen kleiner, ≥ 50 % vom Tiefpunkt erholt **und die MACD-Linie fällt nicht mehr** (seitwärts oder steigend, verglichen mit vor 3 Tagen) |
| 6 | Momentum Bias Index (AlgoAlpha) | grünes X („Bullish TP Signal“) auf der Spitze der roten Balken über der Impulse Boundary |

Die Signale 4–6 müssen innerhalb von ~3 Wochen (15 Handelstage) zueinander auftreten, das
Bündel darf bis zu ~6 Wochen (30 Handelstage) alt sein.

### Score (0–100) – bevorzugt vollständige Setups, die noch NICHT gestiegen sind
Wird für jede Aktie berechnet (auch Watchlist-Aktien ohne vollständiges Setup).

| Merkmal | Punkte |
|---|---|
| **Gesamtpaket:** je Kernkriterium 5 Punkte – Rückgang ≥ 20 %, Fibonacci, RSI-Divergenz (klassisch/versteckt), MACD-Histogramm rot & schrumpfend mit nicht mehr fallenden Linien, grünes MBI-X | 25 |
| **Bonus, wenn alle 5 Kernkriterien erfüllt sind** | 16 |
| MACD-Histogramm noch rot: je näher an 0 (Anteil des tiefsten roten Balkens der letzten 20 T., der aufgeholt ist) / schon seit ≤ 3 T. grün | bis 12 / 3 |
| Einstiegsnähe: Kurs höchstens +5 % über dem Tief der letzten 30 Tage → voll, ab +20 % → 0 | bis 10 |
| Umkehrkerze mit Volumen an einer Fib-Linie (letzte 3 Tage) | 6 |
| RSI an der gelben Signallinie (−2 … +5 Punkte) | 6 |
| Frische des jüngsten Signals | bis 5 |
| Zwei oder mehr grüne MBI-X / rote MBI-Balken rückläufig | 4 / 4 |
| Rücksetzer ≥ 30 % vom Hoch (im Backtest der stärkste Einzelfaktor: +20 % in 60 T. bei 53 % statt 40 %) | 6 |
| Klassische Divergenz / in der Golden Zone | 3 / 3 |

Damit landet eine Aktie, der ein Kernkriterium fehlt, immer deutlich hinter vollständigen Setups.

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

## Backtest-Ergebnis Swing-Trading (Okt. 2026, 5 Jahre, ~4.900 Aktien)
Gemessen: Wird innerhalb von 60 Handelstagen (Tageshoch) +10 / +20 / +30 % erreicht?

| Gruppe | +10 % | +20 % | +30 % |
|---|---|---|---|
| Zufall, alle Aktien | 58 % | 30 % | 16 % |
| Zufall nach ≥ 20 % Rückgang + Fib-Zone | 66 % | 40 % | 24 % |
| Scanner-Signal (vollständiger Trichter) | 66 % | 40 % | 24 % |
| 5 von 5 Kernkriterien | 68 % | 41 % | 25 % |
| Rücksetzer ≥ 30 % vom Hoch | 74 % | 53 % | 37 % |
| Status Einstiegsbereit / Schon gelaufen | 62 % / 72 % | 35 % / 47 % | 19 % / 32 % |

Fazit: Der Vorteil kommt vor allem aus „deutlich gefallen + Fibonacci“ und einem tiefen Rücksetzer.
RSI/MACD/MBI verbessern die Trefferquote im Schnitt kaum; Aktien, die schon vom Tief steigen,
liefen statistisch eher besser. Der Scanner bleibt ein Vorfilter für die eigene Chartprüfung.

## Erweiterungen (Okt. 2026)
- **Divergenz in Bildung:** Die letzte Kerze(n) bilden ein neues 2-Wochen-Tief, das noch nicht durch 3 Folgekerzen
  bestätigt ist, aber mit einem früheren bestätigten RSI-Tief bereits eine Divergenz zeigt (RSI mind. 2 Punkte
  Abstand). Nur Hinweis (+4 Punkte, wenn noch keine bestätigte Divergenz vorliegt), kein Kernkriterium.
- **Chance/Risiko:** Stop 3 % unter dem Rücksetzer-Tief, technisches Ziel = Fib 0,382 des Schwungs (liegt das
  schon unter dem Kurs: das Schwunghoch). Chance/Risiko = (Ziel − Kurs) / (Kurs − Stop).
- **Quartalszahlen:** nächster Termin von Yahoo; Warnung auf der Karte, wenn er in den nächsten 10 Tagen liegt.
- **Top-Auswahl:** alle 5 Kernkriterien, Chance/Risiko ≥ 2 : 1, keine Quartalszahlen in den nächsten 10 Tagen
  (zusätzlich gilt der Kursziel-Filter). Wird beim Top-Setup des Tages bevorzugt.
- **Backtest Stufe B:** prüft Marktumfeld (Index über EMA 200), langfristigen Trend der Aktie, relative Stärke,
  nachlassendes Volumen, Chance/Risiko und einen bestätigten Einstieg (erst wenn das MACD-Histogramm grün wird).
  Übernommen wird nur, was die Trefferquote messbar verbessert.

## Optimierung mit echten Trades (Okt. 2026)
Backtest-Trade: Kauf zur Eröffnung am Folgetag, Stop 3 % unter dem Rücksetzer-Tief, Verkauf bei +20 %,
sonst nach 60 Handelstagen. Optimiert auf das Ø-Ergebnis je Trade; Auswahl auf 2021–Nov. 2024, Prüfung auf
Nov. 2024–2026. Basis (alle Signale): Ø +2,7 % je Trade, Ziel vor Stop 31 %.

| Filter (Test-Hälfte) | Ø je Trade | Ziel vor Stop |
|---|---|---|
| Relative Stärke 3 Mon. > 0 | +5,3 % | 42 % |
| Rücksetzer ≥ 40 % | +3,5 % | 43 % |
| Kurs 5–20 % über dem Tief | +3,2 % | 35 % |
| Kurs 0–8 % über dem Tief (Einstieg am Tief) | +1,2 % | 22 % |
| Chance/Risiko ≥ 2 | +1,4 % | 26 % (enger Stop wird oft gerissen) |
| Markt über EMA 200 | +1,6 % | 28 % |
| **Top-Auswahl: rel. Stärke > 0, 5–20 % über Tief, ≥ 2 grüne X** | **+6,4 %** (Lernen +4,5 %) | 41 %, Median +10,4 % |

Daraus folgt: Top-Auswahl und Status „Einstiegsbereit“ = vollständiges Setup + Kursziel ≥ 40 % + relative
Stärke > 0 + Kurs 5–20 % über dem Tief + ≥ 2 grüne MBI-X + keine Quartalszahlen in 10 Tagen.
„Schon gelaufen“ erst ab +20 % über dem Tief. Chance/Risiko wird nur angezeigt, nicht gefiltert.
Hinweis: Vergangene Ergebnisse sind keine Garantie; der Zeitraum enthält keinen langen Bärenmarkt.

## Aktuelle Top-Auswahl (Entscheidung Okt. 2026)
Vollständiges Setup (Rückgang ≥ 20 %, Fibonacci, RSI-Divergenz, MACD, mind. 1 grünes MBI-X) + Analysten-Kursziel
≥ 40 % + relative Stärke 3 Monate > 0. Kein Filter auf Abstand zum Tief, keine Quartalszahlen-Regel.
Sortiert nach Score. Backtests laufen nur noch manuell.
