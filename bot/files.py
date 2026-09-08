"""Входящие файлы: скачать в uploads/, docx перевести в markdown, описать для промпта."""
from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import time
from pathlib import Path

log = logging.getLogger("marketeer.files")

_UNSAFE = re.compile(r"[^\w.\-]+")


def safe_name(name: str | None, default: str = "file") -> str:
    base = os.path.basename(name or "")
    s = _UNSAFE.sub("_", base).strip("._") or default
    return s[:80]


async def save_incoming(bot, file_id: str, filename: str | None, uploads: Path, max_mb: int) -> Path | None:
    """Скачивает файл Telegram. None, если он больше лимита."""
    uploads.mkdir(parents=True, exist_ok=True)
    tg_file = await bot.get_file(file_id)
    size = tg_file.file_size or 0
    if size > max_mb * 1024 * 1024:
        return None
    dest = uploads / f"{int(time.time())}_{safe_name(filename)}"
    await tg_file.download_to_drive(custom_path=str(dest))
    log.info("Скачал %s → %s (%s байт)", file_id, dest, size)
    return dest


def convert_docx(path: Path) -> Path | None:
    """docx → markdown через pandoc, если он есть. Иначе None."""
    if path.suffix.lower() != ".docx" or not shutil.which("pandoc"):
        return None
    out = path.with_suffix(".md")
    try:
        subprocess.run(["pandoc", str(path), "-t", "gfm", "--wrap=none", "-o", str(out)],
                       check=True, timeout=120, capture_output=True)
    except (subprocess.SubprocessError, OSError) as e:
        log.warning("pandoc %s: %s", path, e)
        return None
    return out


def describe_incoming(paths: list[Path]) -> str:
    """Строки для служебной приписки к промпту."""
    lines = []
    for p in paths:
        line = f"- {p}"
        if p.suffix.lower() == ".docx":
            md = convert_docx(p)
            line += f" (markdown-версия: {md})" if md else " (docx; pandoc недоступен, читай как есть)"
        lines.append(line)
    return "\n".join(lines)
