# Reversal-Setup-Finder

Scannt täglich **alle Aktien ab 2 Mrd. USD Börsenwert in Nordamerika (USA, Kanada), Westeuropa und Asien/Pazifik** auf ein festes
Long-Reversal-Setup im Tageschart, bewertet jeden Treffer mit einem **Score von 0–100** und zeigt
Treffer und Fast-Treffer auf einer Website mit interaktiven Charts.

**Website:** https://dxrtex.github.io/Aktienfinder-/  (auf dem iPad über „Teilen → Zum Home-Bildschirm“ als App)

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
| Regressionstest mit den 5 Beispielen | `backend/regression.py` |
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
