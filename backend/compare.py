"""Vergleich zweier Parameter-Sätze auf dem Kurs-Cache (ohne neue Downloads).

Bewertet jede Aktie aus dem Universum einmal mit der aktuellen config.yaml und einmal mit
geänderten Werten und zeigt, wie sich Treffer / Fast-Treffer verändern.

Aufruf:  python -m backend.compare rsi.t1_min_gap=10 rsi.pivot_len=3
"""

from __future__ import annotations

import copy
import sqlite3
import sys

import pandas as pd

from .config import CONFIG
from .data_provider import CACHE_PATH
from .scanner import evaluate
from .universe import load as load_universe


def _override(cfg, assignments: list[str]):
    cfg = copy.deepcopy(cfg)
    for a in assignments:
        path, val = a.split("=", 1)
        *parents, leaf = path.split(".")
        obj = cfg
        for p in parents:
            obj = getattr(obj, p)
        old = getattr(obj, leaf)
        setattr(obj, leaf, type(old)(float(val)) if isinstance(old, (int, float)) else val)
    return cfg


def _status(res) -> str:
    return "Treffer" if res.passed else "Fast-Treffer" if res.fast_hit else "–"


def main(argv=None) -> int:
    alt = _override(CONFIG, argv if argv is not None else sys.argv[1:])
    label = " ".join(argv if argv is not None else sys.argv[1:])
    uni = load_universe()
    meta = {r["ticker"]: r for r in uni.to_dict("records")}
    counts = {"neu": {"Treffer": 0, "Fast-Treffer": 0}, "alt": {"Treffer": 0, "Fast-Treffer": 0}}
    changes = []
    with sqlite3.connect(CACHE_PATH) as con:
        for t, m in meta.items():
            rows = con.execute("SELECT date, open, high, low, close, volume FROM bars WHERE ticker=? ORDER BY date",
                               (t,)).fetchall()
            if len(rows) < CONFIG.history.min_bars:
                continue
            df = pd.DataFrame(rows, columns=["Date", "Open", "High", "Low", "Close", "Volume"])
            df = df.set_index(pd.to_datetime(df.pop("Date"))).iloc[-504:]
            info = {"currency": m.get("currency"), "market_cap_usd": m.get("market_cap_usd")}
            try:
                new, old = evaluate(df, info, CONFIG, t), evaluate(df, info, alt, t)
            except Exception:
                continue
            for k, r in (("neu", new), ("alt", old)):
                if _status(r) != "–":
                    counts[k][_status(r)] += 1
            if _status(new) != _status(old):
                div = (new.flags.get("divergence") or {})
                changes.append((t, m.get("name", ""), _status(old), _status(new),
                                f"{div.get('kind', '')} {div.get('t1', '')} → {div.get('t2', '')}".strip()))
    print(f"# Vergleich: aktuelle config.yaml (neu) gegen alt = {label}\n")
    print("| | Treffer | Fast-Treffer |\n|---|---|---|")
    for k in ("alt", "neu"):
        print(f"| {k} | {counts[k]['Treffer']} | {counts[k]['Fast-Treffer']} |")
    print(f"\n{len(changes)} Aktien ändern ihren Status:\n")
    print("| Ticker | Name | alt | neu | Divergenz (neu) |\n|---|---|---|---|---|")
    order = {"Treffer": 0, "Fast-Treffer": 1, "–": 2}
    for c in sorted(changes, key=lambda c: (order[c[3]], c[0])):
        print("| " + " | ".join(str(x) for x in c) + " |")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
