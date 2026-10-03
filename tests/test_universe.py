import pandas as pd

from aktienfinder import universe
from aktienfinder.universe import IndexSource, _normalize

DAX = IndexSource("DAX", "", "europe", ".DE")
FTSE = IndexSource("FTSE", "", "europe", ".L", dot_to_dash=True)
HK = IndexSource("HSI", "", "global", ".HK", zero_pad=4)
MIXED = IndexSource("SX5E", "", "europe", "")


def test_normalize():
    assert _normalize("ADS", DAX) == "ADS.DE"
    assert _normalize("ADS.DE", DAX) == "ADS.DE"
    assert _normalize("XETRA: ifx", DAX) == "IFX.DE"
    assert _normalize("BT.A", FTSE) == "BT-A.L"
    assert _normalize("5", HK) == "0005.HK"
    assert _normalize("SEHK: 700", HK) == "0700.HK"
    assert _normalize("SAP.DE", MIXED) == "SAP.DE"
    assert _normalize("SAP", MIXED) is None
    assert _normalize(float("nan"), DAX) is None
    assert _normalize("ADS[1]", DAX) == "ADS.DE"


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
    df = universe.us_all()
    assert list(df["ticker"]) == ["AAPL", "BRK-B"]


def test_build_survives_failing_source(monkeypatch):
    monkeypatch.setattr(universe, "us_all", lambda: pd.DataFrame(
        {"ticker": ["AAPL", "AAPL"], "name": ["Apple", "Apple"], "region": "us", "source": "x"}))
    def boom(src):
        raise RuntimeError("offline")
    monkeypatch.setattr(universe, "index_members", boom)
    df, log = universe.build(["us", "europe"])
    assert list(df["ticker"]) == ["AAPL"]
    assert any("FEHLER" in line for line in log)
    assert log[-1] == "GESAMT: 1 Aktien"


def test_normalize_keeps_foreign_home_exchange():
    assert _normalize("AIR.PA", DAX) == "AIR.PA"     # Airbus im DAX, Heimatbörse Paris
    assert _normalize("MT.AS", IndexSource("CAC", "", "europe", ".PA")) == "MT.AS"


def test_screener_keeps_only_home_exchange_and_top_n(monkeypatch):
    import sys, types
    from aktienfinder import markets
    calls = []

    def screen(query, offset, size, sortField, sortAsc):
        calls.append(offset)
        quotes = [{"symbol": s, "longName": s, "quoteType": "EQUITY"}
                  for s in ["SAP.DE", "SAP.F", "SIE.DE", "ALV.SG", "DTE.DE", "BAS.DE"]]
        return {"quotes": quotes if offset == 0 else [], "total": 6}

    class EquityQuery:
        def __init__(self, *a):
            pass

    fake = types.SimpleNamespace(screen=screen, EquityQuery=EquityQuery)
    monkeypatch.setitem(sys.modules, "yfinance", fake)
    monkeypatch.setattr(universe, "MARKETS", [markets.Market("de", (".DE",), "europe", 1.1, 3)])
    df = universe.screener("europe")
    assert list(df["ticker"]) == ["SAP.DE", "SIE.DE", "DTE.DE"]
