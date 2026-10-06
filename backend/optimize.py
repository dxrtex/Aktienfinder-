"""Analyse beider Kairo-Werkzeuge auf den gespeicherten Signalen eines Bilanz-Laufs (6 Jahre).

A) Einstieg (Scanner): Bringen die Treffer mehr als zufällige Tage? Welches der 11 Kriterien trägt wirklich?
   – Treffer vs. Vergleichstage (alle 15 Tage je Aktie) vs. Fast-Treffer, je nachdem welches Kriterium fehlte.
   – Merkmale am Signaltag (RSI, Abstand EMA 200, Volatilität, Rückgang, Marktbreite) → wo liegt der Vorteil?
B) Verkauf (Gewinnmitnahme-Check im Depot): x von 6 Kriterien, ab wie vielen verkaufen? Welche Kriterien helfen?
   Gespielt wie du handelst: Turbo ohne Stop-Order, K.-o. 1 ATR unter dem Setup-Stop, max. 3 Monate,
   Verkauf am Morgen nach dem Signal (Eröffnung). Kosten (Spread, Finanzierung) abgezogen.
Alles getrennt in Lernen (bis 2025) und Prüfen (2026) – nur was in beiden hält, zählt.

Aufruf: python -m backend.optimize bilanz_part_*.json
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

from .config import ROOT
from .exits import RULES, SPLIT, SPREAD, FIN_DAY, simulate

HOLD = 63
KEYS = ["drawdown", "no_crash", "structure", "zone", "flattening", "rsi_div", "rsi_range", "macd_below0", "macd_turn", "mbi", "crv"]


def net(r, d, rp):
    return r - (SPREAD + FIN_DAY * d) / max(rp, 1e-4)


# ---------------------------------------------------------------- B) Verkaufs-Kriterien
def signals(px: dict) -> list[dict] | None:
    """Je Handelstag nach dem Kauf: welche Verkaufs-Signale sind an (Schlusskurs-Basis, wie im Depot)."""
    o, h, l, c = px["o"], px["h"], px["l"], px["c"]
    if len(c) < HOLD or not o:
        return None
    rsi, mh, rx = px.get("rsi") or [], px.get("mh") or [], px.get("rx") or []
    if len(rsi) < HOLD or len(mh) < HOLD:
        return None
    ema, a, lows, atr = px["e20"], 2 / 21, list(px["pl"]), px["atr"] or 0.02
    tps = sorted(px.get("tp") or [])
    mhp = [px.get("mh0") or 0, px.get("mh0") or 0] + list(mh)
    out, rsi_peak = [], 0
    for j in range(HOLD):
        ema += a * (c[j] - ema)
        lo10 = min(lows[-10:])
        nx = next((t for t in tps if t > c[j]), None)
        rsi_peak = max(rsi_peak, rsi[j])
        s = {"res": bool(nx and nx - c[j] < atr), "rsi": rsi[j] >= 70, "macd": mhp[j + 2] < mhp[j + 1] < mhp[j],
             "mbi": any(rx[max(0, j - 2):j + 1]), "ema": c[j] < ema, "low10": c[j] < lo10,
             # zusätzliche Kandidaten
             "rsi_roll": rsi_peak >= 70 and rsi[j] < 65, "macd_neg": mhp[j + 2] < 0 < mhp[j + 1], "rsi75": rsi[j] >= 75,
             "ema2": c[j] < ema and j > 0 and out and out[-1]["ema"]}
        out.append(s)
        lows.append(l[j])
    return out


def sim(px, sg, crit, k, gate=True, ko_buf=1.0, min_gain=0.0):
    """Verkauf am nächsten Morgen, sobald ≥ k der Kriterien an sind (gate: nur im Gewinn). Kein Stop, nur K.-o."""
    o, l, c = px["o"], px["l"], px["c"]
    entry, risk = o[0], 1.0 - px["s"]
    if entry <= px["s"] or risk <= 0:
        return None
    ko = px["s"] - ko_buf * px["atr"]
    rp = risk / entry
    for j in range(HOLD):
        oj = o[j] if j else entry
        if min(oj, l[j]) <= ko:
            return net((min(oj, ko) - entry) / risk, j + 1, rp), j + 1, "ko"
        if (not gate or c[j] > entry * (1 + min_gain)) and sum(sg[j][x] for x in crit) >= k:
            px_ = o[j + 1] if j + 1 < HOLD else c[j]
            return net((px_ - entry) / risk, j + 2, rp), j + 2, "sell"
    return net((c[HOLD - 1] - entry) / risk, HOLD, rp), HOLD, "time"


def summarize(rows):
    if not rows:
        return {"n": 0}
    r = np.array([x[0] for x in rows]); d = np.array([x[1] for x in rows])
    return {"n": len(rows), "r": round(float(r.mean()), 3), "win": round(float((r > 0).mean()), 3), "days": round(float(d.mean()), 1),
            "r_month": round(float(r.mean() / d.mean() * 21), 3), "ko": round(float(np.mean([x[2] == "ko" for x in rows])), 3),
            "p5": round(float(np.percentile(r, 5)), 2)}


def evaluate_rule(ev, fn):
    tr, te, yrs = [], [], defaultdict(list)
    for e in ev:
        x = fn(e)
        if x is None:
            continue
        (tr if e["d"] < SPLIT else te).append(x)
        yrs[e["d"][:4]].append(x)
    allr = tr + te
    return {"all": summarize(allr), "train": summarize(tr), "test": summarize(te),
            "years": {y: summarize(v)["r"] for y, v in sorted(yrs.items())}}


def exit_part(ev):
    for e in ev:
        e["_sg"] = signals(e["px"])
    ev = [e for e in ev if e["_sg"]]
    base6 = ["res", "rsi", "macd", "mbi", "ema", "low10"]
    out = {"n": len(ev), "grid": [], "loo": [], "greedy": None, "baselines": {}}
    # 1) Der Check wie in der App: x von 6, ab k verkaufen, mit/ohne „nur im Gewinn“
    for gate in (True, False):
        for k in range(1, 7):
            res = evaluate_rule(ev, lambda e: sim(e["px"], e["_sg"], base6, k, gate))
            out["grid"].append({"k": k, "gate": gate, **res})
    # 2) Welches Kriterium hilft? Weglassen (bei k aus der App: 4 → bei 5 Kriterien auf 4 bzw. 3 umgerechnet)
    for kk in (2, 3, 4):
        for drop in base6:
            crit = [x for x in base6 if x != drop]
            res = evaluate_rule(ev, lambda e: sim(e["px"], e["_sg"], crit, kk, True))
            out["loo"].append({"k": kk, "ohne": drop, "all": res["all"]["r"], "train": res["train"]["r"], "test": res["test"]["r"]})
    # 3) Beste Auswahl aus allen Kandidaten (nur auf Lern-Daten gesucht, dann geprüft)
    pool = base6 + ["rsi_roll", "macd_neg", "rsi75", "ema2"]
    train = [e for e in ev if e["d"] < SPLIT]
    score = lambda crit, k: summarize([x for x in (sim(e["px"], e["_sg"], crit, k, True) for e in train) if x])["r"]
    best, sel = (-9, None, None), []
    for _ in range(5):
        cand = []
        for c_ in pool:
            if c_ in sel:
                continue
            for k in range(1, len(sel) + 2):
                cand.append((score(sel + [c_], k), sel + [c_], k))
        top = max(cand, key=lambda x: x[0])
        if top[0] <= best[0] + 0.003:
            break
        best, sel = top, top[1]
    if best[1]:
        res = evaluate_rule(ev, lambda e: sim(e["px"], e["_sg"], best[1], best[2], True))
        out["greedy"] = {"crit": best[1], "k": best[2], **res}
    # 4) Vergleich: Halten bis 3 Monate (nur K.-o.), die getesteten Regeln ohne Stop-Order mit K.-o. 1 ATR
    for kb in (1.0, 1.5, 2.0, 3.0):
        out["baselines"][f"Halten 3 Monate (nur K.-o. {kb} ATR)"] = evaluate_rule(ev, lambda e, kb=kb: sim(e["px"], e["_sg"], [], 1, True, kb))
    for kk in (2, 3):
        crit = ["res", "rsi", "mbi", "ema", "low10"]
        out["baselines"][f"Check ohne MACD, ab {kk}"] = evaluate_rule(ev, lambda e, kk=kk: sim(e["px"], e["_sg"], crit, kk, True))
    # Nach Marktlage (Marktbreite am Kauftag): welche Verkaufsart passt wann?
    if any(e.get("_br") is not None for e in ev):
        rules_ = {n: r for n, _, r in RULES}
        fns = {"Halten": lambda e: sim(e["px"], e["_sg"], [], 1, True),
               "TP 2": lambda e: (lambda x: (net(x["r"], x["d"], x["rp"]), x["d"], x["x"]) if x else None)(simulate(e["px"], rules_["TP 2 – zweites relevantes Hoch"], "close", 1.0)),
               "10-Tage-Tief ab 1 R": lambda e: (lambda x: (net(x["r"], x["d"], x["rp"]), x["d"], x["x"]) if x else None)(simulate(e["px"], rules_["Nachziehen: 10-Tage-Tief, ab 1 R"], "close", 1.0))}
        reg = {}
        for lo, hi in ((0, 0.3), (0.3, 0.45), (0.45, 0.6), (0.6, 1.01)):
            es = [e for e in ev if e.get("_br") is not None and lo <= e["_br"] < hi]
            reg[f"{lo}-{hi}"] = {n: evaluate_rule(es, f)["all"] for n, f in fns.items()}
        out["by_breadth"] = reg
    rules = {n: r for n, _, r in RULES}
    for name in ("TP 2 – zweites relevantes Hoch", "Nachziehen: 10-Tage-Tief, ab 1 R", "TP 1 – nächstes relevantes Hoch",
                 "TP 1 – bei steigendem MACD weiter bis TP 2"):
        def fn(e, r=rules[name]):
            x = simulate(e["px"], r, "close", 1.0)
            return (net(x["r"], x["d"], x["rp"]), x["d"], x["x"]) if x else None
        out["baselines"][name + " (Schluss-Stop, K.-o. 1 ATR)"] = evaluate_rule(ev, fn)
    for e in ev:
        e.pop("_sg", None)
    return out


# ---------------------------------------------------------------- A) Einstiegs-Kriterien
def entry_part(ev_all, ev_px):
    out = {}
    have_miss = any("miss" in e for e in ev_all)
    groups = defaultdict(list)
    for e in ev_all:
        if e["k"] == "hit":
            groups["Treffer"].append(e)
        elif e["k"] == "base":
            groups["Vergleichstage (zufällig)"].append(e)
        elif e["k"] == "fast":
            m = [x for x in (e.get("miss") or []) if x in KEYS]
            groups["Fast: fehlt " + (m[0] if m else "Grundfilter" if have_miss else "?")].append(e)

    def ret_stats(es):
        res = {"n": len(es)}
        for k in (20, 63):
            v = np.array([e[f"r{k}"] for e in es if e.get(f"r{k}") is not None])
            tr = np.array([e[f"r{k}"] for e in es if e.get(f"r{k}") is not None and e["d"] < SPLIT])
            te = np.array([e[f"r{k}"] for e in es if e.get(f"r{k}") is not None and e["d"] >= SPLIT])
            res[f"ret{k}"] = round(float(v.mean()), 4) if len(v) else None
            res[f"ret{k}_train"] = round(float(tr.mean()), 4) if len(tr) else None
            res[f"ret{k}_test"] = round(float(te.mean()), 4) if len(te) else None
            res[f"up{k}"] = round(float((v > 0).mean()), 3) if len(v) else None
        mfe = [e["mfe"] for e in es if e.get("mfe") is not None]
        res["mfe"] = round(float(np.median(mfe)), 4) if mfe else None
        return res

    out["groups"] = {g: ret_stats(es) for g, es in sorted(groups.items(), key=lambda x: -len(x[1]))}
    # Treffer vs. Zufall je Jahr (Rendite nach 20 / 63 Tagen)
    yr = {}
    for y in sorted({e["d"][:4] for e in ev_all}):
        h_ = [e for e in groups["Treffer"] if e["d"][:4] == y]; b_ = [e for e in groups["Vergleichstage (zufällig)"] if e["d"][:4] == y]
        yr[y] = {"hit": ret_stats(h_), "base": ret_stats(b_)}
    out["by_year"] = {y: {"hit20": v["hit"].get("ret20"), "base20": v["base"].get("ret20"), "hit63": v["hit"].get("ret63"),
                          "base63": v["base"].get("ret63"), "n": v["hit"]["n"]} for y, v in yr.items()}
    # Ergebnis mit der empfohlenen Verkaufsregel (TP 2, Schluss-Stop, K.-o. 1 ATR) je Gruppe
    tp2 = {n: r for n, _, r in RULES}["TP 2 – zweites relevantes Hoch"]
    def rnet(e):
        x = simulate(e["px"], tp2, "close", 1.0)
        return net(x["r"], x["d"], x["rp"]) if x else None
    for e in ev_px:
        e["_rn"] = rnet(e)
    g2 = defaultdict(list)
    for e in ev_px:
        if e["_rn"] is None:
            continue
        if e["k"] == "hit":
            g2["Treffer"].append(e)
        else:
            m = [x for x in (e.get("miss") or []) if x in KEYS]
            g2["Fast: fehlt " + (m[0] if m else "Grundfilter" if have_miss else "?")].append(e)
    def rs(es):
        a = [e["_rn"] for e in es]; tr = [e["_rn"] for e in es if e["d"] < SPLIT]; te = [e["_rn"] for e in es if e["d"] >= SPLIT]
        return {"n": len(a), "r": round(float(np.mean(a)), 3), "train": round(float(np.mean(tr)), 3) if tr else None,
                "test": round(float(np.mean(te)), 3) if te else None}
    out["r_tp2"] = {g: rs(es) for g, es in sorted(g2.items(), key=lambda x: -len(x[1]))}
    # Merkmale am Signaltag (nur Treffer + Fast mit Kursverlauf): Vorteil je Bereich
    if any("f" in e for e in ev_px):
        # Marktbreite: Anteil der Vergleichstage derselben Woche über der EMA 200
        for e in ev_px:
            e.setdefault("f", {})["breadth"] = e.get("_br")
        bins = {"rsi": [0, 30, 35, 40, 45, 100], "e200": [-9, -0.2, -0.1, 0, 0.1, 9], "vol": [0, 0.25, 0.35, 0.5, 0.7, 9],
                "dd": [0, 0.15, 0.25, 0.35, 0.5, 9], "atrp": [0, 0.02, 0.03, 0.045, 9], "breadth": [0, 0.3, 0.45, 0.6, 1.01]}
        feats = {}
        for f, edges in bins.items():
            rows = []
            for lo, hi in zip(edges[:-1], edges[1:]):
                es = [e for e in ev_px if e["k"] == "hit" and e["_rn"] is not None and (e["f"].get(f) is not None) and lo <= e["f"][f] < hi]
                if len(es) >= 30:
                    rows.append({"von": lo, "bis": hi, **rs(es)})
            feats[f] = rows
        out["features_hits"] = feats
        sc = []
        for lo, hi in ((0, 40), (40, 55), (55, 70), (70, 85), (85, 101)):
            es = [e for e in ev_px if e["k"] == "hit" and e["_rn"] is not None and lo <= (e.get("score") or 0) < hi]
            if len(es) >= 30:
                sc.append({"von": lo, "bis": hi, **rs(es)})
        out["score_bins"] = sc
    for e in ev_px:
        e.pop("_rn", None)
    return out


def _week(d):
    import datetime as dt
    y, w, _ = dt.date.fromisoformat(d).isocalendar()
    return f"{y}-{w:02d}"


def main(argv=None) -> int:
    files = argv if argv is not None else sys.argv[1:]
    ev_all, seen = [], set()
    for p in files:
        for e in json.loads(Path(p).read_text()):
            k = (e["t"], e["d"], e["k"])
            if k not in seen:
                seen.add(k)
                ev_all.append(e)
    ev_px = [e for e in ev_all if e.get("px") and e["k"] in ("hit", "fast")]
    res = {"n_events": len(ev_all), "n_px": len(ev_px), "period": [min(e["d"] for e in ev_all), max(e["d"] for e in ev_all)]}
    wk = defaultdict(list)
    for e in ev_all:
        if e["k"] == "base" and (e.get("f") or {}).get("e200") is not None:
            wk[_week(e["d"])].append(e["f"]["e200"] > 0)
    breadth = {w: float(np.mean(v)) for w, v in wk.items() if len(v) >= 20}
    for e in ev_px:
        e["_br"] = breadth.get(_week(e["d"]))
    res["entry"] = entry_part(ev_all, ev_px)
    res["exit"] = exit_part(ev_px)
    (ROOT / "data" / "optimize.json").write_text(json.dumps(res, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print("OPTIMIZE " + json.dumps(res, ensure_ascii=False, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
