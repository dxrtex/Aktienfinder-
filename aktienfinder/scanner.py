"""Lädt Tageskerzen von Yahoo Finance und prüft jede Aktie auf die Kriterien.

Aufruf:
    python -m aktienfinder.scanner AAPL MSFT SAP.DE
    python -m aktienfinder.scanner --file tickers.txt --out results.json --all
    python -m aktienfinder.scanner --universe universe.csv --out site/data/results.json
"""

import argparse
import json
import sys
import time
from collections import Counter
from datetime import datetime, timezone

import pandas as pd

from .config import DEFAULT, Config
from .indicators import macd, rsi
from .markets import region_of, usd_factor
from .mbi import momentum_bias_index
from .signals import evaluate, fib_swing, find_divergences, macd_condition

MIN_BARS = 120


MAX_STALE_DAYS = 10   # letzte Kerze älter → vermutlich delistet


def download(tickers: list[str], period: str, batch_size: int = 200, retries: int = 3,
             log=print):
    """Lädt Tageskerzen paketweise und liefert (ticker, DataFrame) nacheinander."""
    import yfinance as yf

    total = len(tickers)
    for start in range(0, total, batch_size):
        batch = tickers[start : start + batch_size]
        data = None
        for attempt in range(retries):
            try:
                data = yf.download(batch, period=period, interval="1d", group_by="ticker",
                                   auto_adjust=True, progress=False, threads=True)
                break
            except Exception as exc:  # Netzwerk/Rate-Limit: kurz warten und erneut versuchen
                log(f"  Paket {start}: Fehler {exc!r}, Versuch {attempt + 1}/{retries}")
                time.sleep(10 * (attempt + 1))
        if data is None or data.empty:
            continue
        cutoff = pd.Timestamp.now(tz=data.index.tz) - pd.Timedelta(days=MAX_STALE_DAYS)
        for t in batch:
            try:
                df = data[t] if isinstance(data.columns, pd.MultiIndex) else data
            except KeyError:
                continue
            df = df.dropna(subset=["Close"])
            if len(df) >= MIN_BARS and df.index[-1] >= cutoff:
                yield t, df
        done = min(start + batch_size, total)
        if done % 1000 < batch_size or done == total:
            log(f"  {done}/{total} Ticker geladen")


CHART_BARS = 120   # ca. 6 Monate für den Mini-Chart auf der Website


def chart_data(df: pd.DataFrame, cfg: Config = DEFAULT) -> dict:
    """Schlusskurse der letzten Monate und der Fibonacci-Schwung für den Mini-Chart."""
    closes = df["Close"].dropna().iloc[-CHART_BARS:]
    swing = fib_swing(df.dropna(subset=["Close", "Low", "High"]), cfg)
    return {
        "spark": [float(f"{v:.4g}") for v in closes],
        "fib_high": round(swing[0], 4) if swing else None,
        "fib_low": round(swing[1], 4) if swing else None,
    }


def analyst_targets(tickers: list[str], log=print) -> dict[str, dict]:
    """Durchschnittliches Analysten-Kursziel und Upside je Ticker (Yahoo Finance).

    Wird nur für die Treffer abgefragt (eine Anfrage je Aktie).
    """
    import yfinance as yf

    def fetch(t: str) -> tuple[float | None, float | None, int | None]:
        tk = yf.Ticker(t)
        for attempt in range(3):
            try:
                info = tk.info
                target = info.get("targetMeanPrice")
                price = info.get("currentPrice") or info.get("regularMarketPrice")
                if target and price:
                    return target, price, info.get("numberOfAnalystOpinions")
            except Exception:  # Yahoo blockt gelegentlich (401/429): kurz warten, erneut versuchen
                pass
            try:
                apt = tk.analyst_price_targets or {}
                if apt.get("mean") and apt.get("current"):
                    return apt["mean"], apt["current"], None
            except Exception:
                pass
            time.sleep(2 * (attempt + 1))
        return None, None, None

    out, missing = {}, 0
    for t in tickers:
        target, price, analysts = fetch(t)
        if not (target and price):
            missing += 1
            continue
        out[t] = {"target_price": round(float(target), 2),
                  "upside_pct": round(100 * (float(target) / float(price) - 1), 1),
                  "analysts": analysts}
    if missing:
        log(f"  Kursziel nicht verfügbar für {missing} von {len(tickers)} Aktien")
    return out


def debug_report(ticker: str, df: pd.DataFrame, cfg: Config = DEFAULT, bars: int = 90) -> str:
    """Alle Signaltermine der letzten `bars` Handelstage – zum Abgleich mit TradingView."""
    df = df.dropna(subset=["Close", "Low", "High"])
    close = df["Close"]
    start = df.index[-bars]
    r = rsi(close, cfg.rsi_length)
    m = macd(close, cfg.macd_fast, cfg.macd_slow, cfg.macd_signal)
    hist = m["hist"]
    mbi = momentum_bias_index(close, df["High"], df["Low"], cfg.mbi_momentum_length,
                              cfg.mbi_bias_length, cfg.mbi_smooth_length,
                              cfg.mbi_impulse_length, cfg.mbi_std_mult)
    fmt = lambda idx: ", ".join(str(d.date()) for d in idx) or "-"
    lines = [f"--- {ticker}: {len(df)} Kerzen bis {df.index[-1].date()}, Schluss {close.iloc[-1]:.2f}, "
             f"RSI {r.iloc[-1]:.1f}, MACD-Hist {hist.iloc[-1]:.4f}"]
    for d in find_divergences(df, r, cfg):
        if pd.Timestamp(d.confirmed_date) >= start:
            lines.append(f"  Divergenz {d.kind:<9}: {d.prev_pivot_date} (Tief {d.prev_price_low:.2f}, "
                         f"RSI {d.prev_rsi_low:.1f}) -> {d.pivot_date} (Tief {d.price_low:.2f}, "
                         f"RSI {d.rsi_low:.1f}), bestätigt {d.confirmed_date}")
    recent = df.index >= start
    lines.append(f"  MACD rot+schrumpfend : {fmt(df.index[macd_condition(hist, cfg, m['macd']).to_numpy() & recent])}")
    lines.append(f"  MBI grünes X         : {fmt(df.index[mbi['green_x'].to_numpy() & recent])}")
    lines.append(f"  MBI rotes X          : {fmt(df.index[mbi['red_x'].to_numpy() & recent])}")
    lines.append(f"  MBI jetzt            : grün {mbi['upper_bias'].iloc[-1]:.0f}, rot {mbi['lower_bias'].iloc[-1]:.0f}, "
                 f"Linie {mbi['impulse_boundary'].iloc[-1]:.0f}")
    return "\n".join(lines)


def scan(tickers: list[str], cfg: Config = DEFAULT, include_all: bool = False,
         debug: bool = False, meta: dict | None = None, stats: Counter | None = None,
         log=print) -> list[dict]:
    """Prüft alle Ticker. `meta` liefert Name/Region je Ticker, `stats` sammelt Zählerstände."""
    meta = meta or {}
    stats = stats if stats is not None else Counter()
    stats["universe"] += len(tickers)
    rows = []
    for ticker, df in download(tickers, cfg.history_period, log=log):
        stats["loaded"] += 1
        if debug:
            print(debug_report(ticker, df, cfg))
        try:
            res = evaluate(df, cfg)
        except Exception as exc:  # einzelne kaputte Datenreihen sollen den Scan nicht stoppen
            stats["errors"] += 1
            log(f"{ticker}: Fehler {exc!r}")
            continue
        fx = usd_factor(ticker)
        if res.close * fx < cfg.min_price or res.dollar_volume * fx < cfg.min_dollar_volume:
            stats["illiquid"] += 1
            continue
        stats["liquid"] += 1
        stats["passed"] += res.passed
        if res.passed or include_all:
            info = meta.get(ticker, {})
            rows.append({"ticker": ticker, "name": info.get("name", ""),
                         "region": info.get("region") or region_of(ticker),
                         "market_cap_usd": info.get("market_cap_usd"),
                         "date": str(df.index[-1].date()), **res.to_dict(),
                         **chart_data(df, cfg)})
    passed = [r["ticker"] for r in rows if r["passed"]]
    if passed:
        log(f"  Analysten-Kursziele für {len(passed)} Treffer abfragen …")
        targets = analyst_targets(passed, log=log)
        for r in rows:
            r.update(targets.get(r["ticker"], {"target_price": None, "upside_pct": None, "analysts": None}))
    rows.sort(key=lambda r: (r["passed"], r["score"]), reverse=True)
    return rows


def _print_table(rows: list[dict]) -> None:
    if not rows:
        print("Keine Treffer.")
        return
    print(f"{'Ticker':<10}{'Score':>6}{'Kurs':>10}{'vom Hoch':>10}{'RSI':>6}  "
          f"{'Divergenz':<22}{'MACD':<18}{'MBI':<22}{'Fib':>6} {'EMA20':<7}{'Vol':<4}{'Tief':>6}{'Ziel':>7} Trichter")
    for r in rows:
        div = ", ".join(sorted({d["kind"] for d in r["divergences"]})) or "-"
        c = r["cluster"]
        if c:
            div += f" ({c['divergence_age']} T.)"
        fib = f"{r['fib_retracement']:.2f}" if r["fib_retracement"] is not None else "-"
        fib += "*" if r["fib_zone"] else " "
        ema = f"↑{r['ema_breakout_age']} T." if r["ema_breakout_age"] is not None else "darunter"
        vol = ("S" if r["volume_spike"] else "") + ("A" if r["volume_breakout"] else "")
        upside = f"+{r['upside_pct']:.0f}%" if r.get("upside_pct") is not None else "-"
        funnel = "JA" if r["passed"] else ("nur Signale" if r["signals_ok"] else "-")
        print(f"{r['ticker']:<10}{r['score']:>6}{r['close']:>10.2f}{-r['drawdown_pct']:>9.1f}%"
              f"{r['rsi']:>6.1f}  {div:<22}{r['macd_status']:<18}{r['mbi_status']:<22}"
              f"{fib:>6} {ema:<7}{vol or '-':<4}{-r['pullback_drawdown_pct']:>5.0f}%"
              f"{upside:>7} {funnel}")
    print("Fib* = Rücksetzer in der Fibonacci-Zone; Vol: S = Spike am Tief, A = Ausbruchsvolumen")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Aktienfinder-Scan")
    p.add_argument("tickers", nargs="*", help="Ticker-Symbole (Yahoo-Format, z. B. SAP.DE)")
    p.add_argument("--file", help="Datei mit einem Ticker pro Zeile")
    p.add_argument("--universe", help="CSV aus aktienfinder.universe (ticker,name,region,source)")
    p.add_argument("--out", help="Ergebnis als JSON speichern")
    p.add_argument("--all", action="store_true", help="auch Aktien ohne alle Pflichtsignale ausgeben")
    p.add_argument("--debug", action="store_true", help="alle Signaltermine je Aktie ausgeben")
    p.add_argument("--quiet", action="store_true", help="keine Tabelle ausgeben")
    args = p.parse_args(argv)

    tickers = list(args.tickers)
    meta: dict[str, dict] = {}
    universe_log: list[str] = []
    if args.file:
        with open(args.file, encoding="utf-8") as f:
            tickers += [line.split("#")[0].strip() for line in f if line.split("#")[0].strip()]
    if args.universe:
        uni = pd.read_csv(args.universe, dtype=str).fillna("")
        meta = {r.ticker: {"name": r.name, "region": r.region,
                           "market_cap_usd": float(r.market_cap_usd) if getattr(r, "market_cap_usd", "") else None}
                for r in uni.itertuples()}
        tickers += list(uni["ticker"])
        log_path = args.universe + ".log"
        try:
            with open(log_path, encoding="utf-8") as f:
                universe_log = [line.rstrip() for line in f if line.strip()]
        except FileNotFoundError:
            pass
    tickers = list(dict.fromkeys(tickers))
    if not tickers:
        p.error("keine Ticker angegeben")

    started = time.time()
    stats: Counter = Counter()
    rows = scan(tickers, include_all=args.all, debug=args.debug, meta=meta, stats=stats)
    if not args.quiet:
        _print_table(rows)
    summary = (f"Universum {stats['universe']}, geladen {stats['loaded']}, liquide {stats['liquid']}, "
               f"Treffer {stats['passed']}, Fehler {stats['errors']}, Dauer {time.time() - started:.0f} s")
    print(summary)
    if args.out:
        import os
        os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    "stats": dict(stats),
                    "duration_s": round(time.time() - started),
                    "universe_log": universe_log,
                    "config": {k: v for k, v in vars(DEFAULT).items()},
                    "results": rows,
                },
                f,
                ensure_ascii=False,
                separators=(",", ":"),
            )
    return 0


if __name__ == "__main__":
    sys.exit(main())
