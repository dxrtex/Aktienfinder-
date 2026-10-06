"""Ausstiegs-Backtest: Welche Verkaufsregel holt aus den Kairo-Signalen am meisten heraus?

Jedes Signal (Treffer und Fast-Treffer) bringt seinen Kursverlauf der folgenden 63 Handelstage mit (bilanz.py, "px").
Daran wird jede Regel durchgespielt – realistisch:
- Einstieg am nächsten Morgen zur Eröffnung (das Signal kennt man erst nach dem Abend-Scan).
  Liegt die Eröffnung schon unter dem Stop, gibt es keinen Trade.
- Stop: Eröffnet die Aktie darunter (Kurslücke), wird zur Eröffnung verkauft – nicht zum Stop-Kurs.
- Ziele: Eröffnet sie darüber, wird zur Eröffnung verkauft. Stop und Ziel am selben Tag = Stop (vorsichtig).
- Höchstens 3 Monate (63 Tage), dann zum Schlusskurs.
Ergebnis in R (Gewinn/Verlust ÷ Risiko bis zum Stop) und R je Monat Haltedauer.
Lernen (Signale bis Ende 2025) / Prüfen (ab 2026) getrennt – eine Regel muss in beiden Teilen gut sein.
Zusätzlich: wie oft eine Kurslücke unter den K.-o. eines Turbos fiel (K.-o. = Stop − ½ ATR).

Aufruf: python -m backend.exits bilanz_part_*.json
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np

from .config import ROOT

PATH = ROOT / "data" / "exit_backtest.json"
SPLIT = "2026-01-01"
HOLD = 63

# Regel: target = ("t1"|"t2"|"tp1"|"tp2"|"tp3"|"R", x)|("turbo",)|None; be = Aktivierung in R (Stop auf Einstand);
# trail = ("chand", k ATR)|("ema",)|("low", n Tage), ab trail_from R; partial = (Anteil, target); time = (Tage, Mindest-R)
RULES = [
    ("Ziel 1 (EMA 50 / Fib 0,382)", "base", {"target": ("t1",)}),
    ("TP 1 – nächstes relevantes Hoch", "base", {"target": ("tp1",)}),
    ("TP 2 – zweites relevantes Hoch", "base", {"target": ("tp2",)}),
    ("Swing-High (Ziel 2)", "base", {"target": ("t2",)}),
    ("Festes Ziel 1 R", "r", {"target": ("R", 1.0)}),
    ("Festes Ziel 1,5 R", "r", {"target": ("R", 1.5)}),
    ("Festes Ziel 2 R", "r", {"target": ("R", 2.0)}),
    ("Festes Ziel 3 R", "r", {"target": ("R", 3.0)}),
    ("Turbo +100 % (Hebel nach Stop-Abstand)", "r", {"target": ("turbo",)}),
    ("TP 1 + Stop auf Einstand ab 1 R", "be", {"target": ("tp1",), "be": 1.0}),
    ("TP 2 + Stop auf Einstand ab 1 R", "be", {"target": ("tp2",), "be": 1.0}),
    ("Swing-High + Stop auf Einstand ab 1 R", "be", {"target": ("t2",), "be": 1.0}),
    ("Nachziehen: 3 ATR unter Hoch, ab 1 R", "trail", {"trail": ("chand", 3.0), "trail_from": 1.0, "be": 1.0}),
    ("Nachziehen: 2 ATR unter Hoch, ab 1 R", "trail", {"trail": ("chand", 2.0), "trail_from": 1.0, "be": 1.0}),
    ("Nachziehen: Schluss unter EMA 20, ab 1 R", "trail", {"trail": ("ema",), "trail_from": 1.0, "be": 1.0}),
    ("Nachziehen: 10-Tage-Tief, ab 1 R", "trail", {"trail": ("low", 10), "trail_from": 1.0, "be": 1.0}),
    ("Nachziehen: 3 ATR unter Hoch, sofort", "trail", {"trail": ("chand", 3.0), "trail_from": 0.0}),
    ("Hälfte an TP 1, Rest 3 ATR nachziehen", "mix", {"partial": (0.5, ("tp1",)), "trail": ("chand", 3.0), "trail_from": 1.0, "be_after_partial": True}),
    ("Hälfte an TP 1, Rest bis TP 2", "mix", {"partial": (0.5, ("tp1",)), "target": ("tp2",), "be_after_partial": True}),
    ("Hälfte an 1,5 R, Rest 3 ATR nachziehen", "mix", {"partial": (0.5, ("R", 1.5)), "trail": ("chand", 3.0), "trail_from": 1.0, "be_after_partial": True}),
    ("Hälfte an TP 1, Rest Schluss unter EMA 20", "mix", {"partial": (0.5, ("tp1",)), "trail": ("ema",), "trail_from": 1.0, "be_after_partial": True}),
    # Ausstieg mit den Kairo-Indikatoren (Gegenstück zum Einstieg): Verkauf zum Schlusskurs am Signaltag
    ("RSI über 70 (überkauft)", "ind", {"sig": ["rsi70"]}),
    ("MACD dreht nach unten (Histogramm unter 0)", "ind", {"sig": ["macd"]}),
    ("MBI rotes X (Kaufdruck lässt nach)", "ind", {"sig": ["mbi"]}),
    ("TP 1 oder RSI über 70 – was zuerst kommt", "ind", {"target": ("tp1",), "sig": ["rsi70"]}),
    ("Swing-High oder MACD dreht – was zuerst kommt", "ind", {"target": ("t2",), "sig": ["macd"], "be": 1.0}),
    ("Hälfte an TP 1, Rest bis MACD dreht", "mix", {"partial": (0.5, ("tp1",)), "sig": ["macd"], "be_after_partial": True}),
    ("Hälfte an TP 1, Rest bis MBI rotes X", "mix", {"partial": (0.5, ("tp1",)), "sig": ["mbi"], "be_after_partial": True}),
    # An TP 1 nur verkaufen, wenn das Momentum ausgereizt ist – sonst weiterlaufen lassen (Stop sichert die halbe Strecke bis TP 1)
    ("TP 1 – bei RSI unter 60 weiter bis TP 2", "hold", {"target": ("tp1",), "hold": {"rsi_lt": 60, "next": ("tp2",)}}),
    ("TP 1 – bei RSI unter 70 weiter bis TP 2", "hold", {"target": ("tp1",), "hold": {"rsi_lt": 70, "next": ("tp2",)}}),
    ("TP 1 – bei RSI unter 60 weiter, 3 ATR nachziehen", "hold", {"target": ("tp1",), "hold": {"rsi_lt": 60, "trail": ("chand", 3.0)}}),
    ("TP 1 – bei steigendem MACD weiter bis TP 2", "hold", {"target": ("tp1",), "hold": {"macd_up": True, "next": ("tp2",)}}),
    ("TP 1 + Zeit-Stop (10 T. kein Plus)", "time", {"target": ("tp1",), "time": (10, 0.0)}),
    ("TP 1 + Zeit-Stop (20 T. unter 0,5 R)", "time", {"target": ("tp1",), "time": (20, 0.5)}),
    ("Hälfte TP 1, Rest 3 ATR + Zeit-Stop 20 T.", "mix", {"partial": (0.5, ("tp1",)), "trail": ("chand", 3.0), "trail_from": 1.0,
                                                          "be_after_partial": True, "time": (20, 0.5)}),
]


def _level(spec, px: dict, entry: float, risk: float):
    """Zielkurs (relativ zum Schluss am Signaltag) aus der Regel."""
    if not spec:
        return None
    k = spec[0]
    if k == "R":
        return entry + spec[1] * risk
    if k == "turbo":                               # K.-o. ½ ATR unter dem Stop → Turbo verdoppelt sich bei +(Entry − K.-o.)
        ko = px["s"] - 0.5 * px["atr"]
        return entry + (entry - ko)
    if k in ("t1", "t2"):
        v = px.get(k)
    else:
        idx = int(k[2]) - 1
        v = px["tp"][idx] if len(px.get("tp") or []) > idx else None
    return v if v and v > entry else None


def simulate(px: dict, rule: dict) -> dict | None:
    o, h, l, c = px["o"], px["h"], px["l"], px["c"]
    if len(c) < HOLD or not o:
        return None                                # Verlauf noch nicht vollständig
    entry, stop0 = o[0], px["s"]
    if entry <= stop0:
        return None                                # Eröffnung schon unter dem Stop – kein Trade
    risk = entry - stop0
    R = lambda x: (x - entry) / risk
    target = _level(rule.get("target"), px, entry, risk)
    part = rule.get("partial")
    ptarget = _level(part[1], px, entry, risk) if part else None
    stop, pos, real, maxh = stop0, 1.0, 0.0, entry
    ema, alpha = px["e20"], 2 / 21
    lows = list(px["pl"])
    ko = px["s"] - 0.5 * px["atr"]
    macd_pos = (px.get("mh0") or 0) > 0          # „dreht nach unten“ erst, nachdem das Histogramm positiv war
    held, trail_override = False, None
    for j in range(len(c)):
        oj = o[j] if j else entry
        # 1) Stop (mit Kurslücke)
        # gko: Am Tag des Stops fiel das Tief bis unter den K.-o. – ohne Stop-Order wäre der Turbo ausgeknockt
        if oj <= stop:
            return {"r": real + pos * R(oj), "d": j + 1, "x": "stop" if stop < entry else "be/trail", "gko": stop == stop0 and l[j] <= ko, "rp": risk / entry}
        if l[j] <= stop:
            return {"r": real + pos * R(stop), "d": j + 1, "x": "stop" if stop < entry else "be/trail", "gko": stop == stop0 and l[j] <= ko, "rp": risk / entry}
        # 2) Teilverkauf und Ziel
        if ptarget and pos == 1.0 and h[j] >= ptarget:
            px_ = max(oj, ptarget)
            real += part[0] * R(px_)
            pos -= part[0]
            if rule.get("be_after_partial"):
                stop = max(stop, entry)
        if target and h[j] >= target:
            hd = rule.get("hold")
            if hd and not held:
                rsi, mh = px.get("rsi") or [], px.get("mh") or []
                strong = (("rsi_lt" in hd and j < len(rsi) and rsi[j] < hd["rsi_lt"])
                          or (hd.get("macd_up") and 0 < j < len(mh) and mh[j] > mh[j - 1]))
                if strong:                         # Momentum noch nicht ausgereizt → nicht verkaufen
                    held = True
                    stop = max(stop, entry + 0.5 * (target - entry))
                    target = _level(hd["next"], px, entry, risk) if hd.get("next") else None
                    if target is not None and target <= h[j]:
                        target = None
                    if hd.get("trail"):
                        trail_override = hd["trail"]
                else:
                    return {"r": real + pos * R(max(oj, target)), "d": j + 1, "x": "ziel", "gko": False, "rp": risk / entry}
            else:
                return {"r": real + pos * R(max(oj, target)), "d": j + 1, "x": "ziel", "gko": False, "rp": risk / entry}
        # 3) Nachziehen (gilt ab dem nächsten Tag)
        maxh = max(maxh, h[j])
        mfe = R(maxh)
        ema = ema + alpha * (c[j] - ema)
        lows.append(l[j])
        if rule.get("be") is not None and mfe >= rule["be"]:
            stop = max(stop, entry)
        tr = trail_override or rule.get("trail")
        if tr and (trail_override or mfe >= rule.get("trail_from", 0)):
            if tr[0] == "chand":
                stop = max(stop, maxh - tr[1] * px["atr"])
            elif tr[0] == "low":
                stop = max(stop, min(lows[-tr[1]:]))
            elif tr[0] == "ema" and c[j] < ema:
                return {"r": real + pos * R(c[j]), "d": j + 1, "x": "trail", "gko": False, "rp": risk / entry}
        # Indikator-Signale (Schlusskurs)
        sg = rule.get("sig")
        if sg:
            mh = px.get("mh") or []
            if j < len(mh) and mh[j] > 0:
                macd_pos = True
            hit = (("rsi70" in sg and j < len(px.get("rsi") or []) and px["rsi"][j] >= 70)
                   or ("macd" in sg and macd_pos and j < len(mh) and mh[j] < 0)
                   or ("mbi" in sg and j < len(px.get("rx") or []) and px["rx"][j]))
            if hit:
                return {"r": real + pos * R(c[j]), "d": j + 1, "x": "signal", "gko": False, "rp": risk / entry}
        # 4) Zeit-Stop
        tm = rule.get("time")
        if tm and j + 1 == tm[0] and R(c[j]) < tm[1]:
            return {"r": real + pos * R(c[j]), "d": j + 1, "x": "zeit", "gko": False, "rp": risk / entry}
    return {"r": real + pos * R(c[-1]), "d": len(c), "x": "3 Mon.", "gko": False, "rp": risk / entry}


# Geschätzte Turbo-Kosten, umgerechnet auf den Basiswert: Spread ~0,1 % (Kauf + Verkauf) und Finanzierung ~4 % p. a.
SPREAD, FIN_DAY = 0.001, 0.04 / 252


def _summ(res: list[dict]) -> dict:
    if not res:
        return {"n": 0}
    r = np.array([x["r"] for x in res])
    d = np.array([x["d"] for x in res])
    net = r - np.array([(SPREAD + FIN_DAY * x["d"]) / max(x["rp"], 1e-4) for x in res])
    wins, losses = r[r > 0], r[r <= 0]
    return {"n": len(res), "avg_r": round(float(r.mean()), 3), "med_r": round(float(np.median(r)), 3),
            "win": round(float((r > 0).mean()), 3), "avg_win": round(float(wins.mean()), 3) if len(wins) else None,
            "avg_loss": round(float(losses.mean()), 3) if len(losses) else None,
            "days": round(float(d.mean()), 1), "r_month": round(float(r.mean() / d.mean() * 21), 3),
            "exits": {k: round(sum(x["x"] == k for x in res) / len(res), 3) for k in ("ziel", "stop", "be/trail", "trail", "signal", "zeit", "3 Mon.")},
            "worst5": round(float(np.percentile(r, 5)), 2),
            "avg_r_net": round(float(net.mean()), 3), "r_month_net": round(float(net.mean() / d.mean() * 21), 3)}


def run(events: list[dict]) -> dict:
    sig = [e for e in events if e.get("px") and e["k"] in ("hit", "fast")]
    out = {"generated": time.strftime("%Y-%m-%d"), "split": SPLIT, "rules": []}
    gaps = []
    for name, fam, rule in RULES:
        row = {"name": name, "fam": fam}
        sims = [(e, simulate(e["px"], rule)) for e in sig]
        sims = [(e, x) for e, x in sims if x]
        if name == "TP 1 – nächstes relevantes Hoch":
            gaps = [x["gko"] for e, x in sims if x["x"] == "stop"]
        row["years"] = {y: _summ([x for e, x in sims if e["d"][:4] == y]) for y in sorted({e["d"][:4] for e, _ in sims})}
        for part, sel in (("all", lambda e: True), ("train", lambda e: e["d"] < SPLIT), ("test", lambda e: e["d"] >= SPLIT)):
            for kind in ("hit", "all"):
                row[f"{part}_{kind}"] = _summ([x for e, x in sims if sel(e) and (kind == "all" or e["k"] == "hit")])
        out["rules"].append(row)
    out["ko_on_stop"] = round(float(np.mean(gaps)), 4) if gaps else None   # Anteil der Stop-Tage, an denen der K.-o. getroffen wurde
    # Robuste Empfehlung: in Lernen UND Prüfen unter den besten 3 (Treffer + Fast-Treffer, R je Trade)
    rk = lambda part, key: {r["name"]: i for i, r in enumerate(sorted(out["rules"], key=lambda r: -(r[f"{part}_all"].get(key) or -9)))}
    tr, te = rk("train", "avg_r"), rk("test", "avg_r")
    out["robust"] = sorted(out["rules"], key=lambda r: max(tr[r["name"]], te[r["name"]]))[0]["name"]
    trm, tem = rk("train", "r_month"), rk("test", "r_month")
    out["robust_month"] = sorted(out["rules"], key=lambda r: max(trm[r["name"]], tem[r["name"]]))[0]["name"]
    return out


def main(argv=None) -> int:
    files = argv if argv is not None else sys.argv[1:]
    ev, seen = [], set()
    for p in files:
        for e in json.loads(Path(p).read_text()):
            key = (e["t"], e["d"], e["k"])
            if key not in seen:
                seen.add(key)
                ev.append(e)
    res = run(ev)
    PATH.write_text(json.dumps(res, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    compact = {"robust": res["robust"], "robust_month": res["robust_month"], "ko_on_stop": res["ko_on_stop"],
               "rules": [{"name": r["name"], **{k: {kk: r[k].get(kk) for kk in ("n", "avg_r", "avg_r_net", "win", "days", "r_month", "r_month_net", "worst5")}
                                                 for k in ("all_all", "all_hit", "train_all", "test_all")},
                          "years": {y: [v.get("n"), v.get("avg_r"), v.get("avg_r_net")] for y, v in r["years"].items()}} for r in res["rules"]]}
    print("EXITS " + json.dumps(compact, ensure_ascii=False, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
