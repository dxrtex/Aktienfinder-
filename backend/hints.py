"""Kurzer Hinweis je Aktie für die Suche: Wo steht die Aktie im Setup, was fehlt, wie lange noch?

`hint(res, cfg)` wertet nur das Ergebnis von `scanner.evaluate()` aus (Kriterien + Flags) und liefert
{tone, title, text, days, days_label}. Tage sind Handelstage und reine Schätzungen aus den Regeln:
- Treffer: Tage, bis das erste Zeitfenster (MBI-X ≤ 15, MACD-Kreuz ≤ 7, RSI-Tief T2 ≤ 10) abläuft.
- Fällt noch: Tage, bis die 10-Kerzen-Spanne klein genug wäre, wenn der Kurs ab jetzt seitwärts läuft.
- MACD vor dem Kreuz: Tage bis zum Kreuz bei gleichbleibendem Anstieg des Histogramms.
"""

from __future__ import annotations

import math
from types import SimpleNamespace

from .config import CONFIG
from .scanner import Result, de, pct

UNIVERSE_KEYS = ("cap", "liquidity", "price", "history")
SHORT = {"rsi_div": "RSI-Divergenz", "rsi_range": "RSI 28–48", "macd_below0": "MACD unter 0", "macd_turn": "MACD dreht",
         "mbi": "MBI grünes X", "crv": "CRV ≥ 2"}
SIGNAL_KEYS = ("rsi_div", "rsi_range", "macd_below0", "macd_turn", "mbi", "crv")


def _tage(n: int) -> str:
    return "1 Tag" if n == 1 else f"{n} Tagen"


def _zone_where(res: Result, cfg: SimpleNamespace) -> str:
    """Wo liegt die Fib-Zone relativ zum Kurs?"""
    fib = res.zone.get("fib")
    if res.zone.get("support"):
        s = res.zone["support"]
        return f"Kurs steht an einem Mehrfachboden ({s['touches']} Touches um {de(s['center'])})."
    if not fib or fib["impulse"] < cfg.fib.min_impulse:
        return "Keine brauchbare Fib-Zone (Aufwärtsimpuls davor zu klein) und kein Mehrfachboden."
    lv = fib["levels"]
    top, bottom = lv["0.618"], lv["0.79"]
    if fib["ok"]:
        return f"Kurs ist bereits in der Fib-Zone ({de(bottom)}–{de(top)})."
    if not fib["valid"]:
        return f"Fib-Zone nach unten durchbrochen (unter 0,886 = {de(lv['0.886'])}) – Setup nur noch über einen neuen Boden möglich."
    return f"Fib-Zone 0,618–0,79 liegt bei {de(bottom)}–{de(top)}, also noch {pct((res.close - top) / res.close)} tiefer."


def _macd_eta(f: dict, cap: int = 15) -> int | None:
    h, slope = f.get("macd_hist"), f.get("macd_slope")
    if h is None or slope is None or h >= 0 or slope <= 0:
        return None
    eta = math.ceil(-h / slope)
    return eta if eta <= cap else None


def _signal_text(key: str, res: Result, cfg: SimpleNamespace) -> tuple[str, int | None]:
    """Erklärung für ein fehlendes Bestätigungssignal (+ evtl. Tage)."""
    f = res.flags
    if key == "macd_turn":
        if f.get("macd_failed"):
            return "MACD fällt nach dem Kreuz schon wieder – Fehlsignal, abwarten.", None
        if (f.get("macd_hist") or 0) >= 0:
            return (f"MACD hat schon vor {f.get('macd_cross_age')} Tagen gekreuzt (Regel ≤ {cfg.macd.cross_max_age}) – "
                    "die Umkehr läuft bereits, Einstieg wäre eher spät."), None
        eta = _macd_eta(f)
        if eta:
            return f"MACD-Histogramm steigt Richtung 0 – Kreuz bei gleichem Tempo in ca. {_tage(eta)}.", eta
        return "MACD dreht noch nicht – Histogramm fällt noch oder steigt zu schwach.", None
    if key == "mbi":
        age = f.get("mbi_x_age")
        if age is None or (age > 60):
            return "MBI zeigt noch kein grünes X – Verkaufsdruck noch nicht erschöpft.", None
        if age > cfg.mbi.x_max_age:
            return f"Letztes grünes X im MBI ist {age} Kerzen alt (Regel ≤ {cfg.mbi.x_max_age}) – Signal schon älter.", None
        if f.get("mbi_new_peak"):
            return "Nach dem grünen X im MBI kam eine neue, höhere rote Spitze – der Verkaufsdruck kehrt zurück.", None
        if not f.get("mbi_above_ref", True):
            return "Grünes X im MBI, aber die rote Spitze lag nicht über der Referenzlinie – zu schwaches Signal.", None
        return "Grünes X im MBI ist da, aber der rote Balken ist noch nicht weit genug abgebaut.", None
    if key == "rsi_div":
        return "Keine RSI-Divergenz – ein neues Tief mit höherem RSI (oder umgekehrt) fehlt noch.", None
    if key == "rsi_range":
        r = f.get("rsi") or 0
        if r > cfg.rsi.current_max:
            return f"RSI schon bei {de(r, 0)} (Regel 28–48) – die Erholung ist bereits angelaufen.", None
        return f"RSI erst bei {de(r, 0)} (Regel 28–48) – noch im Ausverkauf.", None
    if key == "macd_below0":
        return "MACD-Linien sind schon über 0 – der Trend hat bereits gedreht, kein Reversal-Einstieg mehr.", None
    if key == "crv":
        p = res.plan
        if not p.get("stop") or not p.get("target2"):
            return "Kein Trade-Plan möglich (keine Zone).", None
        good = (p["target2"] + cfg.risk.min_crv * p["stop"]) / (1 + cfg.risk.min_crv)
        return (f"Chance-Risiko nur {de(p.get('crv'), 1)} (Regel ≥ {de(cfg.risk.min_crv, 1)}) – "
                f"erst bei Kurs ≤ {de(good)} lohnt es sich."), None
    return "", None


def _validity(res: Result, cfg: SimpleNamespace) -> tuple[int | None, str]:
    """Treffer: verbleibende Handelstage bis das erste Zeitfenster abläuft."""
    f, left = res.flags, []
    if f.get("mbi_x_age") is not None:
        left.append((cfg.mbi.x_max_age - f["mbi_x_age"], "ist das grüne MBI-X älter als 15 Kerzen"))
    if f.get("macd_cross_done") and f.get("macd_cross_age") is not None:
        left.append((cfg.macd.cross_max_age - f["macd_cross_age"], "ist das MACD-Kreuz älter als 7 Kerzen"))
    if f.get("div_t2_age") is not None:
        left.append((cfg.rsi.t2_max_age - f["div_t2_age"], "ist das RSI-Tief älter als 10 Kerzen"))
    if not left:
        return None, ""
    days, why = min(left)
    return max(0, days), why


def hint(res: Result, cfg: SimpleNamespace = CONFIG) -> dict:
    f = res.flags
    crit = {c.key: c for c in res.criteria}
    miss = [c.key for c in res.missing]
    out = lambda tone, title, text, days=None, label="": {
        "tone": tone, "title": title, "text": text.strip(), "days": days, "days_label": label}
    e20 = f.get("ema20")
    earn = (f" ⚠ Earnings am {f['earnings_date'][8:10]}.{f['earnings_date'][5:7]}. – erhöhtes Risiko."
            if f.get("earnings_risk") and f.get("earnings_date") else "")

    # 1. Außerhalb des Suchrasters
    uni = [crit[k] for k in UNIVERSE_KEYS if k in miss]
    if uni:
        return out("gray", "Außerhalb des Suchrasters", "Nicht geprüft: " + "; ".join(f"{c.label} ({c.value})" for c in uni) + ".")

    # 2. Treffer
    if res.passed:
        days, why = _validity(res, cfg)
        txt = "Alle Pflichtkriterien erfüllt – die Aktie ist in einem sehr guten Setup für einen Einstieg. "
        if days is not None:
            txt += (f"Das Setup ist noch ca. {_tage(days)} gültig (danach {why})." if days else
                    f"Heute ist der letzte Tag im Zeitfenster (danach {why}).") + " "
        if e20:
            txt += f"Ein Ausbruch über die EMA 20 ({de(e20)}, {pct(e20 / res.close - 1)} höher) beendet das Setup – dann ist der Einstiegsmoment vorbei. "
        if res.plan.get("stop"):
            txt += f"Ungültig bei Schluss unter dem Stop {de(res.plan['stop'])}."
        return out("green", f"Einstiegs-Setup · Score {res.score}", txt + earn, days, "noch gültig")

    # 3. Crash statt Pullback
    if "no_crash" in miss:
        wait = max(1, cfg.correction.crash_lookback - (f.get("crash_age") or 0))
        return out("red", "Crash – kein Pullback",
                   f"{crit['no_crash'].value} an einem Tag – das ist ein Absturz, keine normale Korrektur. Finger weg, "
                   f"frühestens in ca. {_tage(wait)} wieder prüfbar (dann fällt der Crash-Tag aus dem 10-Tage-Fenster).",
                   wait, "warten")

    # 4. Kein Rücksetzer
    if "drawdown" in miss:
        H = res.zone.get("H")
        if not H:
            return out("gray", "Kein Rücksetzer",
                       "Kein Swing-High in den letzten 20–180 Tagen – die Aktie steigt oder notiert nahe am Hoch. Kein Reversal-Setup.")
        trig = H * (1 - cfg.correction.min_drawdown)
        dd = (H - res.close) / H
        above = e20 and res.close > e20
        where = (f"Kurs liegt über dem letzten Swing-Hoch {de(H)}" if dd <= 0
                 else f"Nur {pct(dd)} unter dem Swing-Hoch {de(H)} (Regel ≥ 12 %)")
        return out("gray", "Aufwärtstrend – kein Rücksetzer" if above else "Nur leichter Rücksetzer",
                   f"{where}. Interessant wird die Aktie erst unter {de(trig)} ({pct(1 - trig / res.close).replace('–', '')} tiefer).")

    # 5. Struktur: schon über EMA 20 bzw. EMA 20 fällt nicht mehr
    if "structure" in miss:
        if e20 and res.close >= e20:
            return out("gray", "Erholung läuft schon",
                       f"Kurs ist schon wieder über der EMA 20 ({de(e20)}) – die Umkehr ist im Gange, der Einstieg im Rücksetzer ist vorbei. "
                       "Auf den nächsten Rücksetzer warten.")
        if not f.get("ema20_falling"):
            return out("yellow", "Seitwärts unter den EMAs",
                       "Kurs liegt unter EMA 20 und 50, die EMA 20 fällt aber nicht mehr – eher Seitwärtsphase als frischer Rücksetzer. "
                       + _zone_where(res, cfg))
        return out("gray", "Über der EMA 50",
                   f"Kurs ist unter der EMA 20, aber noch über der EMA 50 ({de(f.get('ema50'))}) – die Korrektur ist noch nicht tief genug.")

    # 6. Fällt noch stark
    if "flattening" in miss:
        eta = f.get("flat_eta") or cfg.correction.flat_days
        return out("orange", "Fällt noch stark – noch kein Einstieg",
                   f"Die letzten 10 Kerzen schwanken noch zu stark. Warten auf Konsolidierung: frühestens in ca. {_tage(eta)}, "
                   f"wenn der Kurs ab jetzt seitwärts läuft. " + _zone_where(res, cfg) + earn, eta, "bis Konsolidierung")

    # 7. Keine Unterstützung
    if "zone" in miss:
        return out("orange", "Korrektur ohne Unterstützung",
                   "Die Korrektur flacht ab, der Kurs steht aber an keiner Unterstützung. " + _zone_where(res, cfg) + earn)

    # 8. Bodenbildung in der Zone – Signale fehlen noch
    keys = [k for k in miss if k in SIGNAL_KEYS and not (k == "macd_turn" and "macd_below0" in miss)]
    texts = [_signal_text(k, res, cfg) for k in keys]
    days = min((d for _, d in texts if d), default=None)
    body = " ".join(t for t, _ in texts if t)
    if res.fast_hit:
        c = res.missing[0]
        return out("yellow", f"Fast-Treffer – nur „{SHORT.get(c.key, c.label)}“ fehlt",
                   "Zone, Korrektur und fast alle Signale passen. " + body + earn, days, "bis MACD-Kreuz" if days else "")
    return out("yellow", "In der Zone – Bestätigung fehlt noch",
               f"Kurs steht in der Unterstützung und flacht ab, es fehlen noch {len(miss)} Signale. " + body
               + " Beobachten." + earn, days, "bis MACD-Kreuz" if days else "")
