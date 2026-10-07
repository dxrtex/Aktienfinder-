"""Push-Mitteilungen aufs iPad nach jedem Scan (Web Push, siehe webpush.py).

Einrichtung (einmalig): In der App unter Einstellungen → Mitteilungen aktivieren, den angezeigten Code kopieren und als
GitHub-Secret PUSH_SUBS speichern; zusätzlich VAPID_PRIVATE_KEY. Der Code enthält das Abo des Geräts und – optional –
Merkliste und Depot (Basiswert, Richtung, K.-o.) für persönliche Hinweise. Er liegt nur in den Secrets, nie im Repo.
"""

from __future__ import annotations

import json
import os

from . import webpush

_OWNER, _, _NAME = os.environ.get("GITHUB_REPOSITORY", "dxrtex/Kairo").partition("/")
APP = f"https://{_OWNER.lower()}.github.io/{_NAME}/"


def _num(x) -> str:
    return "–" if x is None else f"{x:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _pct(x: float) -> str:
    return f"{x * 100:.1f} %".replace(".", ",")


def messages(rows: list[dict], last: dict, market: dict, events: list[dict], search: dict, dev: dict) -> list[dict]:
    """Höchstens 3 kurze Mitteilungen: Depot-Warnung, deine Aktien, Abendbericht."""
    by = {r["ticker"]: r for r in rows}
    fav, depot = set(dev.get("m") or []), dev.get("d") or []
    mine = fav | {r["ticker"] for r in rows if r.get("in_watchlist")} | {d.get("t") for d in depot}
    prev_hit, prev_tr = set(last.get("hit", [])), set(last.get("trend", []))
    out = []
    # 1) Depot: K.-o. nah
    warn = []
    for d in depot:
        s = search.get(d.get("t"))
        if not s or not d.get("ko") or not s.get("c"):
            continue
        dist = (s["c"] - d["ko"]) / s["c"] if d.get("dir", "long") == "long" else (d["ko"] - s["c"]) / s["c"]
        if dist < 0.08:
            warn.append((dist, f"{s.get('n') or d['t']}: nur {_pct(dist)} bis K.-o. {_num(d['ko'])}"))
    if warn:
        warn.sort()
        out.append({"title": "⚠️ K.-o. nah" if len(warn) == 1 else f"⚠️ {len(warn)} Turbos nah am K.-o.",
                    "body": "\n".join(t for _, t in warn[:4]), "url": APP + "?sec=depot", "tag": "kairo-ko"})
    # 2) Deine Aktien: neu Treffer / Trend-Rücksetzer, Termine morgen
    lines = []
    for t in sorted(mine):
        r = by.get(t)
        if not r:
            continue
        n = (r.get("name") or t)[:28]
        if r["passed"] and t not in prev_hit:
            lines.append(f"🟢 {n} ist jetzt Treffer · Score {r['score']}")
        elif (r.get("tr") or {}).get("ok") and t not in prev_tr:
            chk = (r["tr"].get("chk") or {}).get("p")
            lines.append(f"↗️ {n}: Trend-Rücksetzer{' Top' if r['tr'].get('top') else ''}" + (f" · Check {chk * 100:.0f} %" if chk is not None else ""))
    for ev in events:
        if ev.get("days") == 1 and ev.get("ticker") in mine and ev.get("kind") == "earnings":
            lines.append(f"📅 morgen Quartalszahlen: {(ev.get('name') or ev['ticker'])[:28]}")
    if lines:
        out.append({"title": "Deine Aktien", "body": "\n".join(lines[:5]) + (f"\n+ {len(lines) - 5} weitere" if len(lines) > 5 else ""),
                    "url": APP + "?sec=today", "tag": "kairo-mine"})
    # 3) Abendbericht: neue Treffer und Trend-Top
    hits = [r for r in rows if r["passed"]]
    new_hits = sorted([r for r in hits if r["ticker"] not in prev_hit], key=lambda r: -r["score"])
    new_top = [r for r in rows if (r.get("tr") or {}).get("top") and r["ticker"] not in prev_tr]
    macro = [ev for ev in events if ev.get("days") == 1 and ev.get("kind") == "macro"]
    if new_hits or new_top or macro:
        reg = (market.get("regime") or {}).get("label")
        parts = []
        if new_hits:
            parts.append(f"{len(new_hits)} neue Treffer: " + ", ".join((r.get("name") or r["ticker"])[:18] for r in new_hits[:3]))
        if new_top:
            parts.append(f"{len(new_top)} neue Trend Top: " + ", ".join((r.get("name") or r["ticker"])[:18] for r in new_top[:3]))
        if macro:
            parts.append("Morgen: " + ", ".join(ev.get("title", "") for ev in macro[:2]))
        out.append({"title": f"🌙 Kairo · {len(hits)} Treffer" + (f" · {reg}" if reg else ""), "body": "\n".join(parts),
                    "url": APP + "?sec=today", "tag": "kairo-report"})
    return out


def run(rows, market, calendar_events, search, last: dict, today_iso: str) -> dict:
    raw, key = os.environ.get("PUSH_SUBS"), os.environ.get("VAPID_PRIVATE_KEY")
    if not raw or not key:
        print("Push: nicht eingerichtet (Secrets PUSH_SUBS / VAPID_PRIVATE_KEY fehlen)")
        return {"enabled": False}
    try:
        devs = json.loads(raw)
        devs = devs if isinstance(devs, list) else [devs]
        k = webpush.private_key(key.strip())
    except Exception as exc:
        print(f"Push: Secret nicht lesbar ({exc!r})")
        return {"enabled": True, "ok": False}
    import numpy as np
    import pandas as pd
    today = pd.Timestamp(today_iso)
    evs = []
    for ev in calendar_events:
        try:
            evs.append({**ev, "days": int(np.busday_count(today.date(), pd.Timestamp(ev["date"]).date()))})
        except Exception:
            pass
    sent = failed = 0
    for dev in devs:
        sub = dev.get("s") or dev
        for msg in messages(rows, last, market, evs, search, dev):
            try:
                st = webpush.send(sub, msg, k)
                sent += st in (200, 201, 202)
                failed += st not in (200, 201, 202)
                if st not in (200, 201, 202):
                    print(f"Push: Status {st}" + (" – Abo abgelaufen, in der App neu aktivieren" if st in (404, 410) else ""))
            except Exception as exc:
                failed += 1
                print(f"Push: Fehler {exc!r}")
    print(f"Push: {sent} Mitteilungen gesendet, {failed} fehlgeschlagen, {len(devs)} Gerät(e)")
    return {"enabled": True, "ok": failed == 0, "sent": sent, "date": today_iso}
