"""Telegram-Alarme: Abendbericht nach jedem Scan.

Einrichtung (einmalig): Bot bei @BotFather anlegen, Token als GitHub-Secret TELEGRAM_TOKEN speichern, dem Bot
„/start“ schreiben. Der erste Chat, der /start sendet, wird gespeichert (oder fest per Secret TELEGRAM_CHAT).
Die App schickt Merkliste und Depot als Nachricht „/sync …“ an den Bot; der nächste Scan liest sie (getUpdates).

/sync-Format:  /sync M=UBER,IFX.DE;D=UBER:long:54.76,IFX.DE:long:45.17
"""

from __future__ import annotations

import html
import os
import re
import time

import requests

from . import state

API = "https://api.telegram.org/bot{token}/{method}"
APP = "https://dxrtex.github.io/Aktienfinder-/"


def _call(token: str, method: str, **params):
    for attempt in range(3):
        try:
            r = requests.post(API.format(token=token, method=method), json=params, timeout=20)
            j = r.json()
            if j.get("ok"):
                return j.get("result")
            print(f"Telegram {method}: {j.get('description')}")
            return None
        except Exception as exc:
            print(f"Telegram {method}: Fehler {exc!r}")
            time.sleep(2 * (attempt + 1))
    return None


def parse_sync(text: str) -> dict:
    out = {"fav": [], "depot": []}
    body = text.split(None, 1)[1] if " " in text else ""
    for part in body.split(";"):
        if "=" not in part:
            continue
        k, v = part.split("=", 1)
        items = [x.strip() for x in v.split(",") if x.strip()]
        if k.strip().upper() == "M":
            out["fav"] = [re.sub(r"[^A-Za-z0-9.\-^=]", "", x)[:20] for x in items][:300]
        elif k.strip().upper() == "D":
            for x in items[:100]:
                f = x.split(":")
                if not f[0]:
                    continue
                e = {"t": re.sub(r"[^A-Za-z0-9.\-]", "", f[0])[:20]}
                if len(f) >= 3:
                    try:
                        e.update(dir="short" if f[1].lower().startswith("s") else "long", ko=float(f[2]))
                    except ValueError:
                        pass
                out["depot"].append(e)
    return out


def read_updates(token: str, tg: dict) -> None:
    """Neue Bot-Nachrichten verarbeiten: /start (Chat merken), /sync (Merkliste/Depot)."""
    ups = _call(token, "getUpdates", offset=tg.get("offset", 0), timeout=0, allowed_updates=["message"]) or []
    fixed = os.environ.get("TELEGRAM_CHAT")
    for u in ups:
        tg["offset"] = u["update_id"] + 1
        m = u.get("message") or {}
        chat = str((m.get("chat") or {}).get("id", ""))
        text = (m.get("text") or "").strip()
        if not chat or not text:
            continue
        owner = fixed or tg.get("chat")
        if text.startswith("/start") and not owner:
            tg["chat"] = chat
            owner = chat
            _call(token, "sendMessage", chat_id=chat, parse_mode="HTML",
                  text="✅ <b>Kairo ist verbunden.</b>\nDu bekommst ab jetzt nach jedem Scan (werktags ca. 22:45 Uhr) deinen Abendbericht.\n"
                       "Tipp: In der App unter Einstellungen → Telegram „Merkliste &amp; Depot senden“ tippen, dann bekommst du auch Alarme dafür.")
            continue
        if chat != str(owner):
            continue
        if text.startswith("/sync"):
            tg["sync"] = {**parse_sync(text), "date": time.strftime("%Y-%m-%d")}
            s = tg["sync"]
            _call(token, "sendMessage", chat_id=chat,
                  text=f"🔄 Übernommen: {len(s['fav'])} Merkliste-Aktien, {len(s['depot'])} Depot-Positionen. Gilt ab dem nächsten Scan.")
        elif text.startswith("/stop"):
            tg["paused"] = True
            _call(token, "sendMessage", chat_id=chat, text="⏸ Abendbericht pausiert. Mit /weiter wieder einschalten.")
        elif text.startswith("/weiter"):
            tg["paused"] = False
            _call(token, "sendMessage", chat_id=chat, text="▶️ Abendbericht wieder aktiv.")


def _pct(x: float) -> str:
    return f"{x * 100:+.1f} %".replace(".", ",")


def _num(x) -> str:
    return "–" if x is None else f"{x:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def report(rows: list[dict], last: dict, market: dict, events: list[dict], search: dict, tg: dict, today_de: str,
           fc_names=None) -> str:
    e = html.escape
    by = {r["ticker"]: r for r in rows}
    sync = tg.get("sync") or {}
    fav = set(sync.get("fav", []))
    mine = fav | {r["ticker"] for r in rows if r.get("in_watchlist")} | {d["t"] for d in sync.get("depot", [])}
    prev_hit, prev_fast = set(last.get("hit", [])), set(last.get("fast", []))
    prev_met = last.get("met", {})
    L = [f"🌙 <b>Kairo · Abendbericht {today_de}</b>"]
    reg = market.get("regime")
    if reg:
        dot = {"green": "🟢", "yellow": "🟡", "red": "🔴"}.get(reg["tone"], "⚪")
        vix = market.get("^VIX", {}).get("c")
        L.append(f"{dot} Markt: {e(reg['label'])}" + (f" · VIX {vix:.0f}" if vix else ""))
    hits = [r for r in rows if r["passed"]]
    new_hits = [r for r in hits if r["ticker"] not in prev_hit]
    L.append(f"\n<b>{len(hits)} Treffer</b> · {sum(r.get('fast_hit', False) for r in rows)} Fast-Treffer"
             + (f" · <b>{len(new_hits)} neu</b>" if last else ""))
    # Deine Aktien zuerst
    mine_lines = []
    for t in sorted(mine):
        r = by.get(t)
        if not r:
            continue
        was = "hit" if t in prev_hit else "fast" if t in prev_fast else None
        now = "hit" if r["passed"] else "fast" if r.get("fast_hit") else None
        star = "⭐" if t in fav else "👁"
        fc = ((r.get("trend") or {}).get("fc") or {}).get("dir")
        arrow = {"up": " ▲", "down": " ▼"}.get(fc, "")
        if now == "hit" and was != "hit":
            g = (r.get("grade") or {}).get("g")
            mine_lines.append(f"{star} 🟢 <b>{e(r['name'] or t)}</b> ist jetzt <b>Treffer</b>{' · Stufe ' + g if g else ''} · Score {r['score']}, CRV {_num(r.get('crv'))}")
        elif now == "fast" and was is None:
            mine_lines.append(f"{star} 🟡 <b>{e(r['name'] or t)}</b> ist Fast-Treffer – fehlt: {e(r['missing'][0])}{arrow}")
        elif was and not now:
            mine_lines.append(f"{star} ⚪ {e(r['name'] or t)} ist kein {'Treffer' if was == 'hit' else 'Fast-Treffer'} mehr")
        elif prev_met.get(t) is not None and r.get("met") is not None and r["met"] - prev_met[t] >= 2:
            mine_lines.append(f"{star} ↗️ {e(r['name'] or t)}: {prev_met[t]} → {r['met']}/11 Kriterien{arrow}")
    if mine_lines:
        L.append("\n<b>Deine Aktien</b>")
        L += mine_lines[:15]
    # Depot: Knock-out-Abstand
    dep_lines = []
    for d in sync.get("depot", []):
        s = search.get(d["t"])
        if not s or not d.get("ko") or not s.get("c"):
            continue
        dist = (s["c"] - d["ko"]) / s["c"] if d.get("dir") == "long" else (d["ko"] - s["c"]) / s["c"]
        atr = s.get("atr")
        if dist < 0.08:
            dep_lines.append(f"{'🔴' if dist < 0.04 else '🟠'} <b>{e(s.get('n') or d['t'])}</b> Turbo {d.get('dir', 'long').title()}: "
                             f"nur noch {_pct(dist).lstrip('+')} bis K.-o. {_num(d['ko'])}"
                             + (f" (≈ {abs(s['c'] - d['ko']) / atr:.1f} Tagesspannen)" if atr else ""))
    if dep_lines:
        L.append("\n<b>Depot · Knock-out-Warnung</b>")
        L += dep_lines
    # Neue Top-Treffer
    if new_hits:
        L.append("\n<b>Neue Treffer</b> (Top 8 nach Score)")
        for r in sorted(new_hits, key=lambda r: ({"A": 0, "B": 1, "C": 2}.get((r.get("grade") or {}).get("g"), 3), -r["score"]))[:8]:
            g = (r.get("grade") or {}).get("g")
            L.append(f"• {'🅰️ ' if g == 'A' else ''}<a href=\"{APP}#{e(r['ticker'])}\">{e((r['name'] or r['ticker'])[:32])}</a> · {('Stufe ' + g + ' · ') if g else ''}Score {r['score']} · CRV {_num(r.get('crv'))}"
                     + (" ⚠️ Earnings" if r.get("earnings_risk") else ""))
    # Termine morgen / übermorgen für deine Aktien + Makro
    up = [ev for ev in events if ev.get("days") in (0, 1, 2) and (not ev.get("ticker") or ev["ticker"] in mine)]
    if up:
        L.append("\n<b>Termine</b>")
        for ev in up[:8]:
            when = {0: "heute", 1: "morgen", 2: "übermorgen"}[ev["days"]]
            what = ev.get("title") or f"{ev.get('name') or ev['ticker']}: {'Quartalszahlen' if ev['kind'] == 'earnings' else 'Dividende'}"
            L.append(f"📅 {when}: {e(what)}")
    L.append(f"\n<a href=\"{APP}\">Kairo öffnen</a>")
    return "\n".join(L)


def run(rows, market, calendar_events, search, today_iso: str, today_de: str) -> dict:
    """Updates lesen, Bericht senden. Liefert öffentlichen Status für die App (ohne Chat-ID)."""
    token = os.environ.get("TELEGRAM_TOKEN")
    tg = state.load("telegram.json", {})
    last = state.load("last.json", {})
    if not token:
        return {"enabled": False}
    me = _call(token, "getMe") or {}
    tg["bot"] = me.get("username")
    read_updates(token, tg)
    chat = os.environ.get("TELEGRAM_CHAT") or tg.get("chat")
    sent = False
    if chat and not tg.get("paused"):
        import pandas as pd
        today = pd.Timestamp(today_iso)
        evs = []
        for ev in calendar_events:
            try:
                evs.append({**ev, "days": int(__import__("numpy").busday_count(today.date(), pd.Timestamp(ev["date"]).date()))})
            except Exception:
                pass
        text = report(rows, last, market, evs, search, tg, today_de)
        sent = bool(_call(token, "sendMessage", chat_id=chat, text=text[:4000], parse_mode="HTML", disable_web_page_preview=True))
        if sent:
            tg["last_sent"] = today_iso
    state.save("telegram.json", tg)
    print(f"Telegram: Bot @{tg.get('bot')}, Chat {'verbunden' if chat else 'fehlt (/start an den Bot senden)'}, Bericht {'gesendet' if sent else 'nicht gesendet'}")
    return {"enabled": True, "bot": tg.get("bot"), "connected": bool(chat), "synced": (tg.get("sync") or {}).get("date"),
            "n_fav": len((tg.get("sync") or {}).get("fav", [])), "n_dep": len((tg.get("sync") or {}).get("depot", [])),
            "last_sent": tg.get("last_sent"), "paused": bool(tg.get("paused"))}
