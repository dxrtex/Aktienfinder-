"""Diagnose: welche Quellen liefern Termine? (nur zum Testen)"""
import re
import traceback
import urllib.request

import pandas as pd
import yfinance as yf

from .macro import UA

print("yfinance", yf.__version__)
for t in ["SAP.DE", "RHM.DE", "NOVO-B.CO", "AIR.PA", "SAP", "NVO"]:
    tk = yf.Ticker(t)
    for name, fn in (("calendar", lambda: tk.calendar), ("earnings_dates", lambda: tk.get_earnings_dates(limit=6)),
                     ("info", lambda: {k: tk.info.get(k) for k in ("earningsTimestamp", "earningsTimestampStart", "exDividendDate")})):
        try:
            v = fn()
            if isinstance(v, pd.DataFrame):
                v = v.head(4).to_string()
            print(f"{t} {name}: {str(v)[:300]}")
        except Exception as exc:
            print(f"{t} {name}: FEHLER {exc!r}"[:300])
for url in ["https://fred.stlouisfed.org/releases/calendar?rid=10&y=2026", "https://fred.stlouisfed.org/releases/calendar?rid=50&y=2026",
            "https://www.bls.gov/schedule/news_release/cpi.htm"]:
    try:
        html = urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30).read().decode("utf-8", "replace")
        dates = re.findall(r"(January|February|March|April|May|June|July|August|September|October|November|December) (\d{1,2}), (\d{4})", html)
        print(url, len(html), dates[:30])
        i = html.find("2026"); print(re.sub(r"\s+", " ", html[i - 300:i + 600]))
    except Exception as exc:
        print(url, "FEHLER", repr(exc), getattr(exc, "code", ""))
