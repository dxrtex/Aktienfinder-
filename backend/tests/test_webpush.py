from backend import push, webpush


def test_rfc8291_vector():
    eph = webpush.private_key("yfWPiYE-n46HLnH0KqZOF1fJJU3MYrct3AELtAQ-oRw")
    body = webpush.encrypt(b"When I grow up, I want to be a watermelon",
                           "BCVxsr7N_eNgVRqvHtD0zTZsEc6-VV-JvLexhqUzORcxaOzi6-AYWXvTBHm4bjyPjs7Vd8pZGH6SRpkNtoIAiw4",
                           "BTBZMqHH6r4Tts7J_aSIgg", salt=webpush.b64d("DGv6ra1nlYgDCS1FRnbzlw"), eph=eph)
    assert webpush.b64e(body) == ("DGv6ra1nlYgDCS1FRnbzlwAAEABBBP4z9KsN6nGRTbVYI_c7VJSPQTBtkgcy27mlmlMoZIIgDll6e3vCYLocInmYWAmS6Tlz"
                                  "AC8wEqKK6PBru3jl7A_yl95bQpu6cVPTpK4Mqgkf1CXztLVBSt2Ks3oZwbuwXPXLWyouBWLVWGNWQexSgSxsj_Qulcy4a-fN")


def test_messages():
    rows = [{"ticker": "AAA", "name": "Alpha", "passed": True, "score": 80, "in_watchlist": True},
            {"ticker": "BBB", "name": "Beta", "passed": False, "score": 0, "tr": {"ok": True, "top": True, "chk": {"p": .62}}}]
    search = {"CCC": {"c": 100, "n": "Gamma"}}
    dev = {"m": ["BBB"], "d": [{"t": "CCC", "dir": "long", "ko": 95}]}
    ev = [{"kind": "earnings", "ticker": "AAA", "days": 1, "name": "Alpha"}]
    msgs = push.messages(rows, {"hit": [], "trend": []}, {"regime": {"label": "Rückenwind"}}, ev, search, dev)
    titles = [m["title"] for m in msgs]
    assert titles[0].startswith("⚠️") and "Gamma" in msgs[0]["body"]
    assert "Alpha ist jetzt Treffer" in msgs[1]["body"] and "Check 62 %" in msgs[1]["body"] and "Quartalszahlen" in msgs[1]["body"]
    assert "1 neue Treffer" in msgs[2]["body"] and "Trend Top" in msgs[2]["body"]
