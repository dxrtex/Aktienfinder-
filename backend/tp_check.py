"""Vorübergehend: erkannte Take-Profit-Stufen für einige Ticker ausgeben (Abgleich mit Markierungen)."""
import sys

from .analysis import analyze
from .data_provider import YFinanceProvider
from .scanner import evaluate

tickers = sys.argv[1].split(",")
yf = YFinanceProvider()
hist = yf.history(tickers, "2y")
full = yf.history(tickers, "max")
for t in tickers:
    df = hist.get(t)
    if df is None:
        print(t, "keine Daten"); continue
    res = evaluate(df, {"currency": "EUR", "market_cap_usd": 5e9}, ticker=t)
    f = full.get(t)
    ath = {"p": float(f["Close"].max()), "date": str(f["Close"].idxmax().date()), "full": True} if f is not None else None
    a = analyze(df, res, ath)
    print(f"\n{t}: Kurs {a['c']:.2f}, ATR {a['atr']:.2f}")
    for z in a["tps"].get("levels", []):
        print(f"  Stufe {z['p']:.2f}–{z['hi']:.2f}  ({z['src']})  +{z['pct']*100:.1f} %  3M {z['p3m']:.0%}  6M {z['p6m']:.0%}" + ("  = ATH" if z.get("ath") else ""))
    if "ath" in a["tps"]:
        z = a["tps"]["ath"]; print(f"  ATH {z['p']:.2f} vom {z['date']}  +{z['pct']*100:.1f} %  3M {z['p3m']:.0%}")
