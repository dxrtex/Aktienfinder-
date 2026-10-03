"""Score 0–100 (Abschnitt 4): nur Aktien mit allen Pflichtkriterien bekommen Punkte."""

from types import SimpleNamespace


def score_setup(res, cfg: SimpleNamespace) -> tuple[int, list[tuple[str, int]]]:
    if not res.passed:
        return 0, []
    s, f = cfg.score, res.flags
    div = f.get("divergence") or {}
    crv = (res.plan or {}).get("crv") or 0
    parts = [
        ("Basis (alle Pflichtkriterien erfüllt)", s.base, True),
        ("Fib-Kernzone 0,706–0,79 oder Support mit ≥ 3 Touches", s.fib_core_or_3_touches,
         f.get("fib_core") or f.get("support_3_touches")),
        ("Fib-Zone und Support überlappen", s.fib_and_support_overlap, f.get("overlap")),
        ("EMA 200 in der Zone", s.ema200_in_zone, f.get("ema200_in_zone")),
        ("Klassische Divergenz", s.classic_divergence, div.get("kind") == "klassisch"),
        ("RSI war ≤ 32 in den letzten 60 Tagen", s.rsi_was_oversold, f.get("rsi_was_oversold")),
        ("RSI über SMA 14", s.rsi_above_sma, f.get("rsi_above_sma")),
        ("MACD-Kreuz bereits erfolgt", s.macd_cross_done, f.get("macd_cross_done")),
        ("MACD-Divergenz", s.macd_divergence, f.get("macd_divergence")),
        ("MBI-Histogramm bereits grün", s.mbi_green, f.get("mbi_green")),
        ("Volumen-Climax in der Zone", s.volume_climax, f.get("volume_climax")),
        ("CRV ≥ 3", s.crv_3, crv >= 3),
        ("Earnings innerhalb 5 Tagen", s.earnings_penalty, f.get("earnings_risk")),
    ]
    got = [(label, pts) for label, pts, ok in parts if ok]
    return max(0, min(100, sum(p for _, p in got))), got
