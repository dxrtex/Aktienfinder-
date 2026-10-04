"""Wichtige Markt-Termine automatisch von den offiziellen Seiten holen.

- Fed-Zinsentscheide (FOMC):          federalreserve.gov
- EZB-Zinsentscheide:                 ecb.europa.eu
- US-Inflation (CPI), Arbeitsmarkt:   bls.gov (Release-Kalender)

Jede Quelle wird einzeln versucht; schlägt eine fehl, bleiben die von Hand gepflegten Termine aus
data/macro_events.json als Ersatz. Ergebnis: Liste von {date, title, region}.
"""

from __future__ import annotations

import re
import urllib.request
from datetime import date

UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) "
                    "Version/17.0 Safari/605.1.15", "Accept-Language": "en-US,en;q=0.9"}
MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}


def _get(url: str) -> str:
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8", "replace")


def _month(name: str) -> int:
    return MONTHS[name.strip().lower()[:3]]


def fed_meetings(html: str) -> list[dict]:
    """FOMC-Sitzungen je Jahr; Zinsentscheid = letzter Sitzungstag."""
    out = []
    for block in re.split(r"(?=<h4[^>]*>\s*<a[^>]*>\s*\d{4} FOMC Meetings|<h4[^>]*>\s*\d{4} FOMC Meetings)", html):
        y = re.search(r"(\d{4}) FOMC Meetings", block)
        if not y:
            continue
        year = int(y.group(1))
        pairs = re.findall(r'fomc-meeting__month[^>]*>\s*<strong>([^<]+)</strong>.*?fomc-meeting__date[^>]*>\s*([^<]+?)\s*<',
                           block, re.S)
        for mon, days in pairs:
            nums = [int(x) for x in re.findall(r"\d+", days)]
            if not nums:
                continue
            months = [m for m in re.split(r"[/-]", mon) if m.strip()]
            m = _month(months[-1]) if len(nums) > 1 and nums[-1] < nums[0] and len(months) > 1 else _month(months[0])
            out.append({"date": date(year, m, nums[-1]).isoformat(), "title": "Fed-Zinsentscheid (FOMC)", "region": "us"})
    return out


def ecb_meetings(html: str) -> list[dict]:
    """EZB-Ratssitzungen zur Geldpolitik; Zinsentscheid = Tag mit Pressekonferenz."""
    out = []
    for d, mth, y, text in re.findall(r"(\d{1,2})/(\d{1,2})/(\d{4})\s*</dt>\s*<dd[^>]*>(.*?)</dd>", html, re.S):
        t = re.sub(r"<[^>]+>", " ", text).lower()
        if "monetary policy meeting" in t and ("day 2" in t or "press conference" in t):
            out.append({"date": date(int(y), int(mth), int(d)).isoformat(), "title": "EZB-Zinsentscheid", "region": "europe"})
    return out


def bls_releases(html: str, title: str) -> list[dict]:
    """Release-Termine aus einer BLS-Kalenderseite (z. B. „Oct. 15, 2026“)."""
    out = []
    cells = r"<td[^>]*>\s*(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\.?\s+(\d{1,2}),\s+(\d{4})"
    for mon, d, y in re.findall(cells, html):
        try:
            out.append({"date": date(int(y), _month(mon), int(d)).isoformat(), "title": title, "region": "us"})
        except ValueError:
            continue
    return out


SOURCES = (
    ("Fed", "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm", fed_meetings),
    ("EZB", "https://www.ecb.europa.eu/press/calendars/mgcgc/html/index.en.html", ecb_meetings),
    ("US-CPI", "https://www.bls.gov/schedule/news_release/cpi.htm", lambda h: bls_releases(h, "US-Inflation (CPI)")),
    ("US-Arbeitsmarkt", "https://www.bls.gov/schedule/news_release/empsit.htm",
     lambda h: bls_releases(h, "US-Arbeitsmarktbericht (Non-Farm Payrolls)")),
)


def fetch_macro_events() -> tuple[list[dict], dict[str, int]]:
    events, stats = [], {}
    for name, url, parse in SOURCES:
        try:
            found = parse(_get(url))
        except Exception as exc:
            print(f"Markt-Termine {name}: Fehler {exc!r}")
            found = []
        stats[name] = len(found)
        events += found
    uniq = {(e["date"], e["title"]): e for e in events}
    return sorted(uniq.values(), key=lambda e: e["date"]), stats
