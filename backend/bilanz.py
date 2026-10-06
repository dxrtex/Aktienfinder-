"""Kairo-Bilanz: Wie gut waren die Signale wirklich?

Für jedes Signal (erster Tag einer Treffer- bzw. Fast-Treffer-Phase) wird der Trade-Plan nachverfolgt:
- Was kam zuerst: Ziel 1 (Hoch ≥ Ziel 1) oder Stop (Tief ≤ Stop)? Beides am selben Tag zählt als Stop (vorsichtig).
- Rendite zum Schlusskurs nach 5, 10, 20 Handelstagen, bester/schlechtester Stand in 20 Tagen (MFE/MAE).
- Ergebnis in R (Vielfachen des Risikos Entry−Stop): Ziel 1 zuerst = +R(Ziel 1), Stop zuerst = −1 R, sonst Stand nach 30 Tagen.

Zwei Quellen:
- Backtest (`python -m backend.bilanz --shard k --shards 8`, Workflow „Kairo-Bilanz“): zufällige Aktien, 2 Jahre.
- Live-Bilanz (run_scan): jedes Signal wird am Tag des Scans gespeichert (Branch kairo-data) und täglich nachgeführt.
"""

from __future__ import annotations

import argparse
import json
import random
import time
from pathlib import Path

import numpy as np
import pandas as pd

from .config import CONFIG, ROOT

HOLD = 63           # max. Haltedauer: 3 Monate (Swing-Trading)
GAP = 5             # neue Signal-Phase erst nach ≥ 5 Tagen ohne Signal
RET_DAYS = (5, 10, 20, 40, 63)


def _race(h, l, i: int, n: int, stop: float, target: float | None):
    """Was kommt zuerst innerhalb von HOLD Tagen: Ziel (Hoch ≥ Ziel) oder Stop (Tief ≤ Stop)? Gleicher Tag = Stop."""
    for j in range(i + 1, min(n, i + 1 + HOLD)):
        if l[j] <= stop:
            return "stop", j - i, stop
        if target and h[j] >= target:
            return "t", j - i, target
    return None, None, None


def outcome(o, h, l, c, i: int, entry: float, stop: float, t1: float | None, t2: float | None,
            tp1: float | None = None) -> dict | None:
    """Verlauf ab dem Tag nach dem Signal (Index i). Ausstiegs-Pläne mit gleichem Stop, jeweils max. 3 Monate –
    verkauft wird an dem Tag, an dem Ziel bzw. Stop erreicht wird; nur ohne beides zählt der Kurs nach 3 Monaten:
    A) Ziel 1 (EMA 50 / Fib 0,382)   B) Ziel 2 (Swing-High)   C) TP 1 der Hoch-Treppe (nächstes relevantes Hoch, wie im Depot)
    D) Hälfte an Ziel 1, Stop auf Einstand, Rest bis Swing-High."""
    n = len(c)
    if i + 1 >= n or not stop or entry <= stop:
        return None
    risk = entry - stop
    complete = i + HOLD < n
    last = min(n - 1, i + HOLD)

    def plan(target):
        res, day, px = _race(h, l, i, n, stop, target)
        if res is None:
            res, px = ("open" if complete else "running"), c[last]
        return ("t1" if res == "t" else res), day, round(float((px - entry) / risk), 3)

    res, day, r = plan(t1)
    res2, day2, r2 = plan(t2) if t2 else (None, None, None)
    if res2 == "t1":
        res2 = "t2"
    res3, day3, r3 = plan(tp1) if tp1 and tp1 > entry else (None, None, None)
    # D: halb/halb
    rd, resd = None, None
    if t1 and t2 and t2 > t1:
        if res == "stop":
            rd, resd = -1.0, "stop"
        elif res == "t1":
            j0 = i + day
            r_half = (t1 - entry) / risk
            rest, rest_res = None, None
            for j in range(j0 + 1, min(n, i + 1 + HOLD)):
                if l[j] <= entry:
                    rest, rest_res = 0.0, "be"
                    break
                if h[j] >= t2:
                    rest, rest_res = (t2 - entry) / risk, "t2"
                    break
            if rest is None:
                rest, rest_res = (c[last] - entry) / risk, ("open" if complete else "running")
            rd, resd = round(float(0.5 * r_half + 0.5 * rest), 3), rest_res
        else:
            rd, resd = r, res
    ret = lambda k: float(c[i + k] / entry - 1) if i + k < n else None
    w = slice(i + 1, last + 1)
    out = {"res": res, "days": day, "r": r, "res2": res2, "days2": day2, "r2": r2,
           "res3": res3, "days3": day3, "r3": r3, "resd": resd, "rd": rd,
           "mfe": float(h[w].max() / entry - 1), "mae": float(l[w].min() / entry - 1),
           "final": res != "running" and res2 != "running" and res3 != "running" and resd != "running"}
    for k in RET_DAYS:
        out[f"r{k}"] = ret(k)
    return out


def _r(x, d):
    return None if x is None or x != x else round(float(x), d)


def _py(v):
    """numpy-Zahlen → JSON-taugliche Python-Werte."""
    if isinstance(v, (bool, np.bool_)):
        return bool(v)
    if isinstance(v, (int, np.integer)):
        return int(v)
    if isinstance(v, (float, np.floating)):
        return _r(v, 4)
    return v


def scan_history(df: pd.DataFrame, ticker: str, start: int = 260, base_every: int = 15) -> list[dict]:
    """Alle Signale (und Vergleichstage) einer Aktie über die Historie."""
    from .analysis import swing_levels
    from .scanner import evaluate

    df = df.dropna(subset=["Open", "High", "Low", "Close"])
    n = len(df)
    if n < start + 10:
        return []
    o, h, l, c = (df[k].to_numpy(float) for k in ("Open", "High", "Low", "Close"))
    from .indicators import ema as _ema, macd as _macd, rsi as _rsi
    from .mbi import momentum_bias_index
    e20 = _ema(df["Close"], 20).to_numpy(float)
    cf = CONFIG
    rsi_s = _rsi(df["Close"], cf.rsi.length).to_numpy(float)
    mh = _macd(df["Close"], cf.macd.fast, cf.macd.slow, cf.macd.signal)["hist"].to_numpy(float)
    rx = momentum_bias_index(df["Close"], df["High"], df["Low"], cf.mbi.momentum_length, cf.mbi.bias_length, cf.mbi.smooth_length,
                             cf.mbi.impulse_length, cf.mbi.std_mult)["red_x"].to_numpy(bool)
    out, last_sig = [], {"hit": -99, "fast": -99, "trend": -99}

    def pxrec(i, stop, t1, t2, lv, atr):
        cl, j1 = c[i], min(n, i + 1 + HOLD)
        rn = lambda a: [round(float(x / cl), 4) for x in a]
        return {"o": rn(o[i + 1:j1]), "h": rn(h[i + 1:j1]), "l": rn(l[i + 1:j1]), "c": rn(c[i + 1:j1]),
                "pl": rn(l[max(0, i - 9):i + 1]), "e20": round(float(e20[i] / cl), 4),
                "atr": round(float(atr / cl), 4), "s": round(float(stop / cl), 4),
                "t1": round(float(t1 / cl), 4) if t1 else None, "t2": round(float(t2 / cl), 4) if t2 else None,
                "tp": [round(float(z["p"] / cl), 4) for z in lv[:3]],
                "rsi": [round(float(x), 1) for x in rsi_s[i + 1:j1]], "mh": [round(float(x / cl), 5) for x in mh[i + 1:j1]],
                "mh0": round(float(mh[i] / cl), 5), "rx": [int(x) for x in rx[i + 1:j1]]}

    for i in range(start, n):
        try:
            r = evaluate(df.iloc[: i + 1])
        except Exception:
            continue
        # Zweites Setup zum Vergleich: Rücksetzer im Aufwärtstrend (weit gefasst aufgezeichnet, genaue Schwellen in der Analyse)
        fl = r.flags
        if fl.get("ema200") and fl.get("ema50") and fl.get("rsi") is not None and fl.get("atr"):
            cl, atr = r.close, fl["atr"]
            g200, g50 = cl / fl["ema200"] - 1, cl / fl["ema50"] - 1
            if g200 >= 0.05 and -0.12 <= g50 <= 0.01 and 30 <= fl["rsi"] <= 55 and cl >= 1:
                fresh = i - last_sig["trend"] > GAP
                last_sig["trend"] = i
                if fresh and i + 1 < n:
                    stop = min(float(l[max(0, i - 9):i + 1].min()) - 0.25 * atr, cl - atr)
                    try:
                        lv = swing_levels(df.iloc[: i + 1], cl, atr)
                    except Exception:
                        lv = []
                    tp1 = lv[0]["p"] if lv else None
                    oc = outcome(o, h, l, c, i, cl, stop, cl + 2 * atr, None, tp1)
                    if oc:
                        out.append({"t": ticker, "d": str(df.index[i].date()), "k": "trend", "score": 0, "crv": 0,
                                    "stop_pct": round(1 - stop / cl, 4), **oc,
                                    "f": {"rsi": _r(fl["rsi"], 1), "atrp": _r(atr / cl, 4), "vol": _r(fl.get("volatility"), 3),
                                          "e200": _r(g200, 3), "e50": _r(g50, 3),
                                          "dd": _r((r.zone["H"] - cl) / r.zone["H"], 3) if r.zone.get("H") else None,
                                          "e200up": bool(fl["ema50"] > fl["ema200"]), "kairo": bool(r.passed)},
                                    "px": pxrec(i, stop, cl + 2 * atr, None, lv, atr)})
        kind = "hit" if r.passed else "fast" if r.fast_hit else None
        base = kind is None and (i - start) % base_every == 0
        if kind:
            fresh = i - last_sig[kind] > GAP
            last_sig[kind] = i
            if not fresh:
                continue
        elif not base:
            continue
        p = r.plan or {}
        if not p.get("stop"):
            if not base:
                continue
            atr = r.flags.get("atr") or 0
            p = {"entry": r.close, "stop": r.close - 2 * atr, "target1": r.close + 2 * atr, "target2": None, "crv": 1.0}
        tp1, lv = None, []
        if kind:
            try:
                lv = swing_levels(df.iloc[: i + 1], r.close, r.flags.get("atr") or 0)
                tp1 = lv[0]["p"] if lv else None
            except Exception:
                tp1, lv = None, []
        oc = outcome(o, h, l, c, i, p["entry"], p["stop"], p.get("target1"), p.get("target2"), tp1)
        if not oc:
            continue
        out.append({"t": ticker, "d": str(df.index[i].date()), "k": kind or "base", "score": r.score,
                    "crv": round(p.get("crv") or 0, 2), "stop_pct": round(1 - p["stop"] / p["entry"], 4),
                    "t1_pct": round(p["target1"] / p["entry"] - 1, 4) if p.get("target1") else None,
                    "tp1_pct": round(tp1 / p["entry"] - 1, 4) if tp1 else None,
                    "earn": bool(r.flags.get("earnings_risk")), "zone": "Fib" if (r.zone.get("fib") or {}).get("ok") else "Support",
                    "div": (r.flags.get("divergence") or {}).get("kind"), **oc,
                    # für die Kriterien-Analyse: was fehlte (Fast-Treffer) und Merkmale am Signaltag
                    "miss": [m.key for m in r.missing],
                    "f": {"rsi": _r(r.flags.get("rsi"), 1), "atrp": _r((r.flags.get("atr") or 0) / r.close, 4),
                          "vol": _r(r.flags.get("volatility"), 3), "e200": _r(r.close / r.flags["ema200"] - 1, 3) if r.flags.get("ema200") else None,
                          "e50": _r(r.close / r.flags["ema50"] - 1, 3) if r.flags.get("ema50") else None,
                          "dd": _r((r.zone["H"] - r.close) / r.zone["H"], 3) if r.zone.get("H") else None,
                          "raw": {k[4:]: _py(v) for k, v in r.flags.items()
                                  if k.startswith("raw_") and v is not None and kind} if kind else None,
                          "macd_age": _py(r.flags.get("macd_cross_age")) if kind else None, "crv": _r((r.plan or {}).get("crv"), 2),
                          "div_age": _py(r.flags.get("div_t2_age")) if kind else None,
                          "ok": "".join("1" if c.ok else "0" for c in r.criteria) if kind else None,
                          "met": int(sum(c.ok for c in r.criteria if c.key not in ("cap", "liquidity", "price", "history")))}})
        if kind:                                   # Kursverlauf danach (für den Ausstiegs-Backtest, relativ zum Schluss)
            out[-1]["px"] = pxrec(i, p["stop"], p.get("target1"), p.get("target2"), lv, r.flags.get("atr") or 0)
    return out


def _agg(ev: list[dict]) -> dict:
    ev = [e for e in ev if e["res"] != "running"]
    n = len(ev)
    if not n:
        return {"n": 0}
    f = lambda k: [e[k] for e in ev if e.get(k) is not None]
    mean = lambda xs: round(float(np.mean(xs)), 4) if xs else None
    t1 = sum(e["res"] == "t1" for e in ev)
    st = sum(e["res"] == "stop" for e in ev)
    out = {"n": n, "t1": round(t1 / n, 3), "stop": round(st / n, 3), "open": round((n - t1 - st) / n, 3),
           "avg_r": mean(f("r")), "mfe": mean(f("mfe")), "mae": mean(f("mae")),
           "days_t1": mean([e["days"] for e in ev if e["res"] == "t1"])}
    for k in RET_DAYS:
        xs = f(f"r{k}")
        out[f"r{k}"] = mean(xs)
        if k in (20, 63) and xs:
            out[f"win{k}"] = round(float(np.mean([x > 0 for x in xs])), 3)
    e3 = [e for e in ev if e.get("res3") not in (None, "running")]
    if e3:
        out["c"] = {"n": len(e3), "hit": round(sum(e["res3"] == "t1" for e in e3) / len(e3), 3),
                    "stop": round(sum(e["res3"] == "stop" for e in e3) / len(e3), 3),
                    "open": round(sum(e["res3"] == "open" for e in e3) / len(e3), 3),
                    "avg_r": mean([e["r3"] for e in e3]), "days": mean([e["days3"] for e in e3 if e["res3"] == "t1"]),
                    "dist": mean([e["tp1_pct"] for e in e3 if e.get("tp1_pct") is not None])}
    ed = [e for e in ev if e.get("resd") not in (None, "running")]
    if ed:
        out["d"] = {"n": len(ed), "avg_r": mean([e["rd"] for e in ed]),
                    "full": round(sum(e["resd"] == "t2" for e in ed) / len(ed), 3),
                    "be": round(sum(e["resd"] == "be" for e in ed) / len(ed), 3),
                    "stop": round(sum(e["resd"] == "stop" for e in ed) / len(ed), 3)}
    e2 = [e for e in ev if e.get("res2") not in (None, "running")]
    if e2:
        out["b"] = {"n": len(e2), "t2": round(sum(e["res2"] == "t2" for e in e2) / len(e2), 3),
                    "stop": round(sum(e["res2"] == "stop" for e in e2) / len(e2), 3),
                    "open": round(sum(e["res2"] == "open" for e in e2) / len(e2), 3),
                    "avg_r": mean([e["r2"] for e in e2]), "days": mean([e["days2"] for e in e2 if e["res2"] == "t2"])}
    return out


def stats(ev: list[dict]) -> dict:
    hits = [e for e in ev if e["k"] == "hit"]
    bucket = lambda s: "80+" if s >= 80 else "70–79" if s >= 70 else "60–69" if s >= 60 else "< 60"
    out = {"hit": _agg(hits), "fast": _agg([e for e in ev if e["k"] == "fast"]), "base": _agg([e for e in ev if e["k"] == "base"]),
           "trend": _agg([e for e in ev if e["k"] == "trend"]),
           "score": {b: _agg([e for e in hits if bucket(e.get("score") or 0) == b]) for b in ("80+", "70–79", "60–69", "< 60")},
           "crv": {b: _agg([e for e in hits if ((e.get("crv") or 0) >= 3) == (b == "≥ 3")]) for b in ("≥ 3", "2–3")},
           "zone": {b: _agg([e for e in hits if e.get("zone") == b]) for b in ("Fib", "Support")},
           "div": {b: _agg([e for e in hits if (e.get("div") or "keine") == b]) for b in ("klassisch", "versteckt")}}
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--shard", type=int, default=0)
    ap.add_argument("--shards", type=int, default=1)
    ap.add_argument("--n", type=int, default=1600)
    ap.add_argument("--period", default="3y", help="Kurshistorie, z. B. 3y oder 6y (Prüfung über mehrere Marktphasen)")
    ap.add_argument("--combine", nargs="*")
    a = ap.parse_args(argv)
    if a.combine is not None:
        ev, seen = [], set()
        for p in a.combine:
            for e in json.loads(Path(p).read_text()):
                if (e["t"], e["d"], e["k"]) not in seen:      # Aktien können in mehreren Listen stehen
                    seen.add((e["t"], e["d"], e["k"]))
                    ev.append(e)
        res = {"generated": time.strftime("%Y-%m-%d"), "stocks": len({e["t"] for e in ev}),
               "period": [min(e["d"] for e in ev), max(e["d"] for e in ev)], "stats": stats(ev),
               "recent": [{k: v for k, v in e.items() if k != "px"} for e in sorted([e for e in ev if e["k"] == "hit"], key=lambda e: e["d"])[-40:]]}
        (ROOT / "data" / "bilanz_backtest.json").write_text(json.dumps(res, ensure_ascii=False, separators=(",", ":")))
        print("BILANZ " + json.dumps(res, ensure_ascii=False, separators=(",", ":")))
        return 0
    from .data_provider import YFinanceProvider
    from .universe import load as load_universe

    tickers = list(load_universe()["ticker"])
    random.Random(11).shuffle(tickers)
    mine = tickers[: a.n][a.shard::a.shards]
    data = YFinanceProvider().history(mine, a.period)   # Standard 3 Jahre; 6 Jahre zur Prüfung inkl. Bärenmarkt 2022
    print(f"Shard {a.shard}: {len(data)} von {len(mine)} Aktien geladen")
    ev, t0 = [], time.time()
    for k, (t, df) in enumerate(data.items()):
        ev += scan_history(df, t)
        if k % 25 == 0:
            print(f"  {k} Aktien, {sum(e['k'] == 'hit' for e in ev)} Treffer-Signale, {time.time() - t0:.0f} s")
    Path(f"bilanz_part_{a.shard}.json").write_text(json.dumps(ev, separators=(",", ":")))
    print(f"Fertig: {len(ev)} Ereignisse")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
