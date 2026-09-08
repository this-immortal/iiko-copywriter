from bot.claude_runner import Sessions


def test_session_expires_after_ttl(tmp_path):
    clock = {"t": 1000.0}
    s = Sessions(tmp_path / "s.json", ttl_hours=8, now=lambda: clock["t"])
    s.set(7, "sid-1")
    assert s.get(7) == "sid-1"
    clock["t"] += 7 * 3600
    assert s.get(7) == "sid-1"
    clock["t"] += 2 * 3600
    assert s.get(7) is None


def test_sessions_persist_and_reset(tmp_path):
    p = tmp_path / "s.json"
    Sessions(p, 8).set(1, "abc")
    again = Sessions(p, 8)
    assert again.get(1) == "abc"
    assert again.reset(1) is True
    assert again.reset(1) is False
    assert Sessions(p, 8).get(1) is None
