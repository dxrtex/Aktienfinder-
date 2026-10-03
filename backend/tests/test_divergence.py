import numpy as np
import pandas as pd

from backend.config import CONFIG
from backend.indicators import rsi
from backend.scanner import find_rsi_divergence


def _series(parts):
    c = np.concatenate([np.linspace(a, b, k) for a, b, k in parts])
    return pd.Series(c - 0.2, index=pd.bdate_range("2026-01-01", periods=len(c))), pd.Series(c)


def test_classic_divergence():
    # steiler Abverkauf auf 100 (RSI tief), Erholung, langsames tieferes Tief 99, dann leichter Anstieg
    low, close = _series([(130, 131, 40), (131, 100, 10), (100, 115, 15), (115, 99, 20), (99, 101, 4)])
    div, _ = find_rsi_divergence(low, rsi(close).to_numpy(), CONFIG.rsi)
    assert div and div[0] == "klassisch"


def test_hidden_divergence():
    # zäher Abwärts-Zickzack auf 100 (RSI nur mäßig tief), Erholung, dann steiler Rücksetzer
    # auf ein HÖHERES Tief (~105) – der RSI fällt dabei tiefer als beim ersten Tief
    steps = [0.0] * 40 + [-1.6, 1.0] * 14 + [-1.6] + [1.6] * 25 + [-5.0] * 7 + [0.5] * 4
    c = np.cumsum(steps)
    c = c - c[68] + 100
    close = pd.Series(c)
    low = pd.Series(c - 0.2, index=pd.bdate_range("2026-01-01", periods=len(c)))
    div, _ = find_rsi_divergence(low, rsi(close).to_numpy(), CONFIG.rsi)
    assert div and div[0] == "versteckt"


def test_no_divergence_in_steady_trend():
    low, close = _series([(150, 100, 100)])
    div, _ = find_rsi_divergence(low, rsi(close).to_numpy(), CONFIG.rsi)
    assert div is None
