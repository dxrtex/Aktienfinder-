import numpy as np
import pandas as pd
import pytest

from backend.indicators import atr, ema, macd, pivot_highs, pivot_lows, rma, rsi, sma

# Lehrbuch-Beispiel (StockCharts „RSI“) – exakte Wilder-Rechnung
CLOSES = [44.34, 44.09, 44.15, 43.61, 44.33, 44.83, 45.10, 45.42, 45.84, 46.08,
          45.89, 46.03, 45.61, 46.28, 46.28, 46.00, 46.03, 46.41, 46.22, 45.64]
EXPECTED_RSI = {14: 70.46, 15: 66.25, 16: 66.48, 17: 69.35, 18: 66.29, 19: 57.92}


def test_rsi_matches_wilder_reference():
    r = rsi(pd.Series(CLOSES), 14)
    assert r.iloc[:14].isna().all()
    for i, expected in EXPECTED_RSI.items():
        assert r.iloc[i] == pytest.approx(expected, abs=0.01)


def test_rsi_extremes():
    assert rsi(pd.Series(np.arange(1, 40, dtype=float)), 14).iloc[-1] == 100
    assert rsi(pd.Series(np.arange(40, 1, -1, dtype=float)), 14).iloc[-1] == 0


def test_ema_seeded_with_sma_like_pine():
    s = pd.Series([1, 2, 3, 4, 5, 6], dtype=float)
    e = ema(s, 3)
    assert np.isnan(e.iloc[1]) and e.iloc[2] == pytest.approx(2.0)      # SMA der ersten 3
    assert e.iloc[3] == pytest.approx(0.5 * 4 + 0.5 * 2.0)               # alpha = 2/(3+1)
    assert rma(s, 3).iloc[3] == pytest.approx(4 / 3 + 2 / 3 * 2.0)       # alpha = 1/3
    assert sma(s, 3).iloc[-1] == pytest.approx(5.0)


def test_atr_constant_range():
    idx = pd.bdate_range("2026-01-01", periods=30)
    df = pd.DataFrame({"High": 11.0, "Low": 9.0, "Close": 10.0, "Open": 10.0}, index=idx)
    assert atr(df, 14).iloc[-1] == pytest.approx(2.0)


def test_macd_hist_is_line_minus_signal():
    m = macd(pd.Series(np.sin(np.linspace(0, 10, 200)) * 10 + 100))
    assert np.allclose(m["hist"].dropna(), (m["macd"] - m["signal"]).dropna())


def test_pivots_with_open_right_side():
    s = pd.Series([5, 4, 3, 2, 1, 2, 3, 4, 5, 6, 5, 4, 3], dtype=float)
    assert list(pivot_lows(s, 3)) == [4, 12]       # 12: offenes Ende, aktueller Kurs gilt
    assert list(pivot_highs(s, 3)) == [9]
    # jüngstes Tief ohne volle rechte Seite zählt (aktueller Kurs gilt)
    t = pd.Series([5, 4, 3, 4, 5, 6, 5, 4, 2.5], dtype=float)
    assert 8 in list(pivot_lows(t, 3))
