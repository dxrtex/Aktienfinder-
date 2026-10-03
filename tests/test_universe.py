import sys
import types

import pandas as pd

from aktienfinder import markets, universe


def _fake_yf(monkeypatch, pages):
    def screen(query, offset, size, sortField, sortAsc):
        page = pages.get(offset, [])
        return {"quotes": page, "total": sum(len(p) for p in pages.values())}

    class EquityQuery:
        def __init__(self, *a):
            pass

    monkeypatch.setitem(sys.modules, "yfinance", types.SimpleNamespace(screen=screen, EquityQuery=EquityQuery))


def q(sym, cap, cur="EUR", exchange="GER", qt="EQUITY"):
    return {"symbol": sym, "longName": sym, "marketCap": cap, "currency": cur, "exchange": exchange, "quoteType": qt}


def test_screener_home_exchange_and_min_cap(monkeypatch):
    _fake_yf(monkeypatch, {0: [q("SAP.DE", 2e11), q("SAP.F", 2e11), q("SIE.DE", 1.5e11),
                               q("RHM.DE", 4e10), q("SMALL.DE", 1e9), q("LATE.DE", 3e9)]})
    monkeypatch.setattr(universe, "MARKETS", [markets.Market("de", (".DE",), "europe", 1.1, 100)])
    df = universe.screener("europe", min_cap_usd=2e9)
    # Zweitlisting SAP.F verworfen, Abbruch beim ersten Wert unter 2 Mrd. $
    assert list(df["ticker"]) == ["SAP.DE", "SIE.DE", "RHM.DE"]
    assert df["market_cap_usd"].iloc[0] == round(2e11 * 1.10)


def test_screener_us_skips_otc_and_converts_pence(monkeypatch):
    _fake_yf(monkeypatch, {0: [q("NVDA", 4e12, "USD", "NMS"), q("NSRGY", 3e11, "USD", "PNK"),
                               q("BRK-B", 1e12, "USD", "NYQ")]})
    monkeypatch.setattr(universe, "MARKETS", [markets.Market("us", ("",), "us", 1.0, 100)])
    assert list(universe.screener("us")["ticker"]) == ["NVDA", "BRK-B"]
    # London: Kurs in Pence, Börsenwert in Pfund
    assert markets.market_cap_usd(1e10, "GBp") == 1e10 * 1.30
    assert markets.market_cap_usd(None, "USD") is None


def test_us_all_filters_non_common(monkeypatch):
    text = "\n".join([
        "Nasdaq Traded|Symbol|Security Name|Listing Exchange|Market Category|ETF|Round Lot Size|Test Issue|Financial Status|CQS Symbol|NASDAQ Symbol|NextShares",
        "Y|AAPL|Apple Inc. - Common Stock|Q|Q|N|100|N|N||AAPL|N",
        "Y|BRK.B|Berkshire Hathaway Inc. Class B|N| |N|100|N||BRK.B|BRK.B|N",
        "Y|SPY|SPDR S&P 500 ETF Trust|P| |Y|100|N||SPY|SPY|N",
        "Y|ABCW|Abc Corp - Warrants|Q|Q|N|100|N|N||ABCW|N",
        "Y|ZZZT|Test Corp|Q|Q|N|100|Y|N||ZZZT|N",
        "Y|PFE$A|Some Preferred|N| |N|100|N||PFE$A|PFE$A|N",
        "File Creation Time: 1003202600:00|||||||||||",
    ])
    monkeypatch.setattr(universe, "_get", lambda url: text)
    assert list(universe.us_all()["ticker"]) == ["AAPL", "BRK-B"]


def test_build_falls_back_for_us_and_survives_errors(monkeypatch):
    def screener(region, min_cap):
        raise RuntimeError("offline")
    monkeypatch.setattr(universe, "screener", screener)
    monkeypatch.setattr(universe, "us_all", lambda: pd.DataFrame(
        {"ticker": ["AAPL", "AAPL"], "name": "Apple", "region": "us", "source": "x", "market_cap_usd": None}))
    df, log = universe.build(["us", "europe"])
    assert list(df["ticker"]) == ["AAPL"]
    assert sum("FEHLER" in line for line in log) == 2
    assert log[-1] == "GESAMT: 1 Aktien"


def test_company_key_and_dedupe(monkeypatch):
    assert universe.company_key("Lundin Mining Corporation") == universe.company_key("Lundin Mining Corp.")
    assert universe.company_key("Alphabet Inc.") == universe.company_key("Alphabet Inc. Class C")
    assert universe.company_key("SAP SE") != universe.company_key("Siemens AG")

    def screener(region, min_cap):
        rows = {"us": [("GOOGL", "Alphabet Inc."), ("AVGO", "Broadcom Inc.")],
                "europe": [("LUMI.ST", "Lundin Mining Corporation")],
                "global": [("LUN.TO", "Lundin Mining Corp."), ("GOOG.TO", "Alphabet Inc."),
                           ("AVGO34.SA", "Broadcom Inc."), ("7203.T", "Toyota Motor Corporation")]}[region]
        return pd.DataFrame([(t, n, region, "x", 1e10) for t, n in rows], columns=universe.COLUMNS)
    monkeypatch.setattr(universe, "screener", screener)
    df, log = universe.build(["us", "europe", "global"])
    assert list(df["ticker"]) == ["GOOGL", "AVGO", "LUMI.ST", "7203.T"]
    assert "Doppelte Firmen entfernt: 3" in log


def test_screener_skips_trusts(monkeypatch):
    _fake_yf(monkeypatch, {0: [dict(q("U-UN.TO", 5e9, "CAD", "TOR"), longName="Sprott Physical Uranium Trust"), q("SHOP.TO", 1e11, "CAD", "TOR")]})
    monkeypatch.setattr(universe, "MARKETS", [markets.Market("ca", (".TO",), "global", 0.73, 100)])
    q0 = universe.screener("global")
    assert "U-UN.TO" not in list(q0["ticker"])
