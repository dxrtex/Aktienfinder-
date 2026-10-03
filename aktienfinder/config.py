"""Alle einstellbaren Parameter des Scanners an einem Ort."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Config:
    # Zeitfenster: alle drei Pflichtsignale müssen in den letzten N Handelstagen
    # aufgetreten sein (10 Handelstage ≈ 2 Wochen).
    signal_window: int = 10

    # RSI und Divergenz (wie die eingebaute Divergenz-Erkennung im TradingView-RSI)
    rsi_length: int = 14
    pivot_left: int = 5          # Balken links vom Tief
    pivot_right: int = 5         # Balken rechts vom Tief (Bestätigung)
    divergence_min_bars: int = 5   # Mindestabstand der beiden Tiefs
    divergence_max_bars: int = 60  # Höchstabstand der beiden Tiefs

    # MACD
    macd_fast: int = 12
    macd_slow: int = 26
    macd_signal: int = 9
    macd_rising_bars: int = 3      # so viele Tage in Folge kleiner werdende rote Balken
    macd_near_zero: float = 0.5    # Histogramm hat sich um mind. 50 % vom Tiefpunkt erholt
    macd_trough_lookback: int = 20

    # Momentum Bias Index (AlgoAlpha) – Standardwerte des Originals
    mbi_momentum_length: int = 10
    mbi_bias_length: int = 5
    mbi_smooth_length: int = 10
    mbi_impulse_length: int = 30
    mbi_std_mult: float = 3.0

    # Weiche Kriterien (nur Score)
    drawdown_lookback: int = 252   # ca. 1 Jahr
    drawdown_full: float = 0.20    # ab 20 % unter Hoch volle Punkte
    drawdown_min: float = 0.05     # unter 5 % keine Punkte
    volume_avg_length: int = 20
    volume_spike: float = 1.5      # Volumen am Tief ≥ 1,5 × Durchschnitt

    # Grundfilter gegen Pennystocks / illiquide Werte
    min_price: float = 1.0
    min_dollar_volume: float = 1_000_000.0

    # Benötigte Historie
    history_period: str = "2y"


DEFAULT = Config()
