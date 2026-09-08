"""Каталоги результатов: по одному на запуск, чистка по сроку."""
from __future__ import annotations

import logging
import secrets
import shutil
import time
from pathlib import Path

log = logging.getLogger("marketeer.outputs")

IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp"}


class OutputStore:
    def __init__(self, root: Path, ttl_days: int):
        self.root, self.ttl_days = root, ttl_days
        self.root.mkdir(parents=True, exist_ok=True)

    def new_run(self) -> Path:
        name = time.strftime("%Y%m%d-%H%M%S") + "-" + secrets.token_hex(2)
        d = self.root / name
        d.mkdir(parents=True, exist_ok=False)
        return d

    @staticmethod
    def collect(run_dir: Path) -> list[Path]:
        """Файлы для отправки: без скрытых (черновики начинаются с точки)."""
        if not run_dir.is_dir():
            return []
        files = [p for p in run_dir.rglob("*") if p.is_file() and not any(part.startswith(".") for part in p.relative_to(run_dir).parts)]
        return sorted(files)

    def cleanup(self, *extra_dirs: Path) -> None:
        cleanup_old(self.root, self.ttl_days)
        for d in extra_dirs:
            cleanup_old(d, self.ttl_days)


def cleanup_old(directory: Path, ttl_days: int) -> None:
    if ttl_days <= 0 or not directory.is_dir():
        return
    cutoff = time.time() - ttl_days * 86400
    for p in directory.iterdir():
        try:
            if p.stat().st_mtime >= cutoff:
                continue
            if p.is_dir():
                shutil.rmtree(p, ignore_errors=True)
            else:
                p.unlink(missing_ok=True)
            log.info("Удалил старое: %s", p)
        except OSError as e:
            log.warning("cleanup %s: %s", p, e)
