"""Backtest: Wie haben sich Aktien entwickelt, nachdem der Scanner in der Vergangenheit angeschlagen hat?

Vorgehen je Aktie (alles ohne Blick in die Zukunft):
1. Alle Signaltermine berechnen: RSI-Divergenz (Bestätigungstag), MACD-Bedingung, grünes MBI-X.
2. Jeden Tag finden, an dem ein Signal-Bündel *vollständig* wird (das dritte Signal kommt dazu).
   Das ist der Tag, an dem der Scanner die Aktie erstmals anzeigen würde.
3. An diesem Tag `evaluate()` auf den bis dahin bekannten Daten aufrufen → Score und Merkmale
   genau wie im Live-Scan.
4. Einstieg zum Eröffnungskurs des Folgetags; Rendite nach 10/20/40 Handelstagen, sowie
   ob zuerst +10 % (Ziel) oder −7 % (Stopp) erreicht wurde.
5. Variante „Einstieg beim Ausbruch über die EMA 20“ (wie bei Infineon/TUI).
6. Vergleich mit einem Zufallseinstieg in dieselben Aktien im selben Zeitraum.

Aufruf:
    python -m aktienfinder.backtest --universe universe.csv --period 5y --out events.csv
"""

import argparse
import sys
import time

import numpy as np
import pandas as pd

from .config import DEFAULT, Config
from .indicators import ema, macd, rsi
from .mbi import momentum_bias_index
from .signals import evaluate, find_divergences, macd_condition

HORIZONS = (10, 20, 40)
TARGET, STOP = 0.10, -0.07
MIN_HISTORY = 260          # so viele Kerzen vor dem ersten möglichen Signal (für 52-Wochen-Hoch)
DEDUPE_BARS = 10           # neues Bündel derselben Aktie erst nach so vielen Tagen erneut zählen


def cluster_completions(div_idx, macd_idx, mbi_idx, cfg: Config = DEFAULT) -> list[int]:
    """Tage (Indizes), an denen ein Signal-Bündel vollständig wird.

    Ein Bündel ist (d, m, x) mit Spanne ≤ cluster_span und wird am Tag max(d, m, x)
    vollständig. Für jedes Paar (d, x) zählt der früheste mögliche Abschluss.
    """
    macd_sorted = np.sort(np.asarray(macd_idx, dtype=int))
    done = set()
    for d in div_idx:
        for x in mbi_idx:
            if abs(d - x) > cfg.cluster_span:
                continue
            lo, hi = max(d, x) - cfg.cluster_span, min(d, x) + cfg.cluster_span
            ms = macd_sorted[(macd_sorted >= lo) & (macd_sorted <= hi)]
            if len(ms):
                done.add(int(max(d, x, ms.min())))
    return sorted(done)


def _dedupe(days: list[int], gap: int) -> list[int]:
    out = []
    for d in days:
        if not out or d - out[-1] > gap:
            out.append(d)
    return out


def _forward(df: pd.DataFrame, entry: int) -> dict:
    """Renditen ab Eröffnung am Tag `entry`."""
    o = float(df["Open"].iloc[entry])
    if not np.isfinite(o) or o <= 0:
        return {}
    close = df["Close"].to_numpy(dtype=float)
    high = df["High"].to_numpy(dtype=float)
    low = df["Low"].to_numpy(dtype=float)
    out = {"entry_price": o}
    for h in HORIZONS:
        j = entry + h - 1
        out[f"ret_{h}"] = close[j] / o - 1 if j < len(df) else np.nan
    # Ziel oder Stopp zuerst? (innerhalb von 40 Tagen; bei beidem am selben Tag zählt der Stopp)
    outcome = np.nan
    end = min(len(df), entry + max(HORIZONS))
    if entry + max(HORIZONS) <= len(df):
        outcome = 0.0
        for j in range(entry, end):
            if low[j] / o - 1 <= STOP:
                outcome = -1.0
                break
            if high[j] / o - 1 >= TARGET:
                outcome = 1.0
                break
    out["target_first"] = outcome
    return out


def stock_events(ticker: str, df: pd.DataFrame, cfg: Config = DEFAULT) -> list[dict]:
    df = df.dropna(subset=["Open", "High", "Low", "Close"])
    if len(df) < MIN_HISTORY + 50:
        return []
    close = df["Close"]
    r = rsi(close, cfg.rsi_length)
    n = len(df)
    div_idx = [n - 1 - d.age for d in find_divergences(df, r, cfg)]
    hist = macd(close, cfg.macd_fast, cfg.macd_slow, cfg.macd_signal)["hist"]
    macd_idx = np.flatnonzero(macd_condition(hist, cfg).to_numpy())
    mbi = momentum_bias_index(close, df["High"], df["Low"], cfg.mbi_momentum_length, cfg.mbi_bias_length,
                              cfg.mbi_smooth_length, cfg.mbi_impulse_length, cfg.mbi_std_mult)
    mbi_idx = np.flatnonzero(mbi["green_x"].to_numpy())
    e20 = ema(close, cfg.ema_trigger_length).to_numpy()
    c = close.to_numpy(dtype=float)

    days = [d for d in cluster_completions(div_idx, macd_idx, mbi_idx, cfg) if d >= MIN_HISTORY and d + 1 < n]
    events = []
    for day in _dedupe(days, DEDUPE_BARS):
        res = evaluate(df.iloc[: day + 1], cfg)
        if not res.passed:
            continue
        ev = {
            "ticker": ticker, "date": str(df.index[day].date()), "score": res.score,
            "drawdown_pct": res.drawdown_pct, "rsi": res.rsi,
            "div_kinds": "+".join(sorted({d.kind for d in res.divergences})),
            "div_rsi_min": min(min(d.rsi_low, d.prev_rsi_low) for d in res.divergences
                               if d.age == res.cluster.divergence_age),
            "span": res.cluster.span, "macd_red_now": res.macd_status.startswith("rot"),
            "fib_zone": res.fib_zone, "ema_breakout_age": res.ema_breakout_age,
            "volume_spike": res.volume_spike, "volume_breakout": res.volume_breakout,
        }
        ev.update({f"sig_{k}": v for k, v in _forward(df, day + 1).items()})
        # Variante: Einstieg erst beim Schlusskurs über der EMA 20 (innerhalb von 30 Tagen)
        # (liegt der Kurs am Signaltag schon darüber, ist das der Einstieg)
        brk = next((t for t in range(day, min(n - 1, day + cfg.max_signal_age))
                    if c[t] > e20[t] and (t == day or c[t - 1] <= e20[t - 1])), None)
        if brk is not None:
            ev["brk_delay"] = brk - day
            ev.update({f"brk_{k}": v for k, v in _forward(df, brk + 1).items()})
        events.append(ev)
    return events


def baseline_returns(df: pd.DataFrame, step: int = 5) -> list[dict]:
    """Zufallseinstieg: jeder `step`-te Tag ab MIN_HISTORY."""
    df = df.dropna(subset=["Open", "High", "Low", "Close"])
    high52 = df["High"].rolling(252, min_periods=1).max()
    rows = []
    for day in range(MIN_HISTORY, len(df) - 1, step):
        fwd = _forward(df, day + 1)
        if fwd:
            fwd["drawdown_pct"] = 100 * (1 - df["Close"].iloc[day] / high52.iloc[day])
            rows.append(fwd)
    return rows


def _stats(frame: pd.DataFrame, prefix: str) -> str:
    if frame.empty:
        return "n=0"
    parts = [f"n={len(frame)}"]
    for h in HORIZONS:
        col = frame[f"{prefix}ret_{h}"].dropna()
        if len(col):
            parts.append(f"{h}T: Ø {100 * col.mean():+.1f} % / Median {100 * col.median():+.1f} % / "
                         f"positiv {100 * (col > 0).mean():.0f} %")
    tf = frame[f"{prefix}target_first"].dropna()
    if len(tf):
        parts.append(f"+10 % vor −7 %: {100 * (tf == 1).mean():.0f} % (−7 % zuerst {100 * (tf == -1).mean():.0f} %)")
    return " | ".join(parts)


def summarize(events: pd.DataFrame, base: pd.DataFrame) -> str:
    out = ["== Backtest =="]
    base_p = base.add_prefix("b_")
    out.append("Zufallseinstieg (alle Aktien, alle Tage):        " + _stats(base_p, "b_"))
    dips = base_p[base_p["b_drawdown_pct"] >= 20]
    out.append("Zufallseinstieg nach ≥20 % Rückgang vom Hoch:    " + _stats(dips, "b_"))
    if events.empty:
        out.append("keine Signale")
        return "\n".join(out)
    out.append("Signal, Einstieg am Folgetag:                   " + _stats(events, "sig_"))
    brk = events.dropna(subset=["brk_entry_price"]) if "brk_entry_price" in events else events.iloc[0:0]
    out.append("Signal, Einstieg beim Ausbruch über EMA 20:      " + _stats(brk, "brk_"))

    def variant(label, mask):
        out.append(f"  {label:<44}" + _stats(events[mask], "sig_"))

    out.append("\nVarianten (Einstieg am Folgetag):")
    for lo, hi in ((0, 40), (40, 50), (50, 60), (60, 70), (70, 80), (80, 101)):
        variant(f"Score {lo}–{hi}", (events["score"] >= lo) & (events["score"] < hi))
    for lim in (30, 35, 40):
        variant(f"RSI-Tief der Divergenz ≤ {lim}", events["div_rsi_min"] <= lim)
    for lim in (10, 20, 30):
        variant(f"Abstand zum Hoch ≥ {lim} %", events["drawdown_pct"] >= lim)
    for kind in ("klassisch", "versteckt", "klassisch+versteckt"):
        variant(f"Divergenz: {kind}", events["div_kinds"] == kind)
    for lim in (5, 10):
        variant(f"Bündel-Spanne ≤ {lim} Tage", events["span"] <= lim)
    variant("MACD noch rot", events["macd_red_now"])
    variant("in Fibonacci-Zone", events["fib_zone"])
    variant("Volumen-Spike am Tief", events["volume_spike"])
    variant("RSI ≤ 35 und Abstand ≥ 20 %", (events["div_rsi_min"] <= 35) & (events["drawdown_pct"] >= 20))

    # Robustheit: gleiche Auswertung für erste und zweite Hälfte des Zeitraums
    mid = events["date"].sort_values().iloc[len(events) // 2]
    out.append("\nZeitraum-Hälften (Einstieg am Folgetag):")
    out.append(f"  bis {mid}: " + _stats(events[events["date"] < mid], "sig_"))
    out.append(f"  ab {mid}:  " + _stats(events[events["date"] >= mid], "sig_"))
    return "\n".join(out)


def _process(item):
    ticker, df = item
    try:
        return stock_events(ticker, df), baseline_returns(df)
    except Exception as exc:  # einzelne kaputte Datenreihen überspringen
        print(f"{ticker}: Fehler {exc!r}", file=sys.stderr)
        return [], []


def main(argv: list[str] | None = None) -> int:
    from concurrent.futures import ProcessPoolExecutor

    from .scanner import download

    p = argparse.ArgumentParser(description="Backtest der Scanner-Signale")
    p.add_argument("--universe", required=True)
    p.add_argument("--period", default="5y")
    p.add_argument("--out", help="alle Signale als CSV")
    p.add_argument("--limit", type=int, default=0, help="nur die ersten N Aktien (zum Testen)")
    args = p.parse_args(argv)

    uni = pd.read_csv(args.universe, dtype={"ticker": str})
    tickers = list(uni["ticker"])[: args.limit or None]
    started = time.time()
    events, base = [], []
    with ProcessPoolExecutor() as pool:
        futures = [pool.submit(_process, item) for item in download(tickers, args.period)]
        for f in futures:
            e, b = f.result()
            events += e
            base += b
    ev = pd.DataFrame(events)
    print(f"{len(tickers)} Aktien, {len(ev)} Signale, Dauer {time.time() - started:.0f} s")
    print(summarize(ev, pd.DataFrame(base)))
    if args.out:
        ev.to_csv(args.out, index=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
