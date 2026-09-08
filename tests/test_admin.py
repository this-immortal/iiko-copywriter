import asyncio
from types import SimpleNamespace as NS

from bot.config import Config
from bot.telegram import MarketeerBot, is_admin


def test_is_admin():
    cfg = NS(admin_ids={7})
    assert is_admin(7, cfg)
    assert not is_admin(8, cfg)
    assert not is_admin(None, cfg)
    assert not is_admin(7, NS(admin_ids=set()))


def test_update_rejected_for_non_admin(tmp_path):
    cfg = Config(token="x", chat_id=-100, user_ids=set(), admin_ids={7}, repo_dir=tmp_path, data_dir=tmp_path / "d")
    bot = MarketeerBot(cfg)
    replies = []

    async def reply_text(text, **kw):
        replies.append(text)

    update = NS(effective_chat=NS(id=-100), effective_user=NS(id=8), message=NS(reply_text=reply_text))
    asyncio.run(bot.cmd_update(update, None))
    assert replies == ["Обновлять бота могут только его администраторы."]
    assert bot.update_requested is False


def test_config_reads_admin_ids():
    cfg = Config.from_env({"TELEGRAM_BOT_TOKEN": "x", "ALLOWED_CHAT_ID": "-1", "ADMIN_USER_IDS": "1, 2"})
    assert cfg.admin_ids == {1, 2}
    assert cfg.user_ids == set()
