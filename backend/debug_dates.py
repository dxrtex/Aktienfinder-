"""Diagnose: US-Termine über curl_cffi (Browser-Imitation) – nur zum Testen"""
import re

from curl_cffi import requests as cr

for url in ["https://www.bls.gov/schedule/news_release/cpi.htm", "https://www.bls.gov/schedule/news_release/empsit.htm",
            "https://fred.stlouisfed.org/releases/calendar?rid=10&y=2026",
            "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"]:
    try:
        r = cr.get(url, impersonate="chrome", timeout=40)
        html = r.text
        cells = re.findall(r"<td[^>]*>\s*((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2},\s+\d{4})", html)
        print(url, r.status_code, len(html), cells[:24])
        if not cells:
            i = html.find("2026"); print(re.sub(r"\s+", " ", html[max(0, i - 200):i + 800]))
    except Exception as exc:
        print(url, "FEHLER", repr(exc))
