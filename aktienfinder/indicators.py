"""Indikatoren, so nah wie möglich an der TradingView/Pine-Script-Berechnung."""

import numpy as np
import pandas as pd


def rma(src: pd.Series, length: int) -> pd.Series:
    """Wilder-Glättung wie Pine `ta.rma`: Start mit SMA, danach alpha = 1/length."""
    values = src.to_numpy(dtype=float)
    out = np.full(len(values), np.nan)
    alpha = 1.0 / length
    prev = np.nan
    start = None
    for i, v in enumerate(values):
        if np.isnan(v):
            continue
        if start is None:
            start = i
        if np.isnan(prev):
            if i - start + 1 >= length:
                window = values[i - length + 1 : i + 1]
                if not np.isnan(window).any():
                    prev = window.mean()
                    out[i] = prev
            continue
        prev = alpha * v + (1 - alpha) * prev
        out[i] = prev
    return pd.Series(out, index=src.index)


def ema(src: pd.Series, length: int) -> pd.Series:
    """Exponentieller Durchschnitt wie Pine `ta.ema` (Start mit dem ersten Wert)."""
    return src.ewm(span=length, adjust=False).mean()


def rsi(close: pd.Series, length: int = 14) -> pd.Series:
    """RSI wie Pine `ta.rsi`."""
    change = close.diff()
    up = rma(change.clip(lower=0), length)
    down = rma((-change).clip(lower=0), length)
    rs = up / down
    out = 100 - 100 / (1 + rs)
    out = out.where(down != 0, 100.0)
    out = out.where(up != 0, 0.0).where(~(up.isna() | down.isna()))
    return out


def macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame:
    """MACD-Linie, Signallinie und Histogramm wie Pine `ta.macd`."""
    line = ema(close, fast) - ema(close, slow)
    sig = ema(line, signal)
    return pd.DataFrame({"macd": line, "signal": sig, "hist": line - sig})


def pivot_low(src: pd.Series, left: int, right: int) -> pd.Series:
    """Pine `ta.pivotlow`: True am Bestätigungsbalken (Tief liegt `right` Balken zurück).

    Das Tief muss tiefer sein als die `left` Balken davor und nicht höher als die
    `right` Balken danach.
    """
    values = src.to_numpy(dtype=float)
    n = len(values)
    found = np.zeros(n, dtype=bool)
    for i in range(left + right, n):
        c = i - right
        center = values[c]
        if np.isnan(center):
            continue
        left_win = values[c - left : c]
        right_win = values[c + 1 : i + 1]
        if np.isnan(left_win).any() or np.isnan(right_win).any():
            continue
        if center < left_win.min() and center <= right_win.min():
            found[i] = True
    return pd.Series(found, index=src.index)
