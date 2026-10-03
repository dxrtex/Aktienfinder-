from aktienfinder.markets import region_of, usd_factor


def test_region_and_fx():
    assert region_of("AAPL") == "us" and usd_factor("AAPL") == 1.0
    assert region_of("BRK-B") == "us"
    assert region_of("IFX.DE") == "europe" and usd_factor("IFX.DE") > 1
    assert region_of("7203.T") == "global" and usd_factor("7203.T") < 0.01
    assert usd_factor("VOD.L") < 0.02          # London notiert in Pence


def test_china_and_new_markets():
    assert region_of("600519.SS") == "global" and region_of("000858.SZ") == "global"
    assert region_of("2222.SR") == "global" and region_of("ETE.AT") == "europe"
