import asyncio
import json
from types import SimpleNamespace as NS

from bot.config import Config
from bot.telegram import MarketeerBot


def make_cfg(tmp_path, chat_id=-5592510419):
    return Config(token="x", chat_id=chat_id, user_ids=set(), repo_dir=tmp_path, data_dir=tmp_path / "data")


def test_saved_migration_applies_on_start(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    (data / "chat_migration.json").write_text(json.dumps({"from": -5592510419, "to": -1003939200514}))
    bot = MarketeerBot(make_cfg(tmp_path))
    assert bot.cfg.chat_id == -1003939200514


def test_saved_migration_ignored_when_env_already_updated(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    (data / "chat_migration.json").write_text(json.dumps({"from": -5592510419, "to": -1003939200514}))
    bot = MarketeerBot(make_cfg(tmp_path, chat_id=-777))
    assert bot.cfg.chat_id == -777


def test_on_migrate_switches_chat_and_persists(tmp_path):
    bot = MarketeerBot(make_cfg(tmp_path))
    sent = []

    async def fake_announce(text):
        sent.append(text)

    bot._announce = fake_announce
    msg = NS(chat=NS(id=-5592510419), migrate_to_chat_id=-1003939200514, migrate_from_chat_id=None)
    asyncio.run(bot.on_migrate(NS(message=msg), None))
    assert bot.cfg.chat_id == -1003939200514
    assert json.loads((tmp_path / "data" / "chat_migration.json").read_text()) == {"from": -5592510419, "to": -1003939200514}
    assert sent and "-1003939200514" in sent[0]
