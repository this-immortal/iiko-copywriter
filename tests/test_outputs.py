from bot.outputs import OutputStore


def test_collect_skips_hidden(tmp_path):
    store = OutputStore(tmp_path / "out", ttl_days=7)
    run = store.new_run()
    (run / "article.md").write_text("x")
    (run / ".article.draft.md").write_text("x")
    (run / "cover.png").write_bytes(b"\x89PNG")
    names = [p.name for p in store.collect(run)]
    assert names == ["article.md", "cover.png"]
