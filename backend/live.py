"""Live-Bilanz: Signale des täglichen Scans speichern und ihr Ergebnis nachverfolgen (siehe bilanz.py)."""

from __future__ import annotations

import json

import pandas as pd

from . import state
from .bilanz import GAP, _agg, outcome, stats
from .config import ROOT


def update(rows: list[dict], data: dict[str, pd.DataFrame], today: str) -> dict:
    sig = state.load("signals.json", [])
    last = state.load("last.json", {})
    prev = {"hit": set(last.get("hit", [])), "fast": set(last.get("fast", []))}
    known = {(s["t"], s["k"], s["d"]) for s in sig}
    recent = {}
    for s in sig:                                  # letztes Signal je Aktie/Art
        recent[(s["t"], s["k"])] = max(recent.get((s["t"], s["k"]), ""), s["d"])
    new = []
    for r in rows:
        k = "hit" if r["passed"] else "fast" if r.get("fast_hit") else None
        p = r.get("plan") or {}
        if not k or not p.get("stop") or not p.get("entry"):
            continue
        d = r.get("date") or today
        if r["ticker"] in prev[k] or (r["ticker"], k, d) in known:
            continue
        lastd = recent.get((r["ticker"], k))
        if lastd and (pd.Timestamp(d) - pd.Timestamp(lastd)).days <= GAP + 2:
            continue
        s = {"t": r["ticker"], "n": (r.get("name") or r["ticker"])[:40], "k": k, "d": d, "score": r.get("score", 0),
             "entry": p["entry"], "stop": p["stop"], "t1": p.get("target1"), "t2": p.get("target2"), "crv": p.get("crv"),
             "region": r.get("region"), "grade": (r.get("grade") or {}).get("g"), "res": "running"}
        sig.append(s)
        new.append(s)
    # Ergebnisse nachführen
    for s in sig:
        if s.get("final"):
            continue
        df = data.get(s["t"])
        if df is None:
            continue
        df = df.dropna(subset=["Open", "High", "Low", "Close"])
        idx = df.index.searchsorted(pd.Timestamp(s["d"]), side="right") - 1
        if idx < 0:
            continue
        o, h, l, c = (df[k].to_numpy(float) for k in ("Open", "High", "Low", "Close"))
        oc = outcome(o, h, l, c, idx, s["entry"], s["stop"], s.get("t1"), s.get("t2"))
        if oc:
            s.update(oc)
            s["now"] = round(float(c[-1] / s["entry"] - 1), 4)
    state.save("signals.json", sig)
    state.save("last.json", {"date": today, "hit": [r["ticker"] for r in rows if r["passed"]],
                             "fast": [r["ticker"] for r in rows if r.get("fast_hit")],
                             "met": {r["ticker"]: r.get("met") for r in rows}})
    try:
        bt = json.loads((ROOT / "data" / "bilanz_backtest.json").read_text(encoding="utf-8"))
    except Exception:
        bt = None
    done = [s for s in sig if s.get("res") not in (None, "running")]
    out = {"generated": today, "live": {"since": min((s["d"] for s in sig), default=today), "n": len(sig),
                                        "stats": stats(done) if done else None,
                                        "grade": {g: _agg([x for x in done if x["k"] == "hit" and x.get("grade") == g]) for g in "ABC"}},
           "signals": sorted(sig, key=lambda s: s["d"], reverse=True)[:80], "new": [s["t"] for s in new], "backtest": bt}
    return out
