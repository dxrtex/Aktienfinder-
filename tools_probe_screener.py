"""Einmaliger Test: Wie verhält sich der Yahoo-Screener? (Ergebnisgrenze, Währung des Börsenwerts)"""
import yfinance as yf
from yfinance import EquityQuery as Q

def total(q):
    r = yf.screen(q, offset=0, size=5, sortField="intradaymarketcap", sortAsc=False)
    qs = r.get("quotes", [])
    first = qs[0] if qs else {}
    return r.get("total"), first.get("symbol"), first.get("marketCap"), first.get("currency")

for region in ("us", "de", "jp", "gb"):
    print(region, "nur Region:", total(Q("eq", ["region", region])))
    print(region, "Börsenwert >= 2e9:", total(Q("and", [Q("eq", ["region", region]), Q("gte", ["intradaymarketcap", 2e9])])))
    print(region, "Börsenwert >= 3e11:", total(Q("and", [Q("eq", ["region", region]), Q("gte", ["intradaymarketcap", 3e11])])))

q = Q("and", [Q("eq", ["region", "us"]), Q("gte", ["intradaymarketcap", 2e9])])
for off in (0, 250, 500, 750, 1000, 1250, 1500, 2000, 3000):
    r = yf.screen(q, offset=off, size=250, sortField="intradaymarketcap", sortAsc=False)
    qs = r.get("quotes", [])
    print("US offset", off, "->", len(qs), "Treffer; letzter:", (qs[-1].get("symbol"), qs[-1].get("marketCap"), qs[-1].get("exchange")) if qs else None)
for ex in ("NMS", "NYQ", "NGM", "NCM", "ASE", "PCX", "BTS"):
    print("US Börse", ex, total(Q("and", [Q("eq", ["exchange", ex]), Q("gte", ["intradaymarketcap", 2e9])])))
for t in ("QBTS", "TUI1.DE"):
    info = yf.Ticker(t).fast_info
    print(t, "marketCap", getattr(info, "market_cap", None), getattr(info, "currency", None), getattr(info, "exchange", None))
