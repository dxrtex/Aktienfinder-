"""Lädt Tageskerzen von Yahoo Finance und prüft jede Aktie auf die Kriterien.

Aufruf:
    python -m aktienfinder.scanner AAPL MSFT SAP.DE
    python -m aktienfinder.scanner --file tickers.txt --out results.json --all
"""

import argparse
import json
import sys
from datetime import datetime, timezone

import pandas as pd

from .config import DEFAULT, Config
from .signals import evaluate

MIN_BARS = 120


def download(tickers: list[str], period: str, batch_size: int = 100) -> dict[str, pd.DataFrame]:
    import yfinance as yf

    out: dict[str, pd.DataFrame] = {}
    for start in range(0, len(tickers), batch_size):
        batch = tickers[start : start + batch_size]
        data = yf.download(
            batch,
            period=period,
            interval="1d",
            group_by="ticker",
            auto_adjust=True,
            progress=False,
            threads=True,
        )
        for t in batch:
            try:
                df = data[t] if isinstance(data.columns, pd.MultiIndex) else data
            except KeyError:
                continue
            df = df.dropna(subset=["Close"])
            if len(df) >= MIN_BARS:
                out[t] = df
    return out


def scan(tickers: list[str], cfg: Config = DEFAULT, include_all: bool = False) -> list[dict]:
    rows = []
    for ticker, df in download(tickers, cfg.history_period).items():
        try:
            res = evaluate(df, cfg)
        except Exception as exc:  # einzelne kaputte Datenreihen sollen den Scan nicht stoppen
            print(f"{ticker}: Fehler {exc}", file=sys.stderr)
            continue
        if res.close < cfg.min_price or res.dollar_volume < cfg.min_dollar_volume:
            continue
        if res.passed or include_all:
            rows.append({"ticker": ticker, "date": str(df.index[-1].date()), **res.to_dict()})
    rows.sort(key=lambda r: (r["passed"], r["score"]), reverse=True)
    return rows


def _print_table(rows: list[dict]) -> None:
    if not rows:
        print("Keine Treffer.")
        return
    print(f"{'Ticker':<10}{'Score':>6}{'Kurs':>10}{'vom Hoch':>10}{'RSI':>7}  "
          f"{'Divergenz':<20}{'MACD':<16}{'MBI-X':<8}{'Vol':<5}")
    for r in rows:
        div = ", ".join(f"{d['kind']} ({d['age']} T.)" for d in r["divergences"]) or "-"
        mbi = f"vor {r['mbi_age']} T." if r["mbi_age"] is not None else "-"
        vol = ("S" if r["volume_spike"] else "") + ("E" if r["volume_recovery"] else "")
        print(f"{r['ticker']:<10}{r['score']:>6}{r['close']:>10.2f}{-r['drawdown_pct']:>9.1f}%"
              f"{r['rsi']:>7.1f}  {div:<20}{r['macd_status']:<16}{mbi:<8}{vol or '-':<5}")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Aktienfinder-Scan")
    p.add_argument("tickers", nargs="*", help="Ticker-Symbole (Yahoo-Format, z. B. SAP.DE)")
    p.add_argument("--file", help="Datei mit einem Ticker pro Zeile")
    p.add_argument("--out", help="Ergebnis als JSON speichern")
    p.add_argument("--all", action="store_true", help="auch Aktien ohne alle Pflichtsignale ausgeben")
    args = p.parse_args(argv)

    tickers = list(args.tickers)
    if args.file:
        with open(args.file, encoding="utf-8") as f:
            tickers += [line.strip() for line in f if line.strip() and not line.startswith("#")]
    if not tickers:
        p.error("keine Ticker angegeben")

    rows = scan(tickers, include_all=args.all)
    _print_table(rows)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(
                {"generated": datetime.now(timezone.utc).isoformat(timespec="seconds"), "results": rows},
                f,
                ensure_ascii=False,
                indent=1,
            )
    return 0


if __name__ == "__main__":
    sys.exit(main())
