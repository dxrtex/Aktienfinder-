"""Rückblick für einzelne Aktien: Hätte Kairo an einem Tag ein Einstiegs-Setup gemeldet?

Für jeden Handelstag der letzten N Tage: Schlusskurs, Tagesänderung, Kairo (Treffer / Fast / x von 11),
Trend-Rücksetzer (ja / Top / x von 3). Markiert große Tagesbewegungen.

Aufruf: python -m backend.history_check MRNA [--days 120]
"""

from __future__ import annotations

import argparse

from .data_provider import YFinanceProvider
from .scanner import evaluate
from .trend import evaluate_trend


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("tickers")
    ap.add_argument("--days", type=int, default=120)
    a = ap.parse_args(argv)
    for t in [x.strip() for x in a.tickers.split(",") if x.strip()]:
        df = YFinanceProvider().history([t], "3y").get(t)
        if df is None or df.empty:
            print(f"{t}: keine Daten")
            continue
        df = df.dropna(subset=["Open", "High", "Low", "Close"])
        n = len(df)
        print(f"=== {t}: {n} Kerzen bis {df.index[-1].date()} ===")
        print("Datum       Schluss   Tag      Kairo            Trend")
        for i in range(max(260, n - a.days), n):
            sub = df.iloc[: i + 1]
            try:
                r = evaluate(sub, {"currency": "USD"}, ticker=t)
                tr = evaluate_trend(sub, r)
            except Exception as exc:
                print(f"{df.index[i].date()} Fehler {exc!r}")
                continue
            c, c0 = float(df["Close"].iloc[i]), float(df["Close"].iloc[i - 1])
            chg = c / c0 - 1
            met = sum(x.ok for x in r.criteria if x.key not in ("cap", "liquidity", "price", "history"))
            k = "TREFFER" if r.passed else "fast" if r.fast_hit else "-"
            tm = sum(x.ok for x in tr.criteria if x.key.startswith("t_"))
            tt = ("TOP" if tr.flags.get("trend_top") else "JA") if tr.passed else "-"
            miss = ",".join(x.key for x in r.missing)[:40]
            flag = "  <<< " if abs(chg) >= 0.15 else ""
            print(f"{df.index[i].date()} {c:9.2f} {chg:+7.1%}  {k:8} {met:2}/11  {tt:3} {tm}/3  fehlt:{miss}{flag}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
