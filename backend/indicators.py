"""Technische Indikatoren – selbst implementiert, Formeln wie in TradingView (Pine Script)."""

import numpy as np
import pandas as pd


def sma(src: pd.Series, length: int) -> pd.Series:
    """Einfacher Durchschnitt wie `ta.sma`."""
    return src.rolling(length).mean()


def ema(src: pd.Series, length: int) -> pd.Series:
    """Exponentieller Durchschnitt wie `ta.ema` (alpha = 2 / (length + 1), Start mit SMA)."""
    return _seeded(src, 2.0 / (length + 1), length)


def rma(src: pd.Series, length: int) -> pd.Series:
    """Wilder-Glättung wie `ta.rma` (alpha = 1 / length, Start mit SMA)."""
    return _seeded(src, 1.0 / length, length)


def _seeded(src: pd.Series, alpha: float, length: int) -> pd.Series:
    """Rekursive Glättung, die wie Pine mit dem SMA der ersten `length` gültigen Werte startet."""
    vals = src.to_numpy(dtype=float)
    out = np.full(len(vals), np.nan)
    valid = np.flatnonzero(~np.isnan(vals))
    if len(valid) < length:
        return pd.Series(out, index=src.index)
    start = valid[0]
    seed_end = start + length - 1
    if np.isnan(vals[start : seed_end + 1]).any():   # Lücke in der Startphase: einfach weiter hinten starten
        return pd.Series(out, index=src.index)
    out[seed_end] = vals[start : seed_end + 1].mean()
    prev = out[seed_end]
    for i in range(seed_end + 1, len(vals)):
        v = vals[i]
        prev = prev if np.isnan(v) else alpha * v + (1 - alpha) * prev
        out[i] = prev
    return pd.Series(out, index=src.index)


def rsi(close: pd.Series, length: int = 14) -> pd.Series:
    """RSI nach Wilder wie `ta.rsi`."""
    change = close.diff()
    gain = rma(change.clip(lower=0), length)
    loss = rma(-change.clip(upper=0), length)
    rs = gain / loss
    out = 100 - 100 / (1 + rs)
    out[(loss == 0) & gain.notna()] = 100.0
    return out


def macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame:
    """MACD wie `ta.macd`: Linie = EMA(fast) − EMA(slow), Signal = EMA(Linie, signal)."""
    line = ema(close, fast) - ema(close, slow)
    sig = ema(line, signal)
    return pd.DataFrame({"macd": line, "signal": sig, "hist": line - sig})


def true_range(df: pd.DataFrame) -> pd.Series:
    prev_close = df["Close"].shift(1)
    return pd.concat([df["High"] - df["Low"], (df["High"] - prev_close).abs(),
                      (df["Low"] - prev_close).abs()], axis=1).max(axis=1, skipna=False).fillna(df["High"] - df["Low"])


def atr(df: pd.DataFrame, length: int = 14) -> pd.Series:
    """Average True Range wie `ta.atr` (RMA des True Range)."""
    return rma(true_range(df), length)


def pivot_lows(low: pd.Series, length: int, ties: bool = False) -> np.ndarray:
    """Positionen der Pivot-Tiefs: tiefster Punkt mit je `length` Kerzen links und rechts.

    Für die letzten `length` Kerzen gibt es noch keine volle rechte Seite – dort zählt der
    aktuelle Kurs: ein Tief ist ein (vorläufiges) Pivot, wenn es tiefer ist als die `length`
    Kerzen davor und nicht tiefer als alle Kerzen danach bis heute.
    ties=True: ein gleich tiefes Tief (Doppelboden) zählt ebenfalls als eigenes Pivot.
    """
    return _pivots(low.to_numpy(dtype=float), length, lower=True, ties=ties)


def pivot_highs(high: pd.Series, length: int) -> np.ndarray:
    """Positionen der Pivot-Hochs (Spiegelbild von `pivot_lows`)."""
    return _pivots(high.to_numpy(dtype=float), length, lower=False)


def _pivots(v: np.ndarray, length: int, lower: bool, ties: bool = False) -> np.ndarray:
    x = -v if not lower else v
    n = len(x)
    out = []
    for i in range(length, n):
        if np.isnan(x[i]):
            continue
        left = x[i - length : i]
        right = x[i + 1 : i + 1 + length]
        if np.isnan(left).any():
            continue
        # strikt tiefer als links, nicht tiefer als rechts (wie ta.pivotlow bei Gleichstand rechts)
        if (x[i] <= left.min() if ties else x[i] < left.min()) and (len(right) == 0 or x[i] <= np.nanmin(right)):
            out.append(i)
    return np.array(out, dtype=int)
