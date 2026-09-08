from types import SimpleNamespace as NS

from bot.telegram import extract_prompt, is_authorized


def ent(type_, offset, length, user=None):
    return NS(type=type_, offset=offset, length=length, user=user)


def test_mention_at_start():
    assert extract_prompt("@iiko_bot пост про кухню", [ent("mention", 0, 9)], "iiko_bot", 1) == "пост про кухню"


def test_mention_in_middle_case_insensitive():
    text = "сделай, @IIKO_bot, пост"
    off = text.index("@")
    assert extract_prompt(text, [ent("mention", off, 9)], "iiko_bot", 1) == "сделай, , пост"


def test_no_mention_is_ignored():
    assert extract_prompt("просто болтаем", [], "iiko_bot", 1) is None


def test_other_bot_mention_is_ignored():
    assert extract_prompt("@other привет", [ent("mention", 0, 6)], "iiko_bot", 1) is None


def test_reply_to_bot_counts():
    assert extract_prompt("короче", [], "iiko_bot", 1, reply_from_id=1) == "короче"


def test_reply_to_someone_else_ignored():
    assert extract_prompt("короче", [], "iiko_bot", 1, reply_from_id=42) is None


def test_text_mention_entity():
    assert extract_prompt("бот, пост", [ent("text_mention", 0, 3, user=NS(id=1))], "iiko_bot", 1) == "бот, пост"


def test_empty_caption_with_mention_gives_empty_string():
    assert extract_prompt("@iiko_bot", [ent("mention", 0, 9)], "iiko_bot", 1) == ""


def test_authorized():
    cfg = NS(chat_id=-100, user_ids={1, 2})
    assert is_authorized(-100, 1, cfg)
    assert not is_authorized(-100, 3, cfg)
    assert not is_authorized(5, 1, cfg)
    assert not is_authorized(-100, None, cfg)
