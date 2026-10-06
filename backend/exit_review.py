"""Absicherung der Ausstiegs-Empfehlung auf den gespeicherten Kursverläufen eines Bilanz-Laufs (ohne neu zu rechnen).

1. Spitzengruppe: die 8 Regeln mit dem besten Ergebnis nach Kosten (ganzer Zeitraum), die in Lernen UND Prüfen positiv sind.
2. Dein Handeln ohne Stop-Order: Verkauf erst bei Schluss unter dem Stop – mit Turbo-K.-o. 0,5 / 1 / 1,5 ATR unter dem Stop
   (berührt das Tief den K.-o., ist der Turbo wertlos). Daraus: K.-o.-Quote und typischer Hebel je Abstand.
3. Statistische Sicherheit: Bootstrap – mit welcher Wahrscheinlichkeit ist eine Regel wirklich besser als „TP 1“?
4. Jahr für Jahr (inkl. 2020/2022 bei 6 Jahren Historie).

Aufruf: python -m backend.exit_review bilanz_part_*.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

from .config import ROOT
from .exits import RULES, SPLIT, SPREAD, FIN_DAY, run as run_all, simulate

BASE = "TP 1 – nächstes relevantes Hoch"


def _net(x):
    return x["r"] - (SPREAD + FIN_DAY * x["d"]) / max(x["rp"], 1e-4)


def main(argv=None) -> int:
    files = argv if argv is not None else sys.argv[1:]
    ev, seen = [], set()
    for p in files:
        for e in json.loads(Path(p).read_text()):
            k = (e["t"], e["d"], e["k"])
            if e.get("px") and e["k"] in ("hit", "fast") and k not in seen:
                seen.add(k)
                ev.append(e)
    rng = np.random.default_rng(1)
    rules = dict((n, r) for n, _, r in RULES)

    def run(rule, mode="intraday", kb=None):
        out = []
        for e in ev:
            x = simulate(e["px"], rule, mode, kb)
            if x:
                out.append((e, x))
        return out

    # 1) Spitzengruppe nach Kosten (Stop-Order-Modus wie im Haupt-Backtest)
    base = {}
    for n, r in rules.items():
        sims = run(r)
        net = np.array([_net(x) for _, x in sims])
        tr = np.array([_net(x) for e, x in sims if e["d"] < SPLIT])
        te = np.array([_net(x) for e, x in sims if e["d"] >= SPLIT])
        base[n] = {"sims": sims, "net": float(net.mean()) if len(net) else -9,
                   "train": float(tr.mean()) if len(tr) else None, "test": float(te.mean()) if len(te) else None}
    cand = [n for n, v in base.items() if (v["train"] or -1) > 0 and (v["test"] or -1) > 0]
    top = sorted(cand, key=lambda n: -base[n]["net"])[:8]
    if BASE not in top:
        top.append(BASE)
    full = run_all(ev)                            # komplette Rangliste mit korrigierter Rechnung
    res = {"n_signals": len(ev), "period": [min(e["d"] for e in ev), max(e["d"] for e in ev)], "top": [],
           "table": [{"name": r["name"], **{k: {kk: r[k].get(kk) for kk in ("n", "avg_r", "avg_r_net", "win", "days", "r_month_net", "worst5")}
                                            for k in ("all_all", "all_hit", "train_all", "test_all")}} for r in full["rules"]],
           "robust": full["robust"], "ko_on_stop": full["ko_on_stop"]}
    # Paarweiser Vergleich mit TP 1 (gleiche Signale)
    bmap = {(e["t"], e["d"], e["k"]): _net(x) for e, x in base[BASE]["sims"]}
    for n in top:
        v = base[n]
        row = {"name": n, "net": round(v["net"], 3), "train": round(v["train"], 3), "test": round(v["test"], 3),
               "days": round(float(np.mean([x["d"] for _, x in v["sims"]])), 1)}
        row["r_month_net"] = round(v["net"] / row["days"] * 21, 3)
        yrs = {}
        for e, x in v["sims"]:
            yrs.setdefault(e["d"][:4], []).append(_net(x))
        row["years"] = {y: [len(a), round(float(np.mean(a)), 3)] for y, a in sorted(yrs.items())}
        diffs = np.array([_net(x) - bmap[(e["t"], e["d"], e["k"])] for e, x in v["sims"] if (e["t"], e["d"], e["k"]) in bmap])
        if len(diffs) and n != BASE:
            boot = np.array([rng.choice(diffs, len(diffs)).mean() for _ in range(1000)])
            row["vs_tp1"] = {"diff": round(float(diffs.mean()), 3), "ci95": [round(float(np.percentile(boot, 2.5)), 3), round(float(np.percentile(boot, 97.5)), 3)],
                             "p_better": round(float((boot > 0).mean()), 3)}
        # 2) Ohne Stop-Order (Schluss unter Stop) + Turbo-K.-o.
        row["no_stop_order"] = {}
        for kb in (None, 0.5, 1.0, 1.5):
            sims = run(rules[n], "close", kb)
            net = np.array([_net(x) for _, x in sims])
            row["no_stop_order"]["ohne K.-o." if kb is None else f"K.-o. {kb} ATR"] = {
                "net": round(float(net.mean()), 3), "ko": round(float(np.mean([x["x"] == "ko" for _, x in sims])), 3),
                "worst5": round(float(np.percentile(net, 5)), 2)}
        res["top"].append(row)
    # Typischer Hebel je K.-o.-Abstand (Turbo-Hebel ≈ Kurs ÷ (Kurs − K.-o.))
    lev = {}
    for kb in (0.5, 1.0, 1.5):
        ls = [e["px"]["o"][0] / (e["px"]["o"][0] - (e["px"]["s"] - kb * e["px"]["atr"])) for e in ev
              if e["px"]["o"] and e["px"]["o"][0] > e["px"]["s"]]
        lev[f"{kb} ATR"] = {"median": round(float(np.median(ls)), 1), "p25": round(float(np.percentile(ls, 25)), 1),
                            "p75": round(float(np.percentile(ls, 75)), 1)}
    res["leverage"] = lev
    (ROOT / "data" / "exit_review.json").write_text(json.dumps(res, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print("EXREVIEW " + json.dumps(res, ensure_ascii=False, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
