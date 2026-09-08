"""Запуск Claude Code в headless-режиме и сессии на пользователя."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path

from .config import Config

log = logging.getLogger("marketeer.claude")

ALLOWED_TOOLS = "Read,Glob,Grep,Write,Edit,Bash(python3 .claude/skills/*),Bash(ls *)"


class Sessions:
    """user_id → session_id Claude Code, с истечением по тишине."""

    def __init__(self, path: Path, ttl_hours: float, now=time.time):
        self.path, self.ttl, self.now = path, ttl_hours * 3600, now
        self._d: dict[str, dict] = self._load()

    def _load(self) -> dict:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def _save(self) -> None:
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._d, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(self.path)

    def get(self, user_id: int) -> str | None:
        e = self._d.get(str(user_id))
        if not e:
            return None
        if self.now() - float(e.get("last", 0)) > self.ttl:
            self._d.pop(str(user_id), None)
            self._save()
            return None
        return e.get("session_id")

    def set(self, user_id: int, session_id: str) -> None:
        self._d[str(user_id)] = {"session_id": session_id, "last": self.now()}
        self._save()

    def reset(self, user_id: int) -> bool:
        had = self._d.pop(str(user_id), None) is not None
        if had:
            self._save()
        return had


@dataclass
class ClaudeResult:
    text: str
    ok: bool
    kind: str = ""  # "", "timeout", "auth", "session", "error"
    session_id: str | None = None


class ClaudeRunner:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        cfg.data_dir.mkdir(parents=True, exist_ok=True)
        self.sessions = Sessions(cfg.data_dir / "sessions.json", cfg.session_ttl_hours)
        self._sem = asyncio.Semaphore(cfg.max_concurrent)
        self.active = 0

    def build_cmd(self, prompt: str, session_id: str | None) -> list[str]:
        cmd = [
            "claude", "-p", prompt,
            "--model", self.cfg.model,
            "--output-format", "json",
            "--max-turns", str(self.cfg.max_turns),
            "--permission-mode", "acceptEdits",
            "--allowedTools", ALLOWED_TOOLS,
            "--add-dir", str(self.cfg.data_dir),
        ]
        if session_id:
            cmd += ["--resume", session_id]
        return cmd

    async def run(self, prompt: str, user_id: int) -> ClaudeResult:
        async with self._sem:
            self.active += 1
            try:
                sid = self.sessions.get(user_id)
                res = await self._exec(prompt, sid)
                if not res.ok and res.kind == "session" and sid:
                    log.info("Сессия %s не найдена, начинаю новую для %s", sid, user_id)
                    self.sessions.reset(user_id)
                    res = await self._exec(prompt, None)
                if res.session_id:
                    self.sessions.set(user_id, res.session_id)
                return res
            finally:
                self.active -= 1

    async def _exec(self, prompt: str, session_id: str | None) -> ClaudeResult:
        cmd = self.build_cmd(prompt, session_id)
        log.info("claude -p: model=%s resume=%s len=%d", self.cfg.model, session_id or "-", len(prompt))
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd, cwd=str(self.cfg.repo_dir), env=os.environ.copy(),
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            )
        except OSError as e:
            return ClaudeResult(f"Не могу запустить claude: {e}", False, "error")
        try:
            out, err = await asyncio.wait_for(proc.communicate(), timeout=self.cfg.timeout_sec)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            return ClaudeResult(f"Не уложился в {self.cfg.timeout_sec // 60} минут, прервал.", False, "timeout")

        o = out.decode(errors="replace")
        e = err.decode(errors="replace")
        if proc.returncode != 0:
            blob = (e + "\n" + o).lower()
            if session_id and "session" in blob and ("not found" in blob or "no conversation" in blob or "does not exist" in blob):
                return ClaudeResult(o, False, "session")
            kind = "auth" if any(k in blob for k in ("authentication", "unauthorized", "not logged in", "oauth", "401")) else "error"
            log.error("claude rc=%s err=%s out=%s", proc.returncode, e[:500], o[:500])
            return ClaudeResult((e or o).strip()[:1500], False, kind)

        try:
            data = json.loads(o)
        except ValueError:
            return ClaudeResult(o.strip()[:3500], True)
        text = (data.get("result") or "").strip()
        sid = data.get("session_id")
        if data.get("is_error"):
            return ClaudeResult(text or str(data.get("subtype", "ошибка")), False, "error", sid)
        log.info("claude ok: turns=%s duration_ms=%s", data.get("num_turns"), data.get("duration_ms"))
        return ClaudeResult(text, True, "", sid)
