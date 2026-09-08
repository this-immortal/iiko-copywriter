from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _int(env: dict, name: str, default: int) -> int:
    v = env.get(name, "").strip()
    return int(v) if v else default


def _float(env: dict, name: str, default: float) -> float:
    v = env.get(name, "").strip()
    return float(v) if v else default


def _ids(s: str) -> set[int]:
    return {int(x) for x in s.split(",") if x.strip()}


@dataclass
class Config:
    token: str
    chat_id: int
    user_ids: set[int]
    repo_dir: Path
    data_dir: Path
    admin_ids: set[int] = field(default_factory=set)
    model: str = "claude-opus-5"
    max_turns: int = 30
    timeout_sec: int = 900
    session_ttl_hours: float = 8.0
    max_concurrent: int = 2
    output_ttl_days: int = 7
    update_check_min: int = 15
    git_branch: str = "main"
    max_upload_mb: int = 20
    max_send_mb: int = 50
    log_path: str = ""
    extra: dict = field(default_factory=dict)

    @classmethod
    def from_env(cls, env: dict | None = None) -> "Config":
        env = dict(os.environ if env is None else env)
        missing = [k for k in ("TELEGRAM_BOT_TOKEN", "ALLOWED_CHAT_ID") if not env.get(k)]
        if missing:
            raise SystemExit("Не заданы переменные: " + ", ".join(missing))
        # Пустой ALLOWED_USER_IDS = отвечаем всем участникам чата.
        user_ids = _ids(env.get("ALLOWED_USER_IDS", ""))
        return cls(
            token=env["TELEGRAM_BOT_TOKEN"],
            chat_id=int(env["ALLOWED_CHAT_ID"]),
            user_ids=user_ids,
            admin_ids=_ids(env.get("ADMIN_USER_IDS", "")),
            repo_dir=Path(env.get("REPO_DIR", "/work/repo")),
            data_dir=Path(env.get("DATA_DIR", "/work/data")),
            model=env.get("CLAUDE_MODEL", "claude-opus-5"),
            max_turns=_int(env, "CLAUDE_MAX_TURNS", 30),
            timeout_sec=_int(env, "CLAUDE_TIMEOUT_SEC", 900),
            session_ttl_hours=_float(env, "SESSION_TTL_HOURS", 8.0),
            max_concurrent=_int(env, "MAX_CONCURRENT", 2),
            output_ttl_days=_int(env, "OUTPUT_TTL_DAYS", 7),
            update_check_min=_int(env, "UPDATE_CHECK_MIN", 15),
            git_branch=env.get("GIT_BRANCH", "main"),
            max_upload_mb=_int(env, "MAX_UPLOAD_MB", 20),
            max_send_mb=_int(env, "MAX_SEND_MB", 50),
            log_path=env.get("BOT_LOG", ""),
        )

    def describe(self) -> str:
        """Конфиг для глаз: без токена, с проверкой каталогов."""
        rows = [
            ("chat_id", self.chat_id),
            ("user_ids", ", ".join(str(u) for u in sorted(self.user_ids)) or "все участники чата"),
            ("admin_ids", ", ".join(str(u) for u in sorted(self.admin_ids)) or "не заданы (/update недоступна)"),
            ("repo_dir", f"{self.repo_dir} ({'есть' if self.repo_dir.is_dir() else 'нет'})"),
            ("data_dir", f"{self.data_dir} ({'есть' if self.data_dir.is_dir() else 'нет'})"),
            ("model", self.model),
            ("max_turns", self.max_turns),
            ("timeout_sec", self.timeout_sec),
            ("session_ttl_hours", self.session_ttl_hours),
            ("max_concurrent", self.max_concurrent),
            ("output_ttl_days", self.output_ttl_days),
            ("update_check_min", self.update_check_min),
            ("git_branch", self.git_branch),
            ("token", "задан" if self.token else "нет"),
            ("CLAUDE_CODE_OAUTH_TOKEN", "задан" if os.environ.get("CLAUDE_CODE_OAUTH_TOKEN") else "нет"),
            ("GEMINI_API_KEY", "задан" if os.environ.get("GEMINI_API_KEY") else "нет"),
            ("YANDEX_API_KEY", "задан" if os.environ.get("YANDEX_API_KEY") else "нет"),
        ]
        return "\n".join(f"{k:<24} {v}" for k, v in rows)
