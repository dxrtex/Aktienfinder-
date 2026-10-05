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

HOLD = 30           # max. Handelstage für Ziel/Stop
GAP = 5             # neue Signal-Phase erst nach ≥ 5 Tagen ohne Signal


def outcome(o, h, l, c, i: int, entry: float, stop: float, t1: float | None, t2: float | None) -> dict | None:
    """Verlauf ab dem Tag nach dem Signal (Index i). Arrays: Open/High/Low/Close."""
    n = len(c)
    if i + 1 >= n or not stop or entry <= stop:
        return None
    risk = entry - stop
    res, day, end_px = None, None, None
    t2_hit = False
    for j in range(i + 1, min(n, i + 1 + HOLD)):
        if l[j] <= stop:
            res, day, end_px = "stop", j - i, stop
            break
        if t1 and h[j] >= t1:
            res, day, end_px = "t1", j - i, t1
            t2_hit = bool(t2 and h[i + 1:j + 1].max() >= t2)
            break
    done = i + HOLD < n or res is not None
    if res is None:
        last = min(n - 1, i + HOLD)
        end_px = c[last]
        res = "open" if done else "running"
    ret = lambda k: float(c[i + k] / entry - 1) if i + k < n else None
    w = slice(i + 1, min(n, i + 21))
    return {"res": res, "days": day, "r": round(float((end_px - entry) / risk), 3),
            "r5": ret(5), "r10": ret(10), "r20": ret(20),
            "mfe": float(h[w].max() / entry - 1) if i + 1 < n else None,
            "mae": float(l[w].min() / entry - 1) if i + 1 < n else None,
            "t2": t2_hit, "final": done}


def scan_history(df: pd.DataFrame, ticker: str, start: int = 260, base_every: int = 15) -> list[dict]:
    """Alle Signale (und Vergleichstage) einer Aktie über die Historie."""
    from .scanner import evaluate

    df = df.dropna(subset=["Open", "High", "Low", "Close"])
    n = len(df)
    if n < start + 10:
        return []
    o, h, l, c = (df[k].to_numpy(float) for k in ("Open", "High", "Low", "Close"))
    out, last_sig = [], {"hit": -99, "fast": -99}
    for i in range(start, n):
        try:
            r = evaluate(df.iloc[: i + 1])
        except Exception:
            continue
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
        oc = outcome(o, h, l, c, i, p["entry"], p["stop"], p.get("target1"), p.get("target2"))
        if not oc:
            continue
        out.append({"t": ticker, "d": str(df.index[i].date()), "k": kind or "base", "score": r.score,
                    "crv": round(p.get("crv") or 0, 2), "stop_pct": round(1 - p["stop"] / p["entry"], 4),
                    "t1_pct": round(p["target1"] / p["entry"] - 1, 4) if p.get("target1") else None,
                    "earn": bool(r.flags.get("earnings_risk")), "zone": "Fib" if (r.zone.get("fib") or {}).get("ok") else "Support",
                    "div": (r.flags.get("divergence") or {}).get("kind"), **oc})
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
    r20 = f("r20")
    return {"n": n, "t1": round(t1 / n, 3), "stop": round(st / n, 3), "open": round((n - t1 - st) / n, 3),
            "t2": round(sum(e.get("t2", False) for e in ev) / n, 3),
            "avg_r": mean(f("r")), "r5": mean(f("r5")), "r10": mean(f("r10")), "r20": mean(r20),
            "med20": round(float(np.median(r20)), 4) if r20 else None, "win20": round(float(np.mean([x > 0 for x in r20])), 3) if r20 else None,
            "mfe": mean(f("mfe")), "mae": mean(f("mae")), "days_t1": mean([e["days"] for e in ev if e["res"] == "t1"])}


def stats(ev: list[dict]) -> dict:
    hits = [e for e in ev if e["k"] == "hit"]
    bucket = lambda s: "80+" if s >= 80 else "70–79" if s >= 70 else "60–69" if s >= 60 else "< 60"
    out = {"hit": _agg(hits), "fast": _agg([e for e in ev if e["k"] == "fast"]), "base": _agg([e for e in ev if e["k"] == "base"]),
           "score": {b: _agg([e for e in hits if bucket(e["score"]) == b]) for b in ("80+", "70–79", "60–69", "< 60")},
           "crv": {b: _agg([e for e in hits if (e["crv"] >= 3) == (b == "≥ 3")]) for b in ("≥ 3", "2–3")},
           "zone": {b: _agg([e for e in hits if e["zone"] == b]) for b in ("Fib", "Support")},
           "div": {b: _agg([e for e in hits if (e["div"] or "keine") == b]) for b in ("klassisch", "versteckt")}}
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--shard", type=int, default=0)
    ap.add_argument("--shards", type=int, default=1)
    ap.add_argument("--n", type=int, default=1600)
    ap.add_argument("--combine", nargs="*")
    a = ap.parse_args(argv)
    if a.combine is not None:
        ev = []
        for p in a.combine:
            ev += json.loads(Path(p).read_text())
        res = {"generated": time.strftime("%Y-%m-%d"), "stocks": len({e["t"] for e in ev}),
               "period": [min(e["d"] for e in ev), max(e["d"] for e in ev)], "stats": stats(ev),
               "recent": sorted([e for e in ev if e["k"] == "hit"], key=lambda e: e["d"])[-40:]}
        (ROOT / "data" / "bilanz_backtest.json").write_text(json.dumps(res, ensure_ascii=False, separators=(",", ":")))
        print("BILANZ " + json.dumps(res, ensure_ascii=False, separators=(",", ":")))
        return 0
    from .data_provider import YFinanceProvider
    from .universe import load as load_universe

    tickers = list(load_universe()["ticker"])
    random.Random(11).shuffle(tickers)
    mine = tickers[: a.n][a.shard::a.shards]
    data = YFinanceProvider().history(mine, CONFIG.history.period)
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
