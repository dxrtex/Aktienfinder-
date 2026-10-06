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
    tf = risk / max(entry - ko, 1e-6)              # R → Rendite des Turbos (Einsatz = Abstand Kurs bis K.-o.)
    out = lambda r, d, x: (r, d, x, max(-1.0, r * tf))
    for j in range(HOLD):
        oj = o[j] if j else entry
        if min(oj, l[j]) <= ko:
            return out(net((min(oj, ko) - entry) / risk, j + 1, rp), j + 1, "ko")
        if (not gate or c[j] > entry * (1 + min_gain)) and sum(sg[j][x] for x in crit) >= k:
            px_ = o[j + 1] if j + 1 < HOLD else c[j]
            return out(net((px_ - entry) / risk, j + 2, rp), j + 2, "sell")
    return out(net((c[HOLD - 1] - entry) / risk, HOLD, rp), HOLD, "time")


def summarize(rows):
    if not rows:
        return {"n": 0}
    r = np.array([x[0] for x in rows]); d = np.array([x[1] for x in rows])
    return {"n": len(rows), "r": round(float(r.mean()), 3), "win": round(float((r > 0).mean()), 3), "days": round(float(d.mean()), 1),
            "r_month": round(float(r.mean() / d.mean() * 21), 3), "ko": round(float(np.mean([x[2] == "ko" for x in rows])), 3),
            "p5": round(float(np.percentile(r, 5)), 2),
            "turbo": round(float(np.mean([x[3] for x in rows])), 3) if len(rows[0]) > 3 else None}


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
        # Fairer Vergleich: Treffer vs. zufällige Tage mit GLEICHER Volatilität / Korrektur / ATR %
        base = [e for e in ev_all if e["k"] == "base" and e.get("f")]
        hits = [e for e in ev_all if e["k"] == "hit" and e.get("f")]
        def m(es, k):
            v = [e[k] for e in es if e.get(k) is not None]
            return round(float(np.mean(v)), 4) if v else None
        matched = {}
        for f, edges in (("vol", [0, 0.25, 0.35, 0.5, 0.7, 9]), ("dd", [0, 0.15, 0.25, 0.35, 0.5, 9]), ("atrp", [0, 0.02, 0.03, 0.045, 9])):
            rows = []
            for lo, hi in zip(edges[:-1], edges[1:]):
                hb = [e for e in hits if e["f"].get(f) is not None and lo <= e["f"][f] < hi]
                bb = [e for e in base if e["f"].get(f) is not None and lo <= e["f"][f] < hi]
                if len(hb) >= 30 and len(bb) >= 30:
                    rows.append({"von": lo, "bis": hi, "n_hit": len(hb), "n_base": len(bb), "hit20": m(hb, "r20"), "base20": m(bb, "r20"),
                                 "hit63": m(hb, "r63"), "base63": m(bb, "r63")})
            matched[f] = rows
        out["matched"] = matched
        # Kandidaten-Filter auf die Treffer (Vorschläge für Stufen/Filter, kein Muss)
        rules = {"Vola ≥ 35 %": lambda f: (f.get("vol") or 0) >= 0.35, "ATR ≥ 3 %": lambda f: (f.get("atrp") or 0) >= 0.03,
                 "Rückgang ≥ 25 %": lambda f: (f.get("dd") or 0) >= 0.25, "Vola ≥ 35 % und Rückgang ≥ 20 %": lambda f: (f.get("vol") or 0) >= 0.35 and (f.get("dd") or 0) >= 0.2,
                 "ATR ≥ 3 % und Rückgang ≥ 20 %": lambda f: (f.get("atrp") or 0) >= 0.03 and (f.get("dd") or 0) >= 0.2,
                 "Kurs ≥ 10 % unter EMA 200": lambda f: (f.get("e200") or 0) <= -0.1, "Vola < 30 %": lambda f: (f.get("vol") or 1) < 0.3}
        cands = {}
        for name, fn in rules.items():
            es = [e for e in ev_px if e["k"] == "hit" and e["_rn"] is not None and fn(e.get("f") or {})]
            bs = [e for e in base if fn(e["f"])]
            yrs = max(1, len({e["d"][:4] for e in ev_all}) - 0.8)
            cands[name] = {**rs(es), "je_jahr": round(len(es) / yrs), "hit63": m([e for e in hits if fn(e["f"])], "r63"), "base63": m(bs, "r63")} if es else {"n": 0}
        out["candidates"] = cands
        # Überrendite: Rendite minus Ø der zufälligen Tage derselben Woche (Marktbewegung herausgerechnet)
        wk20, wk63 = defaultdict(list), defaultdict(list)
        for e in base:
            if e.get("r20") is not None: wk20[_week(e["d"])].append(e["r20"])
            if e.get("r63") is not None: wk63[_week(e["d"])].append(e["r63"])
        mw20 = {w: float(np.mean(v)) for w, v in wk20.items() if len(v) >= 20}
        mw63 = {w: float(np.mean(v)) for w, v in wk63.items() if len(v) >= 20}
        def ex(es):
            a = [e["r20"] - mw20[_week(e["d"])] for e in es if e.get("r20") is not None and _week(e["d"]) in mw20]
            b = [e["r63"] - mw63[_week(e["d"])] for e in es if e.get("r63") is not None and _week(e["d"]) in mw63]
            tr = [e["r63"] - mw63[_week(e["d"])] for e in es if e.get("r63") is not None and _week(e["d"]) in mw63 and e["d"] < SPLIT]
            te = [e["r63"] - mw63[_week(e["d"])] for e in es if e.get("r63") is not None and _week(e["d"]) in mw63 and e["d"] >= SPLIT]
            se = float(np.std(b) / np.sqrt(len(b))) if len(b) > 1 else None
            f = lambda v: round(float(np.mean(v)), 4) if v else None
            return {"n": len(b), "ex20": f(a), "ex63": f(b), "se63": round(se, 4) if se else None, "train63": f(tr), "test63": f(te)}
        out["excess"] = {"Treffer": ex(hits), **{g: ex(es) for g, es in groups.items() if g.startswith("Fast") and len(es) >= 300}}
        # Was sagt überhaupt künftige Überrendite voraus? (alle zufälligen Tage, nach Merkmal)
        study = {}
        for f, edges in (("e200", [-9, -0.3, -0.15, -0.05, 0.05, 0.15, 0.3, 9]), ("dd", [0, 0.05, 0.1, 0.2, 0.3, 0.5, 9]),
                         ("rsi", [0, 30, 40, 50, 60, 70, 100]), ("vol", [0, 0.25, 0.35, 0.5, 0.7, 9]), ("e50", [-9, -0.15, -0.05, 0, 0.05, 0.15, 9])):
            rows = []
            for lo, hi in zip(edges[:-1], edges[1:]):
                es = [e for e in base if e["f"].get(f) is not None and lo <= e["f"][f] < hi]
                if len(es) >= 200:
                    rows.append({"von": lo, "bis": hi, **ex(es)})
            study[f] = rows
        out["base_study"] = study
        # Alternative Setup-Ideen auf allen Vergleichstagen: hätte eine andere Einstiegsart Überrendite gebracht?
        alt = {"Rücksetzer im Aufwärtstrend (EMA200 +10 %, Kurs −8…0 % unter EMA50, RSI 35–50)":
                   lambda f: (f.get("e200") or -9) >= 0.10 and -0.08 <= (f.get("e50") or 9) <= 0 and 35 <= (f.get("rsi") or 0) <= 50,
               "Starker Trend (EMA200 +15 %, EMA50 +5 %)": lambda f: (f.get("e200") or -9) >= 0.15 and (f.get("e50") or -9) >= 0.05,
               "Trend + überverkauft (EMA200 +20 %, RSI < 45)": lambda f: (f.get("e200") or -9) >= 0.20 and (f.get("rsi") or 99) < 45,
               "Tief gefallen (EMA200 −30 %)": lambda f: (f.get("e200") or 9) <= -0.30,
               "Volatil + Trend (Vola ≥ 50 %, EMA200 +10 %)": lambda f: (f.get("vol") or 0) >= 0.5 and (f.get("e200") or -9) >= 0.10,
               "Kairo-ähnlich (Rückgang ≥ 12 %, unter EMA50, RSI 28–48)": lambda f: (f.get("dd") or 0) >= 0.12 and (f.get("e50") or 9) < 0 and 28 <= (f.get("rsi") or 0) <= 48}
        out["alt_setups"] = {k: {**ex([e for e in base if fn(e["f"])]),
                                 "je_jahr_je_1000": round(len([e for e in base if fn(e["f"])]) / max(1, len(base)) * 1000, 1)} for k, fn in alt.items()}
    for e in ev_px:
        e.pop("_rn", None)
    return out


ALL15 = ["cap", "liquidity", "price", "history"] + KEYS


def _var_ok(e, key, test):
    """Wäre das Signal mit einer anderen Schwelle für `key` ein Treffer? (übrige Kriterien wie gemessen)"""
    ok = (e.get("f") or {}).get("ok")
    raw = (e.get("f") or {}).get("raw") or {}
    if not ok or len(ok) != 15:
        return None
    for i, k in enumerate(ALL15):
        if k == key:
            v = test(e["f"], raw)
            if v is None:
                return None
            if not v:
                return False
        elif ok[i] != "1":
            return False
    return True


# Schwellen-Varianten je Kriterium (None = Kriterium weglassen). Basis = heutige Einstellung.
def _rng(lo, hi):
    return lambda f, r: f.get("rsi") is not None and lo <= f["rsi"] <= hi
SWEEP = {
    "drawdown": {f"Rückgang ≥ {int(x * 100)} %": (lambda x: lambda f, r: r.get("dd") is not None and r["dd"] >= x)(x) for x in (0.08, 0.10, 0.12, 0.15, 0.20, 0.25)},
    "no_crash": {**{f"max. Tagesverlust > −{int(x * 100)} %": (lambda x: lambda f, r: r.get("worst") is not None and r["worst"] > -x)(x) for x in (0.10, 0.15, 0.25)}, "weglassen": lambda f, r: True},
    "structure": {"weglassen": lambda f, r: True},
    "zone": {"weglassen": lambda f, r: True},
    "flattening": {**{f"Spanne < {x} × Grenze oder Lunten": (lambda x: lambda f, r: r.get("flat") is not None and (r["flat"] < x or (r.get("wicks") or 0) >= 2))(x) for x in (0.7, 0.85, 1.0, 1.2, 1.5)}, "weglassen": lambda f, r: True},
    "rsi_div": {"weglassen": lambda f, r: True},
    "rsi_range": {"RSI 28–48 (heute)": _rng(28, 48), "RSI 25–45": _rng(25, 45), "RSI 28–40": _rng(28, 40), "RSI 30–52": _rng(30, 52),
                  "RSI 28–55": _rng(28, 55), "RSI 20–48": _rng(20, 48), "weglassen": lambda f, r: True},
    "macd_below0": {"weglassen": lambda f, r: True},
    "macd_turn": {"weglassen": lambda f, r: True},
    "mbi": {**{f"grünes X ≤ {x} T. (sonst wie heute)": (lambda x: lambda f, r: None if r.get("mbi_age") is None else
                (r["mbi_age"] <= x and (r.get("mbi_ref") or 0) > 1 and ((r.get("mbi_fade") or 9) <= 0.7 or r.get("mbi_green")))) (x) for x in (10, 15, 20, 30)},
            "weglassen": lambda f, r: True},
    "crv": {**{f"CRV ≥ {x}": (lambda x: lambda f, r: f.get("crv") is not None and f["crv"] >= x)(x) for x in (1.5, 2.0, 2.5, 3.0, 4.0)}, "weglassen": lambda f, r: True},
}


def _dedupe(es):
    from .bilanz import GAP
    import datetime as dt
    out, last = [], {}
    for e in sorted(es, key=lambda e: (e["t"], e["d"])):
        d = dt.date.fromisoformat(e["d"])
        if e["t"] in last and (d - last[e["t"]]).days <= GAP + 2:
            last[e["t"]] = d
            continue
        last[e["t"]] = d
        out.append(e)
    return out


def sweep_part(ev_px):
    """Je Kriterium und Schwelle: Anzahl Signale und Ergebnis (TP 2 netto, Halten netto, Rendite 20/63 T.)."""
    tp2 = {n: r for n, _, r in RULES}["TP 2 – zweites relevantes Hoch"]
    for e in ev_px:
        if "_tp2" not in e:
            x = simulate(e["px"], tp2, "close", 1.0)
            e["_tp2"] = net(x["r"], x["d"], x["rp"]) if x else None
            y = sim(e["px"], [{}] * HOLD, [], 1, True) if len(e["px"]["c"]) >= HOLD else None
            e["_hold"] = y[0] if y else None
    def stats(es):
        es = _dedupe(es)
        a = [e["_tp2"] for e in es if e["_tp2"] is not None]
        hd = [e["_hold"] for e in es if e["_hold"] is not None]
        tr = [e["_tp2"] for e in es if e["_tp2"] is not None and e["d"] < SPLIT]
        te = [e["_tp2"] for e in es if e["_tp2"] is not None and e["d"] >= SPLIT]
        r63 = [e["r63"] for e in es if e.get("r63") is not None]
        f = lambda v: round(float(np.mean(v)), 3) if v else None
        return {"n": len(es), "tp2": f(a), "hold": f(hd), "train": f(tr), "test": f(te), "ret63": f(r63)}
    cand = [e for e in ev_px if (e.get("f") or {}).get("ok")]
    out = {"heute": stats([e for e in cand if e["k"] == "hit"])}
    for key, vs in SWEEP.items():
        out[key] = {name: stats([e for e in cand if _var_ok(e, key, fn)]) for name, fn in vs.items()}
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
    if any((e.get("f") or {}).get("raw") for e in ev_px):
        res["sweep"] = sweep_part(ev_px)
    res["exit"] = exit_part(ev_px)
    (ROOT / "data" / "optimize.json").write_text(json.dumps(res, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    # Ausgabe in Abschnitten (das Wichtigste zuletzt – so lässt es sich gezielt aus dem Protokoll lesen)
    dump = lambda name, obj: print(f"OPT_{name} " + json.dumps(obj, ensure_ascii=False, separators=(",", ":")))
    dump("exit", res["exit"])
    dump("entry", {k: v for k, v in res["entry"].items() if k not in ("alt_setups", "excess")})
    if "sweep" in res:
        dump("sweep", res["sweep"])
    dump("key", {"excess": res["entry"].get("excess"), "alt": res["entry"].get("alt_setups")})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
