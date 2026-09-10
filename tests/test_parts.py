from bot.telegram import PartsBuffer

KEY = (-100, 7)


def test_mention_first_then_tail_parts():
    b = PartsBuffer(before_sec=8, after_sec=3)
    assert b.start(KEY, "@бот статья по плану, часть 1", now=100.0) is True
    assert b.note(KEY, "часть 2", now=100.5) is True
    assert b.note(KEY, "часть 3", now=101.0) is True
    assert b.count(KEY) == 3
    assert b.finish(KEY) == "@бот статья по плану, часть 1\nчасть 2\nчасть 3"
    assert b.count(KEY) == 0


def test_mention_in_last_part_collects_preceding():
    b = PartsBuffer(before_sec=8, after_sec=3)
    assert b.note(KEY, "часть 1", now=50.0) is False
    assert b.note(KEY, "часть 2", now=50.8) is False
    assert b.start(KEY, "часть 3 @бот сделай пост", now=51.5) is True
    assert b.finish(KEY) == "часть 1\nчасть 2\nчасть 3 @бот сделай пост"


def test_old_chatter_is_not_glued():
    b = PartsBuffer(before_sec=8, after_sec=3)
    b.note(KEY, "старое сообщение", now=10.0)
    assert b.start(KEY, "@бот пост", now=30.0) is True
    assert b.finish(KEY) == "@бот пост"


def test_addressed_parts_join_running_collection():
    b = PartsBuffer()
    assert b.start(KEY, "ответ боту, часть 1", now=0.0) is True
    assert b.start(KEY, "ответ боту, часть 2", now=0.4) is False
    assert b.finish(KEY) == "ответ боту, часть 1\nответ боту, часть 2"


def test_other_user_is_separate():
    b = PartsBuffer()
    b.start(KEY, "@бот запрос", now=0.0)
    assert b.note((-100, 8), "чужой текст", now=0.1) is False
    assert b.finish(KEY) == "@бот запрос"
