import numpy as np
import pandas as pd
import pytest

from aktienfinder.indicators import macd, pivot_low, rsi

# Lehrbuch-Beispiel (StockCharts "RSI"). Die dort abgedruckten Werte (70.53, 66.32 …)
# entstehen mit gerundeten Zwischenwerten; hier die exakte Wilder-Rechnung.
CLOSES = [44.34, 44.09, 44.15, 43.61, 44.33, 44.83, 45.10, 45.42, 45.84, 46.08,
          45.89, 46.03, 45.61, 46.28, 46.28, 46.00, 46.03, 46.41, 46.22, 45.64]
EXPECTED = {14: 70.46, 15: 66.25, 16: 66.48, 17: 69.35, 18: 66.29, 19: 57.92}


def test_rsi_matches_wilder_reference():
    r = rsi(pd.Series(CLOSES), 14)
    assert r.iloc[:14].isna().all()
    for i, expected in EXPECTED.items():
        assert r.iloc[i] == pytest.approx(expected, abs=0.01)


def test_rsi_extremes():
    up = rsi(pd.Series(np.arange(1, 40, dtype=float)), 14)
    down = rsi(pd.Series(np.arange(40, 1, -1, dtype=float)), 14)
    assert up.iloc[-1] == 100
    assert down.iloc[-1] == 0


def test_macd_hist_is_line_minus_signal():
    close = pd.Series(np.sin(np.linspace(0, 10, 200)) * 10 + 100)
    m = macd(close)
    assert np.allclose(m["hist"], m["macd"] - m["signal"])


def test_pivot_low_marks_confirmation_bar():
    s = pd.Series([5, 4, 3, 2, 1, 2, 3, 4, 5, 6], dtype=float)
    found = pivot_low(s, left=3, right=2)
    # Tief bei Index 4, bestätigt 2 Balken später bei Index 6
    assert list(np.flatnonzero(found)) == [6]
