"""Проверка новых коммитов. Само обновление делает супервизор по коду выхода 75."""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path

log = logging.getLogger("marketeer.updater")

EXIT_UPDATE = 75


async def _git(*args: str, cwd: Path, timeout: int = 60) -> str | None:
    try:
        proc = await asyncio.create_subprocess_exec(
            "git", *args, cwd=str(cwd),
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except (asyncio.TimeoutError, OSError) as e:
        log.warning("git %s: %s", " ".join(args), e)
        return None
    if proc.returncode != 0:
        log.warning("git %s rc=%s: %s", " ".join(args), proc.returncode, err.decode(errors="replace").strip()[:300])
        return None
    return out.decode(errors="replace").strip()


class Updater:
    def __init__(self, repo_dir: Path, branch: str = "main", remote: str = "origin"):
        self.repo_dir, self.branch, self.remote = repo_dir, branch, remote

    async def local_commit(self) -> str:
        return await _git("rev-parse", "HEAD", cwd=self.repo_dir) or "unknown"

    async def remote_commit(self) -> str | None:
        out = await _git("ls-remote", self.remote, f"refs/heads/{self.branch}", cwd=self.repo_dir, timeout=90)
        if not out:
            return None
        return out.split()[0]

    async def check(self) -> tuple[str, str | None]:
        """(локальный коммит, удалённый коммит или None, если не достучались)."""
        return await self.local_commit(), await self.remote_commit()


def short(commit: str | None) -> str:
    return (commit or "unknown")[:7]
