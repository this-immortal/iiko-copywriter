"""Обмен с супервизором (deploy/entrypoint.sh) через файлы в каталоге данных."""
from __future__ import annotations

import json
import logging
from pathlib import Path

log = logging.getLogger("marketeer.state")

STATE_FILE = "state.json"


def read_and_clear_state(data_dir: Path) -> dict | None:
    """Супервизор пишет state.json после обновления или отката; бот читает один раз."""
    p = data_dir / STATE_FILE
    if not p.is_file():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        log.warning("state.json не читается: %s", e)
        data = None
    try:
        p.unlink()
    except OSError:
        pass
    return data if isinstance(data, dict) else None


def format_state(state: dict) -> str | None:
    event = state.get("event")
    commit = state.get("commit", "?")
    prev = state.get("prev", "?")
    error = state.get("error", "")
    if event == "updated":
        return f"Обновился: {prev} → {commit}."
    if event == "rolled_back":
        return f"Новая версия {prev} не запустилась ({error}). Откатился на {commit}."
    if event == "update_failed":
        return f"Не смог обновиться: {error}. Работаю на {commit}."
    return None
