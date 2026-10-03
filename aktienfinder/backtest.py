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
from .signals import evaluate, fib_retracement, find_divergences, macd_condition

HORIZONS = (20, 40, 60)
TARGET, STOP = 0.10, -0.07
SWING_DAYS = 60            # Swing-Trading: Haltedauer wenige Wochen bis max. ~3 Monate
SWING_TARGETS = (0.10, 0.20, 0.30)
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
    # Swing-Trading: wird +10/+20/+30 % innerhalb von 60 Handelstagen erreicht (Tageshoch)?
    # Und wie tief lag die Aktie zwischendurch, bevor +10 % kamen?
    if entry + SWING_DAYS <= len(df):
        hi = high[entry : entry + SWING_DAYS] / o - 1
        lo = low[entry : entry + SWING_DAYS] / o - 1
        out["max_gain"] = float(hi.max())
        for t in SWING_TARGETS:
            hit = np.flatnonzero(hi >= t)
            out[f"hit_{int(t * 100)}"] = float(len(hit) > 0)
            out[f"days_{int(t * 100)}"] = float(hit[0] + 1) if len(hit) else np.nan
        first = np.flatnonzero(hi >= SWING_TARGETS[0])
        upto = first[0] + 1 if len(first) else SWING_DAYS
        out["dip_before"] = float(lo[:upto].min())
    return out


TRADE_TARGET = 0.20        # Swing-Trade: Verkauf bei +20 % …
TRADE_DAYS = 60            # … spätestens nach 60 Handelstagen; Stop = Stop-Kurs des Setups


def _trade(df: pd.DataFrame, entry: int, stop: float | None) -> dict:
    """Simuliert einen echten Trade: Kauf zur Eröffnung am Tag `entry`, Stop-Loss beim Stop-Kurs
    (bei Kurslücke darunter: Verkauf zur Eröffnung), Gewinnmitnahme bei +20 %, sonst Verkauf zum
    Schlusskurs nach 60 Tagen. Trifft ein Tag Stop und Ziel, zählt (vorsichtig) der Stop."""
    if stop is None or not np.isfinite(stop) or entry + TRADE_DAYS > len(df):
        return {}
    o = df["Open"].to_numpy(dtype=float)
    hi = df["High"].to_numpy(dtype=float)
    lo = df["Low"].to_numpy(dtype=float)
    cl = df["Close"].to_numpy(dtype=float)
    buy = o[entry]
    if not np.isfinite(buy) or buy <= stop:
        return {}                                   # Eröffnung schon unter dem Stop: kein Einstieg
    target = buy * (1 + TRADE_TARGET)
    for j in range(entry, entry + TRADE_DAYS):
        if lo[j] <= stop:
            exit_ = min(o[j], stop) if j > entry else stop
            return {"trade_ret": exit_ / buy - 1, "trade_outcome": -1, "trade_days": j - entry + 1,
                    "trade_risk": 1 - stop / buy}
        if hi[j] >= target:
            exit_ = max(o[j], target) if j > entry else target
            return {"trade_ret": exit_ / buy - 1, "trade_outcome": 1, "trade_days": j - entry + 1,
                    "trade_risk": 1 - stop / buy}
    end = entry + TRADE_DAYS - 1
    return {"trade_ret": cl[end] / buy - 1, "trade_outcome": 0, "trade_days": TRADE_DAYS,
            "trade_risk": 1 - stop / buy}


def _context(df: pd.DataFrame, index_close: pd.Series | None) -> pd.DataFrame:
    """Zusatzmerkmale je Tag für die Stufe-B-Filter (nur Daten bis zum jeweiligen Tag)."""
    close = df["Close"].astype(float)
    e200 = ema(close, 200)
    ctx = pd.DataFrame(index=df.index)
    ctx["trend200"] = (close > e200) & (e200 > e200.shift(20))          # langfristiger Aufwärtstrend
    ctx["ema200_rising"] = e200 > e200.shift(20)
    vol = df["Volume"].astype(float) if "Volume" in df else pd.Series(np.nan, index=df.index)
    ctx["vol_dry"] = vol.rolling(10).mean() / vol.rolling(50).mean()    # < 1: Volumen nimmt ab
    ret63 = close / close.shift(63) - 1
    if index_close is not None and len(index_close):
        ic = index_close.reindex(df.index, method="ffill")
        ctx["market_ok"] = ic > ema(ic.dropna(), 200).reindex(df.index, method="ffill")
        ctx["rel_strength"] = ret63 - (ic / ic.shift(63) - 1)
    else:
        ctx["market_ok"] = np.nan
        ctx["rel_strength"] = np.nan
    return ctx


def _ctx_fields(ctx: pd.DataFrame, day: int) -> dict:
    row = ctx.iloc[day]
    return {k: (None if pd.isna(v) else (bool(v) if k in ("trend200", "ema200_rising", "market_ok") else float(v)))
            for k, v in row.items()}


def stock_events(ticker: str, df: pd.DataFrame, cfg: Config = DEFAULT,
                 index_close: pd.Series | None = None) -> list[dict]:
    """Alle Tage, an denen der vollständige Trichter (Signale + Fibonacci + Rückgang) anschlägt."""
    df = df.dropna(subset=["Open", "High", "Low", "Close"])
    if len(df) < MIN_HISTORY + 50:
        return []
    close = df["Close"]
    r = rsi(close, cfg.rsi_length)
    n = len(df)
    div_idx = [n - 1 - d.age for d in find_divergences(df, r, cfg)]
    m = macd(close, cfg.macd_fast, cfg.macd_slow, cfg.macd_signal)
    macd_idx = np.flatnonzero(macd_condition(m["hist"], cfg, m["macd"]).to_numpy())
    mbi = momentum_bias_index(close, df["High"], df["Low"], cfg.mbi_momentum_length, cfg.mbi_bias_length,
                              cfg.mbi_smooth_length, cfg.mbi_impulse_length, cfg.mbi_std_mult)
    mbi_idx = np.flatnonzero(mbi["green_x"].to_numpy())
    e20 = ema(close, cfg.ema_trigger_length).to_numpy()
    c = close.to_numpy(dtype=float)
    hist = m["hist"].to_numpy()
    ctx = _context(df, index_close)

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
            "fib_zone": res.fib_zone, "fib": res.fib_retracement, "ema_breakout_age": res.ema_breakout_age,
            "volume_spike": res.volume_spike, "volume_breakout": res.volume_breakout,
            "reversal": res.reversal_candle_age is not None, "green_x_count": res.green_x_count,
            "rsi_signal_gap": res.rsi_signal_gap, "status": res.status,
            "rise_from_low_pct": res.rise_from_low_pct, "crv": res.crv,
            "pullback_drawdown_pct": res.pullback_drawdown_pct, "macd_closeness": res.macd_closeness,
            "divergence_forming": res.divergence_forming,
            "core_count": len(res.core_met), **_ctx_fields(ctx, day),
        }
        ev.update({f"sig_{k}": v for k, v in _forward(df, day + 1).items()})
        ev.update(_trade(df, day + 1, res.stop_price))
        # Variante: Einstieg erst beim Schlusskurs über der EMA 20 (innerhalb von 30 Tagen)
        # (liegt der Kurs am Signaltag schon darüber, ist das der Einstieg)
        brk = next((t for t in range(day, min(n - 1, day + cfg.max_signal_age))
                    if c[t] > e20[t] and (t == day or c[t - 1] <= e20[t - 1])), None)
        if brk is not None:
            ev["brk_delay"] = brk - day
            ev.update({f"brk_{k}": v for k, v in _forward(df, brk + 1).items()})
        # Variante „bestätigter Einstieg“: erst wenn das MACD-Histogramm grün wird (max. 20 Tage)
        green = next((t for t in range(day, min(n - 1, day + 20)) if hist[t] > 0), None)
        if green is not None:
            ev["conf_delay"] = green - day
            ev.update({f"conf_{k}": v for k, v in _forward(df, green + 1).items()})
        events.append(ev)
    return events


def baseline_returns(df: pd.DataFrame, step: int = 5, cfg: Config = DEFAULT,
                     index_close: pd.Series | None = None) -> list[dict]:
    """Zufallseinstieg: jeder `step`-te Tag ab MIN_HISTORY.

    Zu jedem Tag wird vermerkt, ob die Fibonacci- und Rückgangs-Bedingungen erfüllt waren –
    so lässt sich prüfen, ob die drei Indikatoren *zusätzlich* etwas bringen.
    """
    df = df.dropna(subset=["Open", "High", "Low", "Close"])
    high52 = df["High"].rolling(cfg.drawdown_lookback, min_periods=1).max()
    recent_low = df["Low"].rolling(cfg.max_signal_age, min_periods=1).min()
    ctx = _context(df, index_close)
    rows = []
    for day in range(MIN_HISTORY, len(df) - 1, step):
        fwd = _forward(df, day + 1)
        if not fwd:
            continue
        fwd["drawdown_pct"] = 100 * (1 - df["Close"].iloc[day] / high52.iloc[day])
        fwd["pullback_drawdown"] = 1 - recent_low.iloc[day] / high52.iloc[day]
        fib = fib_retracement(df.iloc[: day + 1], cfg)
        lo_r, hi_r = cfg.fib_required
        fwd["fib_zone"] = fib is not None and lo_r - cfg.fib_tolerance <= fib <= hi_r + cfg.fib_tolerance
        if fwd["fib_zone"] and fwd["pullback_drawdown"] >= cfg.min_drawdown:
            res = evaluate(df.iloc[: day + 1], cfg)     # wie viele Kernkriterien waren an diesem Tag erfüllt?
            fwd["core_count"] = len(res.core_met)
            fwd["core_met"] = "+".join(res.core_met)
            fwd["score"] = res.score
            fwd["crv"] = res.crv
            fwd["rise_from_low_pct"] = res.rise_from_low_pct
            fwd["green_x_count"] = res.green_x_count
            fwd.update(_ctx_fields(ctx, day))
            fwd.update(_trade(df, day + 1, res.stop_price))
        rows.append(fwd)
    return rows


def _stats(frame: pd.DataFrame, prefix: str) -> str:
    """Kennzahlen für Swing-Trading (Ziel +10–30 %, Haltedauer bis 60 Handelstage)."""
    if frame.empty or f"{prefix}hit_10" not in frame:
        return "n=0"
    f = frame.dropna(subset=[f"{prefix}hit_10"])
    if f.empty:
        return "n=0"
    parts = [f"n={len(f)}"]
    hits = " / ".join(f"+{t}: {100 * f[f'{prefix}hit_{t}'].mean():.0f} %" for t in (10, 20, 30))
    parts.append(f"erreicht in 60 T. {hits}")
    d20 = f[f"{prefix}days_20"].dropna()
    if len(d20):
        parts.append(f"Tage bis +20 % (Median) {d20.median():.0f}")
    parts.append(f"Höchstgewinn Median {100 * f[f'{prefix}max_gain'].median():+.0f} %")
    parts.append(f"Rücksetzer vor +10 % Median {100 * f[f'{prefix}dip_before'].median():.0f} %")
    r60 = f[f"{prefix}ret_60"].dropna()
    if len(r60):
        parts.append(f"Kurs nach 60 T. Median {100 * r60.median():+.1f} %")
    tcol = "b_trade_ret" if prefix == "b_" else "trade_ret"
    if prefix in ("", "sig_", "b_") and tcol in frame:
        t = frame.dropna(subset=[tcol])
        if len(t):
            oc = t[tcol.replace("ret", "outcome")]
            parts.append(f"TRADE (Stop/+20 %/60 T.): Ø {100 * t[tcol].mean():+.1f} % je Trade, "
                         f"Ziel {100 * (oc == 1).mean():.0f} % / Stop {100 * (oc == -1).mean():.0f} %")
    return " | ".join(parts)


def _filters(frame: pd.DataFrame, p: str) -> list[tuple[str, pd.Series]]:
    """Kandidaten für zusätzliche Filter – jeweils als Maske über `frame` (Spalten mit Präfix p)."""
    def col(name, default=np.nan):
        return frame[p + name] if p + name in frame else pd.Series(default, index=frame.index)
    market = col("market_ok").astype("boolean").fillna(False).astype(bool)
    trend = col("trend200").astype("boolean").fillna(False).astype(bool)
    rising = col("ema200_rising").astype("boolean").fillna(False).astype(bool)
    rs = col("rel_strength").astype(float)
    dry = col("vol_dry").astype(float)
    crv = col("crv").astype(float)
    return [
        ("Markt über EMA 200", market),
        ("Markt unter EMA 200", ~market),
        ("Aktie im Aufwärtstrend (über steigender EMA 200)", trend),
        ("EMA 200 der Aktie steigt", rising),
        ("relative Stärke 3 Mon. > 0", rs > 0),
        ("relative Stärke 3 Mon. < −20 %", rs < -0.20),
        ("Volumen nimmt ab (10 T. < 80 % von 50 T.)", dry < 0.8),
        ("Chance/Risiko ≥ 2", crv >= 2),
        ("Chance/Risiko ≥ 3", crv >= 3),
        ("Markt über EMA 200 + Chance/Risiko ≥ 2", market & (crv >= 2)),
        ("Markt über EMA 200 + EMA 200 der Aktie steigt", market & rising),
    ]


def summarize(events: pd.DataFrame, base: pd.DataFrame) -> str:
    out = ["== Backtest =="]
    base_p = base.add_prefix("b_")
    out.append("Zufallseinstieg (alle Aktien, alle Tage):        " + _stats(base_p, "b_"))
    dips = base_p[base_p["b_drawdown_pct"] >= 20]
    out.append("Zufallseinstieg nach ≥20 % Rückgang vom Hoch:    " + _stats(dips, "b_"))
    setup = base_p[(base_p["b_pullback_drawdown"] >= DEFAULT.min_drawdown) & base_p["b_fib_zone"]]
    out.append("Zufallseinstieg mit Fib-Zone + ≥20 % Rückgang:  " + _stats(setup, "b_")
               + "   ← Vergleichsmaßstab: gleiches Setup ohne RSI/MACD/MBI")
    if "b_core_count" in base_p:
        out.append("\nGesamtpaket (alle Tage mit Fib + ≥20 % Rückgang, jeden 5. Tag):")
        cand = base_p.dropna(subset=["b_core_count"])
        for k in (2, 3, 4, 5):
            out.append(f"  {k} von 5 Kernkriterien:{'':<22}" + _stats(cand[cand["b_core_count"] == k], "b_"))
        names = ("divergenz", "macd_jetzt", "mbi_x")
        four = cand[cand["b_core_count"] == 4]
        for n in names:
            miss = four[~four["b_core_met"].str.contains(n)]
            out.append(f"  4 von 5, es fehlt nur {n:<20}" + _stats(miss, "b_"))
        for lo, hi in ((0, 40), (40, 60), (60, 70), (70, 80), (80, 101)):
            out.append(f"  Score {lo}–{hi}:{'':<32}"
                       + _stats(cand[(cand["b_score"] >= lo) & (cand["b_score"] < hi)], "b_"))
    if "b_core_count" in base_p:
        cand = base_p.dropna(subset=["b_core_count"])
        full = cand[cand["b_core_count"] >= 4]
        out.append("\nStufe-B-Filter (Tage mit Fib + ≥20 % Rückgang und mind. 4 von 5 Kernkriterien):")
        out.append(f"  {'ohne Zusatzfilter':<44}" + _stats(full, "b_"))
        for label, mask in _filters(full, "b_"):
            out.append(f"  {label:<44}" + _stats(full[mask], "b_"))
    if events.empty:
        out.append("keine Signale")
        return "\n".join(out)
    out.append("Signal, Einstieg am Folgetag:                   " + _stats(events, "sig_"))
    brk = events.dropna(subset=["brk_entry_price"]) if "brk_entry_price" in events else events.iloc[0:0]
    out.append("Signal, Einstieg beim Ausbruch über EMA 20:      " + _stats(brk, "brk_"))

    def variant(label, mask):
        out.append(f"  {label:<44}" + _stats(events[mask], "sig_"))

    out.append("\nSetup-Status (Einstieg am Folgetag):")
    for st, label in (("bereit", "Einstiegsbereit"), ("abwarten", "Abwarten"), ("gelaufen", "Schon gelaufen")):
        variant(label, events["status"] == st)
    for lo, hi in ((0, 5), (5, 10), (10, 20), (20, 999)):
        variant(f"Kurs {lo}–{hi} % über dem Tief", events["rise_from_low_pct"].between(lo, hi, inclusive="left"))

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
    variant("Fib: in der Golden Zone (0,618–0,79)", events["fib_zone"])
    variant("Fib: darunter gefallen (0,79–1,0)", ~events["fib_zone"] & (events["fib"] > 0.79))
    variant("Volumen-Spike am Tief", events["volume_spike"])
    variant("Umkehrkerze mit Volumen an Fib-Linie", events["reversal"])
    variant("zwei oder mehr grüne MBI-X", events["green_x_count"] >= 2)
    variant("RSI an der Signallinie (−2 … +5)", events["rsi_signal_gap"].between(-2, 5))
    variant("Uber-Muster: MACD rot + 2× X + RSI an Signallinie",
            events["macd_red_now"] & (events["green_x_count"] >= 2) & events["rsi_signal_gap"].between(-2, 5))
    variant("Uber-Muster + Umkehrkerze",
            events["macd_red_now"] & (events["green_x_count"] >= 2) & events["rsi_signal_gap"].between(-2, 5)
            & events["reversal"])
    variant("RSI ≤ 35 und Abstand ≥ 20 %", (events["div_rsi_min"] <= 35) & (events["drawdown_pct"] >= 20))

    out.append("\nStufe-B-Filter auf die Scanner-Signale (Einstieg am Folgetag):")
    for label, mask in _filters(events, ""):
        variant(label, mask)
    if "conf_entry_price" in events:
        conf = events.dropna(subset=["conf_entry_price"])
        out.append("Bestätigter Einstieg (erst wenn MACD grün wird, max. 20 T.): " + _stats(conf, "conf_"))
        out.append("  dieselben Signale, aber sofort eingestiegen:              " + _stats(conf, "sig_"))

    # Robustheit: gleiche Auswertung für erste und zweite Hälfte des Zeitraums
    mid = events["date"].sort_values().iloc[len(events) // 2]
    out.append("\nZeitraum-Hälften (Einstieg am Folgetag):")
    out.append(f"  bis {mid}: " + _stats(events[events["date"] < mid], "sig_"))
    out.append(f"  ab {mid}:  " + _stats(events[events["date"] >= mid], "sig_"))
    return "\n".join(out)


INDEX_OF_REGION = {"us": "^GSPC", "europe": "^STOXX50E", "global": "ACWI"}


def _process(item):
    ticker, df, index_close = item
    try:
        return (stock_events(ticker, df, index_close=index_close),
                baseline_returns(df, index_close=index_close))
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
    indices = {t: d["Close"] for t, d in download(sorted(set(INDEX_OF_REGION.values())), args.period)}
    print("Indizes geladen: " + ", ".join(sorted(indices)))
    region = dict(zip(uni["ticker"], uni["region"])) if "region" in uni else {}
    with ProcessPoolExecutor() as pool:
        futures = [pool.submit(_process, (t, d, indices.get(INDEX_OF_REGION.get(region.get(t, "us"), "^GSPC"))))
                   for t, d in download(tickers, args.period)]
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
