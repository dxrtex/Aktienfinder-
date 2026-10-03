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

    # Pflicht-Filter aus dem eigenen Analyse-Ablauf (zusätzlich zu den drei Signalen)
    require_fib_zone: bool = True     # Rücksetzer hat mind. die Golden Zone erreicht (s. fib_required)
    min_drawdown: float = 0.20        # Rücksetzer-Tief mind. 20 % unter dem 52-Wochen-Hoch
    macd_line_rising: bool = True     # MACD-Linie fällt nicht mehr (seitwärts oder steigend)
    macd_line_lookback: int = 3       # … verglichen mit dem Wert vor so vielen Tagen
    macd_line_tolerance: float = 0.10 # minimaler Rückgang zählt als „seitwärts“: Anteil der
                                      # größten MACD-Ausschläge der letzten 60 Tage
    min_analyst_upside: float = 0.40  # Analysten-Kursziel mind. 40 % über Kurs (Website-Filter)

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
    # Golden Zone 0,618–0,79 (Anzeige „★“ auf der Website, mit Toleranz)
    fib_zone: tuple = (0.618, 0.79)
    fib_tolerance: float = 0.03    # etwas Spielraum um die Zone
    # Pflicht: Rücksetzer mind. bis 0,618; tiefer ist erlaubt (Rocket Lab: unter die Zone
    # gefallen, gleichzeitig Divergenzen), nur unter das Schwungtief (> 1,0) nicht
    fib_required: tuple = (0.618, 1.0)
    fib_levels: tuple = (0.618, 0.706, 0.79, 0.886, 1.0)   # Linien für die Umkehrkerze
    fib_level_tolerance: float = 0.02   # Kerzentief höchstens 2 % (der Schwunghöhe) neben einer Linie
    reversal_lookback: int = 3          # Umkehrkerze in den letzten N Tagen
    rsi_signal_length: int = 14         # gelbe Signallinie des RSI (TradingView: SMA 14)
    rsi_signal_gap: float = 2.0         # RSI höchstens so viele Punkte unter der Signallinie
    ema_trigger_length: int = 20   # Ausbruch über die EMA 20 als Einstiegs-Trigger
    trigger_max_age: int = 5

    # Grundfilter gegen Pennystocks / illiquide Werte (in US-Dollar umgerechnet, siehe markets.py)
    min_price: float = 1.0
    min_dollar_volume: float = 1_000_000.0   # durchschnittlicher Tagesumsatz

    # Benötigte Historie
    history_period: str = "2y"


DEFAULT = Config()
