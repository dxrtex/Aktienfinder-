"""Alle einstellbaren Parameter des Scanners an einem Ort.

Die Startwerte sind aus den Beispiel-Trades (D-Wave, Rocket Lab, Infineon, Uber, TUI,
Stand Okt. 2026) abgeleitet.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Config:
    # Zeitfenster: Die drei Pflichtsignale müssen innerhalb von `cluster_span`
    # Handelstagen zueinander auftreten (≈ 3 Wochen) und das jüngste davon darf
    # höchstens `max_signal_age` Handelstage alt sein (≈ 6 Wochen). Bei den Beispielen
    # lagen zwischen Signal-Bündel und Einstieg (Ausbruch aus der Bodenzone) 0–4 Wochen.
    cluster_span: int = 15
    max_signal_age: int = 30

    # RSI und Divergenz
    rsi_length: int = 14
    pivot_left: int = 3          # Balken links vom Tief
    pivot_right: int = 3         # Balken rechts vom Tief (Bestätigung)
    divergence_min_bars: int = 4   # Mindestabstand der beiden Tiefs (TUI: Doppelboden ~5 Tage)
    divergence_max_bars: int = 60  # Höchstabstand (Infineon/Uber: ~7 Wochen)

    # MACD
    macd_fast: int = 12
    macd_slow: int = 26
    macd_signal: int = 9
    macd_rising_bars: int = 3      # so viele Tage in Folge kleiner werdende rote Balken
    macd_near_zero: float = 0.5    # Histogramm hat sich um mind. 50 % vom Tiefpunkt erholt
    macd_trough_lookback: int = 20

    # Momentum Bias Index (AlgoAlpha) – Eingaben wie im Original (close 10 5 10 30 3)
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
    volume_spike: float = 1.5      # Volumen ≥ 1,5 × Durchschnitt
    fib_lookback: int = 150        # Suchbereich für den letzten Aufwärtsschwung
    # Rücksetzer bis in die Zone 0,618–0,886 (Uber lag knapp unter 0,79, TUI in 0,706–0,79)
    fib_zone: tuple = (0.618, 0.886)
    fib_tolerance: float = 0.03    # etwas Spielraum um die Zone
    ema_trigger_length: int = 20   # Ausbruch über die EMA 20 als Einstiegs-Trigger
    trigger_max_age: int = 5

    # Grundfilter gegen Pennystocks / illiquide Werte
    min_price: float = 1.0
    min_dollar_volume: float = 1_000_000.0

    # Benötigte Historie
    history_period: str = "2y"


DEFAULT = Config()
