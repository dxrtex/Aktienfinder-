"""Regressionstest (6.1): die 5 Beispielaktien mit Daten bis einschließlich 02.10.2026.

Gibt je Aktie eine Tabelle aus: Kriterium | erfüllt | Messwert | Schwelle – plus Trade-Plan,
Score und ob die Aktie die Treffer- oder Fast-Treffer-Liste erreicht.

Aufruf:  python -m backend.regression  [--out regression.md]
"""

import argparse

import pandas as pd

from .config import CONFIG
from .data_provider import YFinanceProvider
from .scanner import de, evaluate, pct

EXPECTED = {   # Erwartete Größenordnungen aus dem Prompt (Tageschart)
    "TUI1.DE": "Kurs ≈ 6,53 € in Fib 0,706–0,79 (6,62–6,46), RSI ≈ 36",
    "UBER": "≈ 60,5 € in 0,706–0,79 (61,38–60,28), RSI ≈ 41",
    "IFX.DE": "≈ 54 € auf Support ~54–55 €, MACD bereits gekreuzt",
    "RKLB": "≈ 63,5 $ knapp unter Support ~66 $ (Retest von unten), MACD gekreuzt",
    "QBTS": "≈ 14,2 € auf Mehrfachboden ~14–14,5 €",
}


def report(ticker: str, res, info: dict) -> str:
    out = [f"## {ticker} – {info.get('name', '')}", "",
           f"Stand {res.date} · Schluss {de(res.close)} {res.flags.get('currency', '')} · "
           f"Erwartung laut Prompt: {EXPECTED.get(ticker, '–')}", "",
           "| Kriterium | erfüllt | Messwert | Schwelle |", "|---|---|---|---|"]
    for c in res.criteria:
        out.append(f"| {c.label} | {'✓' if c.ok else '✗'} | {c.value} | {c.threshold} |")
    status = "TREFFER" if res.passed else ("FAST-TREFFER (fehlt: " + res.missing[0].label + ")" if res.fast_hit
                                          else f"kein Treffer – {len(res.missing)} Kriterien fehlen: "
                                               + ", ".join(c.label for c in res.missing))
    out += ["", f"**Ergebnis: {status}** · Score {res.score}"]
    if res.bonuses:
        out.append("Score-Bausteine: " + ", ".join(f"{k} {v:+d}" for k, v in res.bonuses))
    p = res.plan
    if p:
        out.append(f"Trade-Plan: Entry {de(p['entry'])} (Buy-Stop {de(p['buy_stop'])}) · Stop {de(p['stop'])} "
                   f"(−{pct(p['stop_pct'])}) · Ziel 1 {de(p['target1'])} · Ziel 2 {de(p['target2'])} · "
                   f"CRV {de(p['crv'])} · max. Hebel {de(p['max_leverage'], 1)}")
    f = res.flags
    out.append(f"Zusatz: RSI {de(f['rsi'], 1)}, EMA20 {de(f['ema20'])}, EMA50 {de(f['ema50'])}, EMA200 {de(f['ema200'])}, "
               f"ATR {de(f['atr'])}, Earnings {f.get('earnings_date') or 'unbekannt'}"
               + (" ⚠ Earnings-Risiko" if f.get("earnings_risk") else ""))
    z = res.zone.get("fib")
    if z:
        lv = z["levels"]
        out.append(f"Fib (H {de(res.zone['H'])} am {res.zone['H_date']}, L {de(z['L'])} am {z['L_date']}): "
                   + " · ".join(f"{k.replace('.', ',')} = {de(v)}" for k, v in lv.items()))
    s = res.zone.get("support")
    if s:
        out.append(f"Support: Mitte {de(s['center'])}, Touches {s['touches']} ({', '.join(s['touch_dates'])})")
    return "\n".join(out) + "\n"


def timeline(tickers: list[str], days: int) -> str:
    """Rückblick: Wie hätte der Scanner an jedem der letzten `days` Handelstage geurteilt?"""
    from .hints import hint
    prov = YFinanceProvider()
    data = prov.history(tickers, CONFIG.history.period)
    out = []
    for t in tickers:
        df = data.get(t)
        if df is None:
            out.append(f"## Rückblick {t}\nKEINE DATEN\n")
            continue
        out += [f"## Rückblick {t} – letzte {days} Handelstage", "",
                "| Datum | Schluss | Ergebnis | fehlt | Hinweis |", "|---|---|---|---|---|"]
        for i in range(len(df) - days, len(df)):
            res = evaluate(df.iloc[: i + 1], {"currency": "EUR" if t.endswith(".DE") else "USD"}, ticker=t)
            status = f"TREFFER (Score {res.score})" if res.passed else "Fast-Treffer" if res.fast_hit else f"{len(res.missing)} fehlen"
            miss = "; ".join(f"{c.label.split(' (')[0]} [{c.value}]" for c in res.missing)
            out.append(f"| {res.date} | {de(res.close)} | {status} | {miss or '–'} | {hint(res)['title']} |")
        # Kurs-Tiefs (Pivot-Länge rsi.pivot_len) mit RSI – zum Nachvollziehen der Divergenz
        from .indicators import pivot_lows, rsi
        r = rsi(df["Close"], CONFIG.rsi.length).to_numpy()
        tail = df.iloc[-(days + 15):]
        out += ["", f"Tageswerte (letzte {len(tail)} Kerzen), * = Pivot-Tief (Länge {CONFIG.rsi.pivot_len}):", "",
                "| Datum | Tief | RSI | |", "|---|---|---|---|"]
        piv = set(pivot_lows(df["Low"], CONFIG.rsi.pivot_len, getattr(CONFIG.rsi, "pivot_ties", False)))
        for k in range(len(df) - len(tail), len(df)):
            out.append(f"| {df.index[k].date()} | {de(df['Low'].iloc[k])} | {de(r[k], 1)} | {'*' if k in piv else ''} |")
        out.append("")
    return "\n".join(out)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out")
    ap.add_argument("--timeline", help="Rückblick für diese Ticker (kommagetrennt)")
    ap.add_argument("--days", type=int, default=20)
    args = ap.parse_args(argv)
    if args.timeline:
        print(timeline([t.strip() for t in args.timeline.split(",") if t.strip()], args.days))
        return 0
    rc = CONFIG.regression
    end_excl = str((pd.Timestamp(rc.end_date) + pd.Timedelta(days=1)).date())
    prov = YFinanceProvider()
    data = prov.history(list(rc.tickers), CONFIG.history.period, end=end_excl)
    infos = prov.infos(list(rc.tickers))
    parts = [f"# Regressionstest – Daten bis einschließlich {rc.end_date}\n"]
    summary = []
    for t in rc.tickers:
        if t not in data:
            parts.append(f"## {t}\nKEINE DATEN\n")
            summary.append((t, "keine Daten"))
            continue
        res = evaluate(data[t], infos.get(t), ticker=t)
        parts.append(report(t, res, infos.get(t, {})))
        summary.append((t, "Treffer" if res.passed else "Fast-Treffer" if res.fast_hit else f"{len(res.missing)} fehlen"))
    parts.insert(1, "| Aktie | Ergebnis |\n|---|---|\n" + "\n".join(f"| {t} | {s} |" for t, s in summary) + "\n")
    text = "\n".join(parts)
    print(text)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
