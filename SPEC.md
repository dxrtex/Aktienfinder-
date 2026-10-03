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
| Kriterium | Definition (Startwerte, anpassbar) |
|---|---|
| RSI-Divergenz (RSI 14) | **Klassisch:** Kurs tieferes Tief, RSI höheres Tief. **Versteckt:** Kurs höheres Tief, RSI tieferes Tief. Abstand der Tiefs 5–60 Tage, zweites Tief max. ~10 Tage alt. |
| MACD-Histogramm (12/26/9) | Histogramm noch negativ, die Balken werden seit ≥ 3 Tagen kleiner und liegen nahe der Nulllinie (kurz vor dem Wechsel ins Positive). |
| Momentum Bias Index (AlgoAlpha) | Grünes X (bullisches Erschöpfungs-/Take-Profit-Kreuz) in den letzten Tagen. Exakter Nachbau des Open-Source-Pine-Skripts. |

### Weich (fließen in den Score ein, kein Ausschluss)
| Kriterium | Definition |
|---|---|
| Kursrückgang | Abstand zum letzten Hoch bzw. 52-Wochen-Hoch/ATH; ab ca. −20 % volle Punkte |
| Volumen | z. B. Volumen-Spike am Tief, steigendes Volumen bei der Erholung |

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
6. Ausbau des Universums (Stufe 2–4)
