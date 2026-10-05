"""Qualitätsstufe A/B/C für Treffer – aus dem Backtest, an ungesehenen Daten geprüft.

Die 11 Kriterien bleiben unverändert; die Stufe ordnet Treffer nur nach historisch belegter Qualität.
Vorgehen (`python -m backend.grade bilanz_part_*.json`):
1. Nur abgeschlossene Treffer-Signale. Zeitlich teilen: ältere 60 % = Lernen, neuere 40 % = Prüfen.
2. Kandidaten-Merkmale (Zone, Score, CRV, Divergenz, Stop-Abstand). Ein Merkmal zählt nur, wenn es im Lernteil
   mit ≥ 120 Signalen und deutlichem Abstand (t-Wert ≥ 2) besser bzw. schlechter abschneidet → +1 / −1 Punkt.
3. Stufen nach Punkten (Schwellen aus dem Lernteil: oberes ~30 % = A, unteres ~30 % = C).
4. Prüfen: Im Prüfteil muss A > B > C beim Ø Ergebnis (R) gelten, sonst wird das Modell nicht übernommen.
Maßstab: Ø R mit deiner Ausstiegsregel (TP 1 der Hoch-Treppe, Stop laut Plan, max. 3 Monate).
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np

from .config import ROOT

PATH = ROOT / "data" / "grade_model.json"

FEATURES = {
    "fib": ("Fib-Zone", lambda e: e["zone"] == "Fib"),
    "score80": ("Score ≥ 80", lambda e: e["score"] >= 80),
    "score_low": ("Score < 70", lambda e: e["score"] < 70),
    "crv23": ("CRV 2–3", lambda e: e["crv"] < 3),
    "crv_hi": ("CRV ≥ 6", lambda e: e["crv"] >= 6),
    "div_hidden": ("versteckte Divergenz", lambda e: e.get("div") == "versteckt"),
    "stop_tight": ("enger Stop < 3 %", lambda e: (e.get("stop_pct") or 0) < 0.03),
    "stop_wide": ("weiter Stop > 8 %", lambda e: (e.get("stop_pct") or 0) > 0.08),
    "t1_near": ("Ziel 1 < 2 % entfernt", lambda e: (e.get("t1_pct") or 1) < 0.02),
}


def value(e: dict) -> float:
    if e.get("r3") is not None:                   # Maßstab: deine Ausstiegsregel (TP 1 der Hoch-Treppe)
        return float(e["r3"])
    vals = [v for v in (e.get("r"), e.get("r2")) if v is not None]
    return float(np.mean(vals)) if vals else 0.0


def points(e: dict, weights: dict) -> int:
    return sum(w for k, w in weights.items() if FEATURES[k][1](e))


def _summary(ev):
    if not ev:
        return {"n": 0}
    v = np.array([value(e) for e in ev])
    t1 = np.mean([e["res"] == "t1" for e in ev])
    st = np.mean([e["res"] == "stop" for e in ev])
    r63 = [e["r63"] for e in ev if e.get("r63") is not None]
    return {"n": len(ev), "avg_r": round(float(v.mean()), 3), "t1": round(float(t1), 3), "stop": round(float(st), 3),
            "r63": round(float(np.mean(r63)), 4) if r63 else None}


def fit(events: list[dict]) -> dict:
    ev = sorted([e for e in events if e["k"] == "hit" and e["res"] not in ("running", None)], key=lambda e: e["d"])
    cut = int(len(ev) * 0.6)
    train, test = ev[:cut], ev[cut:]
    weights, effects = {}, {}
    for k, (label, f) in FEATURES.items():
        a = np.array([value(e) for e in train if f(e)])
        b = np.array([value(e) for e in train if not f(e)])
        if len(a) < 120 or len(b) < 120:
            continue
        d = a.mean() - b.mean()
        se = np.sqrt(a.var(ddof=1) / len(a) + b.var(ddof=1) / len(b))
        t = d / se if se else 0
        effects[k] = {"label": label, "n": int(len(a)), "delta": round(float(d), 3), "t": round(float(t), 2)}
        if abs(t) >= 2:
            weights[k] = round(float(d), 3)           # Gewicht = gemessener Vorteil in R
    pts = np.array([points(e, weights) for e in train]) if train else np.array([0.0])
    levels = sorted(set(np.round(pts, 6)))
    # Schwellen: C = unterste Stufen (~15–45 %), A = oberste Stufen (~15–45 %), dazwischen B
    best = None
    for lo in levels:
        for hi in levels:
            if hi <= lo:
                continue
            sc, sa = float(np.mean(pts <= lo + 1e-9)), float(np.mean(pts >= hi - 1e-9))
            sb = 1 - sc - sa
            if not (0.15 <= sc <= 0.45 and 0.15 <= sa <= 0.45 and sb >= 0.15):
                continue
            key = -abs(sc - 0.3) - abs(sa - 0.3)
            if best is None or key > best[0]:
                best = (key, lo, hi)
    lo, hi = (best[1], best[2]) if best else (float("-inf"), float("inf"))
    grade = lambda e: "A" if points(e, weights) >= hi - 1e-9 else "C" if points(e, weights) <= lo + 1e-9 else "B"
    res = {}
    for name, part in (("train", train), ("test", test)):
        res[name] = {g: _summary([e for e in part if grade(e) == g]) for g in "ABC"}
    t = res["test"]
    ok = bool(best) and all(t[g]["n"] >= 40 for g in "ABC") and t["A"]["avg_r"] > t["B"]["avg_r"] > t["C"]["avg_r"]
    return {"fitted": time.strftime("%Y-%m-%d"), "weights": weights, "thr": [lo, hi] if best else None,
            "labels": {k: FEATURES[k][0] for k in FEATURES}, "effects": effects, "valid": bool(ok),
            "period": [ev[0]["d"], ev[-1]["d"]] if ev else None, "split": test[0]["d"] if test else None, **res}


def grade_of(e: dict, model: dict | None) -> tuple[str | None, list]:
    """→ (Stufe, [(+1/−1, Merkmal), …]) für ein Signal mit Feldern score, crv, zone, div, stop_pct, t1_pct."""
    if not model or not model.get("valid"):
        return None, []
    w = model["weights"]
    p = points(e, w)
    lo, hi = model["thr"]
    why = [(1 if w[k] > 0 else -1, model["labels"][k]) for k in w if FEATURES[k][1](e)]
    return ("A" if p >= hi - 1e-9 else "C" if p <= lo + 1e-9 else "B"), why


def load() -> dict | None:
    try:
        return json.loads(PATH.read_text(encoding="utf-8"))
    except Exception:
        return None


def main(argv=None) -> int:
    files = (argv if argv is not None else sys.argv[1:])
    ev, seen = [], set()
    for p in files:
        for e in json.loads(Path(p).read_text()):
            if (e["t"], e["d"], e["k"]) not in seen:
                seen.add((e["t"], e["d"], e["k"]))
                ev.append(e)
    m = fit(ev)
    PATH.write_text(json.dumps(m, ensure_ascii=False), encoding="utf-8")
    print("GRADE " + json.dumps(m, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
