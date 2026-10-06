# Kairo – Reversal-Setup-Finder

Scannt täglich **alle Aktien ab 2 Mrd. USD Börsenwert in Nordamerika (USA, Kanada), Westeuropa und Asien/Pazifik** auf ein festes
Long-Reversal-Setup im Tageschart, bewertet jeden Treffer mit einem **Score von 0–100** und zeigt
Treffer und Fast-Treffer auf einer Website mit interaktiven Charts.

**Website:** https://dxrtex.github.io/Kairo/  (auf dem iPad über „Teilen → Zum Home-Bildschirm“ als App)

> Keine Anlageberatung. Signale sind rein technisch und ersetzen keine eigene Prüfung.

## Das Setup (alle Pflicht)
1. **Korrektur:** Rückgang ≥ 12 % vom Swing-High (höchstes Pivot-High der letzten 20–180 Tage), kein Crash
   (kein Tagesverlust > 25 % in 10 Tagen), Kurs unter EMA 20 und EMA 50, EMA 20 fällt, Abflachung der letzten 10 Kerzen.
2. **Unterstützungszone:** Fibonacci 0,618–0,79 (Variante A) **oder** horizontaler Mehrfachboden mit ≥ 2 Touches ± 3 % (Variante B).
3. **RSI(14):** bullische Divergenz (klassisch oder versteckt; Tiefs mind. 2 Kerzen auseinander, gleich tiefe Doppelböden zählen), RSI aktuell 28–48.
4. **MACD(12/26/9):** Linie und Signal unter 0 und bullisches Kreuz ≤ 7 Kerzen **oder** Histogramm seit ≥ 4 Kerzen steigend
   und ≤ 25 % seines 30-Tage-Tiefs.
5. **Momentum Bias Index [AlgoAlpha]:** grünes X auf einer roten Spitze (über der Referenzlinie) in den letzten 15 Kerzen,
   seitdem rote Balken ≤ 70 % der Spitze oder Histogramm grün.
6. **Risiko:** Chance-Risiko (Ziel 2 / Stop) ≥ 2,0. Earnings in den nächsten 5 Handelstagen: Score −15.

Fast-Treffer = genau ein Pflichtkriterium fehlt (welches, steht dabei).

## Aufbau der App
Leiste unten: **Scanner** (eine Tabelle; oben frei kombinierbar ★ Merkliste / Treffer / Fast-Treffer / Watchlist + Filter; Stern ☆ setzt eine Aktie auf die eigene Merkliste – nur auf dem Gerät gespeichert; Name antippen öffnet die Übersichtskarte mit Mini-Chart, Kriterien, Hinweis und **Marktstimmung** (Analysten-Konsens, Ø Kursziel, Branche, Gesamtmarkt, drei aktuelle Schlagzeilen grob eingeordnet – Yahoo Finance, alle 3 Tage aktualisiert); Score antippen = Zusammensetzung, „i“ = Kurzbeschreibung; Spalte „Prognose“ = Pfeil ▲ ► ▼: erwartete Richtung der erfüllten Kriterien in den nächsten 5 Handelstagen – lineares Modell aus `backend/forecast.py` (ablaufende Zeitfenster, Signale kurz vor dem Eintreten, RSI/MACD, Verlauf), geschätzt per Workflow „Prognose-Modell schätzen“ an 250 zufälligen Aktien über 2 Jahre, geprüft an der anderen Hälfte: Pfeil-Richtung in 57 % richtig, Modell in `data/forecast_model.json`), **Kalender** (Monatsansicht Mo–Fr oder Liste), **Depot**, **Journal**, **Einstellungen** (u. a. Name für die Begrüßung).

- **Journal:** alle Transaktionen aus dem Scalable-Export (bleiben auf dem Gerät). Käufe/Verkäufe je Wertpapier nach FIFO zu Trades zugeordnet (Eröffnung bis Bestand 0), Ergebnis inkl. Ordergebühren, vor Steuern. Realisiertes Ergebnis, Trefferquote, Profit-Faktor, Ø Gewinner/Verlierer, Erwartung je Trade, Haltedauer, max. Rückgang, Gebühren, Dividenden & Zinsen, Ergebnis-Kurve, Monatsbalken, Auswertung nach Art (Turbo Long/Short, Aktien, ETFs) und Basiswert, automatische Hinweise, sortierbare Trade-Liste, offene Positionen, alle Transaktionen.
- **Turbo-Plan** (Detailseite, ersetzt Trade-Plan und Positionsrechner): Entry, Setup-Grenze (Stop), Ziel 1/2; Rechner mit Einsatz und K.-o.-Schwelle (Vorschlag ½ ATR unter der Setup-Grenze) → Hebel, Turbo-Ergebnis in % und € je Szenario (Ziele, Stop, Knock-out), Chance : Risiko.

- **Kalender:** Quartalszahlen, Ex-Dividende und Dividendenzahlung (Yahoo Finance) für Watchlist-, Depot- und
  Treffer-Aktien, dazu Fed- und EZB-Zinsentscheide, US-Inflation (CPI) und US-Arbeitsmarktbericht – automatisch von den offiziellen Seiten
  (`backend/macro.py`, Ersatz: `data/macro_events.json`) – und der große Verfall. Fehlende Quartalstermine von Watchlist-Aktien
  werden einzeln nachgeholt.
  Datei: `site/data/calendar.json`.
- **Depot:** Positionen von Hand oder per Import des Transaktions-Exports aus Scalable Capital (Excel, auch mit
  Endung .csv) – gespeichert nur im Browser des Geräts. Turbo-/Knock-out-Zertifikate werden über den Basiswert bewertet.
  Für Aktien mit Detailseite (Watchlist, Treffer, Fast-Treffer) gibt es die **Positions-Analyse** aus
  `site/data/analysis.json` (`backend/analysis.py`): Urteil 0–100 aus Trend, MACD, RSI, MBI, Divergenz, Fibonacci,
  relativer Stärke, Branche (Sektor-ETF), Gesamtmarkt (S&P 500, VIX), und Quartalszahlen; Stop-Loss unter
  der nächsten Unterstützung (≥ 1 ATR entfernt), zwei Ziele an Widerständen bzw. Fib-Extensionen mit „Chance vor Stop“
  (Zufallspfad mit leichter Trend-Drift) und typischer Dauer; Depot-Übersicht (Einsatz, geschätzter Wert, Wert aller Turbos bei Knock-out, größter Klumpen); Positionen je Basiswert gruppiert und aufklappbar mit Kurschart (alle Käufe, Ø-Kauf, Take-Profit-Zonen, K.-o.), Take Profits TP 1, 2, 3 … = Treppe der relevanten Hochs über dem Kurs (Schlusskurse; seitdem nie überschritten; Gipfel einer eigenen Erholungswelle ≥ 3,5 % bzw. 0,8 ATR, ≥ 15 Handelstage nach dem vorigen Hoch; nahe Hochs ± 4 % als Zone) und „Allzeithoch“ (komplette Historie) mit Chance in 3 und 6 Monaten (Maximum einer Brownschen Bewegung mit Drift), Positionstabelle und Bewertung jedes Einstiegs;
  Bewertung des Einstiegs (Lage in der 20-Tage-Spanne, RSI, Abstand zur EMA 20). Bei Turbos schätzt die App das
  Bezugsverhältnis aus dem Kaufkurs und rechnet Stop/Ziele in Zertifikatskurse um. Eine direkte Verbindung zu Scalable
  Capital gibt es nicht (keine offizielle Schnittstelle).

## Profi-Funktionen
- **Heute** (Startseite): Markt-Lage (Risk-on/off, S&P 500, Nasdaq, DAX, VIX), was sich seit dem letzten Scan geändert hat (neue/weggefallene Treffer, Bewegung deiner Aktien), deine Aktien mit Status und Prognose, Kairo-Bilanz, Depot-Kurzblick mit knappstem K.-o.-Abstand, Termine der nächsten Tage, beste Treffer, Journal-Kurzblick. Einstellungen über das Zahnrad oben rechts.
- **Kairo-Bilanz:** Backtest (`backend/bilanz.py`, Workflow „Kairo-Bilanz“, 8 parallele Teile, 1.600 zufällige Aktien, 2 Jahre): für jedes Treffer-Signal, ob zuerst Ziel 1 oder der Stop erreicht wurde, Ergebnis in R, Renditen nach 5/10/20 Tagen – nach Score, CRV, Zone und Divergenz, im Vergleich zu Fast-Treffern und zufälligen Tagen. Dazu die **Live-Bilanz**: jedes neue Signal wird am Signaltag gespeichert (Branch `kairo-data`) und täglich nachverfolgt.
- **Telegram-Abendbericht** (`backend/telegram.py`): Markt, neue Treffer, Veränderungen bei Merkliste/Watchlist/Depot, Knock-out-Warnungen (< 8 %), Termine. Einrichtung: Secret `TELEGRAM_TOKEN`, dem Bot `/start` schreiben; Merkliste und Depot über Einstellungen → „an den Bot senden“ (`/sync …`, nur Ticker und K.-o.-Schwellen).
- **Fundament & Wochentrend** in der Übersicht: KGV im Vergleich zum Branchen-Median, Umsatzwachstum, Marge, Verschuldung (Ampel) und Trend im Wochenchart (EMA 10/30, Wochen-RSI).
- **Journal-Notizen:** Trade antippen → Kairo-Bewertung des Einstiegs (Lage, RSI, MACD, MBI, EMA am Kauftag), Tags (nach Plan, FOMO, zu früh …) und Notiz; Auswertung „Nach Tags“.
- **Backup:** alle lokalen Daten als Datei sichern und auf einem anderen Gerät einlesen.
- **Komfort:** Filter-Vorlagen als Schnellwahl, Spalten ein-/ausblenden, auf dem iPad quer die Übersicht als Seitenpanel, Offline-Modus (Service Worker).

## Volatilität
Zu jeder Aktie wird die **historische Volatilität** berechnet: Standardabweichung der Tagesrenditen der letzten 30 Tage,
hochgerechnet aufs Jahr (× √252), dazu die Ø Tagesspanne (ATR 14 in % vom Kurs). Kein Pflichtkriterium – nur Filter
(niedrig < 30 %, mittel 30–50 %, hoch 50–80 %, sehr hoch > 80 %), Sortierung und Tabellenspalte. Zeitraum: `volatility.days`.

## Suche mit Kurz-Hinweis
Die Suche oben findet **jede geprüfte Aktie** (nicht nur Treffer) und zeigt einen kurzen Hinweis, wo sie im Setup steht,
z. B. „Fällt noch stark – Konsolidierung frühestens in ca. 3 Tagen“, „In der Zone – MACD-Kreuz in ca. 4 Tagen“ oder
„Einstiegs-Setup – noch ca. 5 Tage gültig, Ausbruch über EMA 20 beendet das Setup“. Die Tage sind Handelstage und grobe
Schätzungen aus den Regeln (Zeitfenster von MBI-X, MACD-Kreuz und RSI-Tief; Abflachung bei Seitwärtslauf).
Logik: `backend/hints.py`, Index: `site/data/search.json`.

## Parameter
Alle Schwellen stehen in **`config.yaml`** (Abschnitte wie im Prompt: `correction`, `fib`, `support`, `rsi`, `macd`, `mbi`,
`risk`, `score`). Ändern: Datei auf GitHub bearbeiten → *Actions → Täglicher Scan → Run workflow*.
Die Website zeigt die aktiven Werte unter **Einstellungen**.

## Ablauf & Technik
| Teil | Datei |
|---|---|
| Datenquelle (austauschbar, `DataProvider`), SQLite-Cache | `backend/data_provider.py` |
| Indikatoren (EMA, RSI nach Wilder, MACD, ATR, Pivots) – selbst implementiert | `backend/indicators.py` |
| Momentum Bias Index – 1:1-Port des Original-Pine-Scripts | `backend/mbi.py` |
| Pflichtkriterien, Trade-Plan | `backend/scanner.py` |
| Score | `backend/scoring.py` |
| Kurz-Hinweis je Aktie für die Suche | `backend/hints.py` |
| Universum (Nordamerika, Westeuropa, Asien/Pazifik ab 2 Mrd. USD) | `backend/universe.py` → `data/universe_us.csv`, `data/universe_eu.csv`, `data/universe_asia.csv` |
| Täglicher Scan → `site/data/` (inkl. Watchlist aus `data/watchlist.json`) | `backend/run_scan.py` |
| Regressionstest mit den 5 Beispielen, Rückblick (`--timeline TICKER`) | `backend/regression.py` |
| Parameter-Vergleich auf dem Kurs-Cache (`python -m backend.compare rsi.t1_min_gap=10`) | `backend/compare.py` |
| Website (Treffer, Tabelle, Fast-Treffer, Detailseite, Einstellungen, CSV/Excel) | `site/index.html` |

Der Scan läuft **werktags um 22:30 Uhr (Berlin)** über GitHub Actions (`.github/workflows/scan.yml`) und veröffentlicht
die Website über GitHub Pages. „Scan jetzt starten“: *Actions → Täglicher Scan → Run workflow*.

**Abweichung vom Prompt:** Statt eines lokalen FastAPI-Servers mit APScheduler (localhost:8000) laufen Scan und Website
über GitHub Actions und GitHub Pages – so funktioniert alles auf dem iPad ohne eigenen Rechner. Die Parameter sind deshalb
in der Website sichtbar, geändert werden sie in `config.yaml`.

## Lokal ausführen (optional)
```bash
pip install -r requirements-dev.txt
python -m pytest -q backend/tests      # Unit-Tests
python -m backend.regression           # Regressionstest (Daten bis 02.10.2026)
python -m backend.universe             # Universum aktualisieren
python -m backend.run_scan             # Scan → site/data/
python -m http.server -d site 8000     # Website unter http://localhost:8000
```
