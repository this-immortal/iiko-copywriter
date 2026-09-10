#!/usr/bin/env python3
"""Установка и обновление бота на VPS (Ubuntu) одной командой с ноутбука.

  deploy/install.py 1.2.3.4                    поставить или обновить; пароль root спросит
  deploy/install.py 1.2.3.4 -p 'пароль'        пароль параметром
  deploy/install.py 1.2.3.4 --discover         показать id чатов и людей, которых видит бот
  deploy/install.py 1.2.3.4 --status | --logs | --rollback | --rebuild | --bootstrap

Всё остальное берётся из файла .env в корне репозитория (переопределить: --env ПУТЬ):

  MARKETEER_BOT_TOKEN      токен бота от @BotFather
  MARKETEER_CHAT_ID        id группы            (узнать: --discover)
  MARKETEER_USER_IDS       необязательно: id людей через запятую, если отвечать не всем в чате
  MARKETEER_ADMIN_IDS      id администраторов бота через запятую: им доступна /update и
                           будущие команды загрузки данных и артефактов
  CLAUDE_CODE_OAUTH_TOKEN  токен подписки Claude: команда `claude setup-token`
  GEMINI_API_KEY           ключ Gemini (картинки)
  YANDEX_API_KEY           ключ Яндекса (вычитка)
  YANDEX_PROJECT_ID        id каталога Яндекс Облака
  YANDEX_PROMPT_ID         id сохранённого промпта агента-редактора Яндекса
  MARKETEER_GIT_URL        необязательно: адрес репозитория, тогда код берётся из GitHub
                           и работает самообновление. Для публичного репо достаточно
                           https://github.com/USER/REPO.git без ключей; для приватного
                           git@github.com:USER/REPO.git плюс deploy-ключ (скрипт его
                           напечатает). Без строки код заливается с ноутбука архивом.
                           (Старое имя MARKETEER_GIT_SSH тоже принимается.)
  MARKETEER_ROOT_PASSWORD  необязательно: чтобы не спрашивал пароль
  MARKETEER_HOST           необязательно: чтобы не передавать IP

Нужен только python3. Библиотека paramiko ставится сама в deploy/.venv.
"""
from __future__ import annotations

import argparse
import getpass
import hashlib
import io
import json
import os
import shlex
import subprocess
import sys
import tarfile
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
DEFAULT_ENV = str(ROOT / ".env")
BOT_USER = "iiko_copywriter"
HOME = f"/home/{BOT_USER}"
APP = f"{HOME}/app"
EXCLUDE = {".venv", "__pycache__", "outputs", "uploads", ".DS_Store", ".pytest_cache"}

REQUIRED = {
    "MARKETEER_BOT_TOKEN": "токен бота от @BotFather",
    "MARKETEER_CHAT_ID": "id группы (посмотреть: --discover)",
    "CLAUDE_CODE_OAUTH_TOKEN": "токен подписки Claude: выполните `claude setup-token`",
    "GEMINI_API_KEY": "ключ Gemini",
    "YANDEX_API_KEY": "ключ Яндекса",
    "YANDEX_PROJECT_ID": "id каталога Яндекс Облака",
    "YANDEX_PROMPT_ID": "id сохранённого промпта агента-редактора Яндекса",
}


# --- подготовка ---------------------------------------------------------------

def ensure_paramiko() -> None:
    try:
        import paramiko  # noqa: F401
        return
    except ImportError:
        pass
    venv = HERE / ".venv"
    py = venv / "bin" / "python"
    # Внутри venv sys.prefix указывает на сам venv. Сравнивать sys.executable нельзя:
    # симлинк .venv/bin/python разрешается в тот же системный интерпретатор.
    if Path(sys.prefix).resolve() == venv.resolve():
        sys.exit("paramiko не импортируется даже из deploy/.venv; удалите deploy/.venv и повторите")
    if not py.exists():
        print("→ создаю deploy/.venv и ставлю paramiko (один раз)")
        subprocess.run([sys.executable, "-m", "venv", str(venv)], check=True)
    if subprocess.run([str(py), "-c", "import paramiko"], capture_output=True).returncode != 0:
        print("→ ставлю paramiko в deploy/.venv")
        subprocess.run([str(py), "-m", "pip", "install", "-q", "paramiko"], check=True)
    os.execv(str(py), [str(py)] + sys.argv)


def load_env(path: Path) -> dict[str, str]:
    env: dict[str, str] = {}
    if not path.is_file():
        return env
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        v = v.split(" #", 1)[0].strip().strip('"').strip("'")
        env[k.strip()] = v
    return env


def missing_keys(env: dict[str, str]) -> list[str]:
    return [k for k in REQUIRED if not env.get(k)]


def server_env(env: dict[str, str]) -> str:
    rows = {
        "TELEGRAM_BOT_TOKEN": env["MARKETEER_BOT_TOKEN"],
        "ALLOWED_CHAT_ID": env["MARKETEER_CHAT_ID"],
        "ALLOWED_USER_IDS": env.get("MARKETEER_USER_IDS", ""),
        "ADMIN_USER_IDS": env.get("MARKETEER_ADMIN_IDS", ""),
        "CLAUDE_CODE_OAUTH_TOKEN": env["CLAUDE_CODE_OAUTH_TOKEN"],
        "GEMINI_API_KEY": env["GEMINI_API_KEY"],
        "YANDEX_API_KEY": env["YANDEX_API_KEY"],
        "YANDEX_PROJECT_ID": env["YANDEX_PROJECT_ID"],
        "YANDEX_PROMPT_ID": env["YANDEX_PROMPT_ID"],
        "GIT_BRANCH": env.get("MARKETEER_GIT_BRANCH", "main"),
        "CLAUDE_MODEL": env.get("CLAUDE_MODEL", "claude-opus-5"),
        "CLAUDE_MAX_TURNS": env.get("CLAUDE_MAX_TURNS", "30"),
        "CLAUDE_TIMEOUT_SEC": env.get("CLAUDE_TIMEOUT_SEC", "900"),
        "SESSION_TTL_HOURS": env.get("SESSION_TTL_HOURS", "8"),
        "UPDATE_CHECK_MIN": env.get("UPDATE_CHECK_MIN", "15"),
    }
    return "".join(f"{k}={v}\n" for k, v in rows.items())


def discover(token: str) -> None:
    """Печатает чаты и людей из getUpdates. Бот в это время не должен работать."""
    url = f"https://api.telegram.org/bot{token}/getUpdates?limit=100"
    try:
        with urllib.request.urlopen(url, timeout=20) as r:
            data = json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        if e.code == 409:
            sys.exit("Бот сейчас запущен и сам забирает сообщения (409). Остановите его или посмотрите id в его логах.")
        sys.exit(f"Telegram ответил {e.code}: {body[:300]}")
    chats: dict[int, str] = {}
    users: dict[int, str] = {}
    for upd in data.get("result", []):
        msg = upd.get("message") or upd.get("edited_message") or upd.get("channel_post") or {}
        chat = msg.get("chat")
        if chat:
            chats[chat["id"]] = chat.get("title") or chat.get("username") or chat.get("first_name") or chat.get("type", "")
        frm = msg.get("from")
        if frm and not frm.get("is_bot"):
            users[frm["id"]] = " ".join(x for x in (frm.get("first_name"), frm.get("last_name"), frm.get("username") and "@" + frm["username"]) if x)
    if not chats:
        print("Telegram ничего не отдал. Напишите в группе `/start@имя_бота` (Group Privacy в @BotFather лучше отключить) и повторите.")
        return
    print("Чаты:")
    for cid, title in chats.items():
        print(f"  MARKETEER_CHAT_ID={cid}    # {title}")
    print("Люди (нужны, только если хотите ограничить, кто даёт задания):")
    for uid, name in users.items():
        print(f"  {uid}    # {name}")
    print("Добавьте в .env MARKETEER_CHAT_ID=...; MARKETEER_USER_IDS=id1,id2 по желанию")


def local_bundle() -> bytes:
    """tar.gz рабочего дерева вместе с .git, без мусора."""
    buf = io.BytesIO()

    def keep(ti: tarfile.TarInfo):
        parts = Path(ti.name).parts
        if any(p in EXCLUDE for p in parts):
            return None
        if ti.name.startswith("./deploy/.venv") or ti.name == "./deploy/local.env":
            return None
        return ti

    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        tar.add(ROOT, arcname=".", filter=keep)
    return buf.getvalue()


def local_head() -> str:
    try:
        return subprocess.run(["git", "-C", str(ROOT), "rev-parse", "--short", "HEAD"],
                              capture_output=True, text=True, check=True).stdout.strip()
    except (subprocess.CalledProcessError, OSError):
        return "unknown"


def laptop_pubkey() -> str:
    for name in ("id_ed25519.pub", "id_rsa.pub"):
        p = Path.home() / ".ssh" / name
        if p.is_file():
            return p.read_text().strip()
    return ""


# --- ssh ----------------------------------------------------------------------

class Remote:
    def __init__(self, host: str, password: str, port: int = 22):
        import paramiko
        self.client = paramiko.SSHClient()
        self.client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        self.client.connect(host, port=port, username="root", password=password,
                            timeout=30, look_for_keys=False, allow_agent=False)

    def run(self, script: str, user: str | None = None, check: bool = True, quiet: bool = False) -> str:
        if user:
            script = ("export XDG_RUNTIME_DIR=/run/user/$(id -u) "
                      "DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/$(id -u)/bus\ncd\n") + script
            cmd = f"runuser -l {user} -c 'bash -s'"
        else:
            cmd = "bash -s"
        chan = self.client.get_transport().open_session()
        chan.set_combine_stderr(True)
        chan.exec_command(cmd)
        chan.sendall(script.encode())
        chan.shutdown_write()
        out: list[str] = []
        while not chan.exit_status_ready():
            if chan.recv_ready():
                self._take(chan.recv(4096), out, quiet)
            else:
                time.sleep(0.05)
        while True:
            data = chan.recv(4096)
            if not data:
                break
            self._take(data, out, quiet)
        rc = chan.recv_exit_status()
        text = "".join(out)
        if check and rc != 0:
            raise RuntimeError(f"команда на сервере завершилась с кодом {rc}")
        return text

    @staticmethod
    def _take(data: bytes, out: list[str], quiet: bool) -> None:
        s = data.decode(errors="replace")
        out.append(s)
        if not quiet:
            sys.stdout.write(s)
            sys.stdout.flush()

    def put(self, data: bytes, remote_path: str, mode: int = 0o644, owner: str | None = None) -> None:
        sftp = self.client.open_sftp()
        try:
            sftp.putfo(io.BytesIO(data), remote_path)
            sftp.chmod(remote_path, mode)
        finally:
            sftp.close()
        if owner:
            self.run(f"chown {owner}:{owner} {shlex.quote(remote_path)}", quiet=True)


def step(msg: str) -> None:
    print(f"\n→ {msg}", flush=True)


# --- шаги ---------------------------------------------------------------------

def needs_bootstrap(r: Remote) -> bool:
    out = r.run(f"command -v podman >/dev/null && id -u {BOT_USER} >/dev/null 2>&1 "
                f"&& [ \"$(loginctl show-user {BOT_USER} -p Linger --value 2>/dev/null)\" = yes ] && echo ready",
                check=False, quiet=True)
    return "ready" not in out


def bootstrap(r: Remote) -> None:
    step("подготовка машины: podman, пользователь, linger (несколько минут)")
    script = (HERE / "bootstrap.sh").read_text(encoding="utf-8")
    r.run(f"export BOT_USER={BOT_USER} PUBKEY={shlex.quote(laptop_pubkey())}\n" + script)


def ensure_dirs(r: Remote) -> None:
    r.run(f"install -d -m 700 -o {BOT_USER} -g {BOT_USER} {APP} {APP}/repo {APP}/data {HOME}/.config/systemd/user\n"
          f"chown {BOT_USER}:{BOT_USER} {HOME}/.config {HOME}/.config/systemd", quiet=True)


def ensure_deploy_key(r: Remote) -> str:
    return r.run(f'[ -f {APP}/deploy_key ] || ssh-keygen -q -t ed25519 -N "" -C marketeer-deploy -f {APP}/deploy_key\n'
                 f"cat {APP}/deploy_key.pub", user=BOT_USER, quiet=True).strip()


GIT_ENV = (f'export GIT_SSH_COMMAND="ssh -i {APP}/deploy_key -o IdentitiesOnly=yes '
           f'-o StrictHostKeyChecking=accept-new -o UserKnownHostsFile={APP}/data/known_hosts"')


def code_from_github(r: Remote, repo_ssh: str, branch: str) -> None:
    step(f"код из {repo_ssh} ({branch})")
    pub = ensure_deploy_key(r)
    out = r.run(f"""{GIT_ENV}
set -e
if [ -d {APP}/repo/.git ]; then
  git -C {APP}/repo fetch -q origin {shlex.quote(branch)} && git -C {APP}/repo reset -q --hard origin/{shlex.quote(branch)}
else
  rm -rf {APP}/repo && git clone -q -b {shlex.quote(branch)} {shlex.quote(repo_ssh)} {APP}/repo
fi
git -C {APP}/repo rev-parse --short HEAD""", user=BOT_USER, check=False)
    if "fatal" in out or "denied" in out.lower():
        print("\nGitHub не пустил. Два варианта:\n"
              "  1) репо публичный: укажите в .env https-адрес, ключ не нужен:\n"
              f"     MARKETEER_GIT_URL={repo_ssh.replace('git@github.com:', 'https://github.com/')}\n"
              "  2) репо приватный: добавьте deploy-ключ бота в репозиторий\n"
              "     (Settings → Deploy keys → Add deploy key, без записи):\n"
              f"     {pub}")
        sys.exit(2)


def code_from_laptop(r: Remote) -> None:
    step(f"код с ноутбука ({local_head()}) архивом")
    ensure_deploy_key(r)
    data = local_bundle()
    print(f"  {len(data) // 1024} КБ")
    r.put(data, f"{APP}/repo.tgz", 0o600)
    r.run(f"tar xzf {APP}/repo.tgz -C {APP}/repo && rm -f {APP}/repo.tgz && chown -R {BOT_USER}:{BOT_USER} {APP}/repo", quiet=True)


def write_env(r: Remote, env: dict[str, str]) -> None:
    step(".env на сервере")
    r.put(server_env(env).encode(), f"{APP}/.env", 0o600, owner=BOT_USER)


def build_image(r: Remote, force: bool) -> None:
    step("образ контейнера")
    r.run(f"""set -e
want=$(sha256sum {APP}/repo/deploy/Containerfile | cut -d' ' -f1)
have=$(cat {APP}/.containerfile_hash 2>/dev/null || true)
if [ "{int(force)}" = 1 ] || [ "$want" != "$have" ] || ! podman image exists localhost/marketeer:latest; then
  echo "  собираю (первый раз несколько минут)"
  podman build -q -t localhost/marketeer:latest -f {APP}/repo/deploy/Containerfile {APP}/repo/deploy
  echo "$want" > {APP}/.containerfile_hash
else
  echo "  образ актуален"
fi""", user=BOT_USER)


def install_unit(r: Remote) -> None:
    step("сервис systemd --user")
    unit = (HERE / "marketeer.service").read_bytes()
    r.put(unit, f"{HOME}/.config/systemd/user/marketeer.service", 0o644, owner=BOT_USER)
    r.run("systemctl --user daemon-reload && systemctl --user enable -q marketeer && systemctl --user restart marketeer && echo '  перезапущен'",
          user=BOT_USER)


def status(r: Remote, tail: int = 30) -> None:
    step("состояние")
    r.run("systemctl --user --no-pager -l status marketeer | head -8 || true\n"
          "echo\necho '  контейнер:' $(podman ps --filter name=marketeer --format '{{.Status}}' 2>/dev/null || echo 'нет')\n"
          "echo '  процесс бота:' $(podman exec marketeer pgrep -af 'python -m bot' 2>/dev/null | head -1 || echo 'не найден')\n"
          f"echo\npodman logs --tail {int(tail)} marketeer 2>&1 || echo '  контейнер ещё не запущен'", user=BOT_USER, check=False)


def ping(token: str) -> int:
    """Длинный опрос getUpdates: если бот работает, Telegram оборвёт наш запрос с 409 Conflict."""
    url = f"https://api.telegram.org/bot{token}/getUpdates?timeout=25"
    step("пинг Telegram (до 25 секунд)")
    try:
        with urllib.request.urlopen(url, timeout=40) as r:
            data = json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        if e.code == 409:
            print("  бот жив: Telegram сообщает, что другой экземпляр (наш бот) уже забирает обновления")
            return 0
        print(f"  Telegram ответил {e.code}: {e.read().decode(errors='replace')[:200]}")
        return 1
    n = len(data.get("result", []))
    print(f"  за 25 секунд конфликта не было, необработанных обновлений: {n}. "
          "Скорее всего бот НЕ опрашивает Telegram: проверьте --status и --logs")
    return 1


def logs(r: Remote) -> None:
    try:
        r.run("podman logs -f --tail 100 marketeer 2>&1", user=BOT_USER, check=False)
    except KeyboardInterrupt:
        pass


def rollback(r: Remote) -> None:
    step("откат на предыдущий коммит")
    r.run(f"""set -e
prev=$(cat {APP}/data/prev_commit 2>/dev/null || true)
[ -n "$prev" ] || {{ echo "prev_commit не записан, откатывать не на что"; exit 1; }}
git -C {APP}/repo reset -q --hard "$prev" && echo "  код на $prev"
systemctl --user restart marketeer""", user=BOT_USER)


# --- main ---------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description="Установка бота-маркетолога на VPS", add_help=True)
    ap.add_argument("host", nargs="?", help="IP или хост VPS (или MARKETEER_HOST в env-файле)")
    ap.add_argument("-p", "--password", help="пароль root (или MARKETEER_ROOT_PASSWORD в env-файле, иначе спросит)")
    ap.add_argument("--port", type=int, default=22)
    ap.add_argument("--env", default=DEFAULT_ENV, help=f"env-файл с ключами (по умолчанию {DEFAULT_ENV})")
    ap.add_argument("--sync", action="store_true", help="залить код с ноутбука, даже если задан MARKETEER_GIT_SSH")
    ap.add_argument("--rebuild", action="store_true", help="пересобрать образ")
    ap.add_argument("--bootstrap", action="store_true", help="заново прогнать подготовку машины")
    ap.add_argument("--discover", action="store_true", help="показать id чатов и людей, которых видит бот")
    ap.add_argument("--ping", action="store_true", help="проверить снаружи, забирает ли бот обновления из Telegram")
    ap.add_argument("--env-check", action="store_true", help="показать имена переменных в .env на сервере (без значений)")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--logs", action="store_true")
    ap.add_argument("--rollback", action="store_true")
    args = ap.parse_args()

    env_path = Path(args.env).expanduser()
    env = load_env(env_path)

    if args.discover or args.ping:
        token = env.get("MARKETEER_BOT_TOKEN")
        if not token:
            sys.exit(f"Добавьте MARKETEER_BOT_TOKEN=... в {env_path}")
        if args.ping:
            return ping(token)
        discover(token)
        return 0

    host = args.host or env.get("MARKETEER_HOST")
    if not host:
        ap.error("укажите IP VPS или MARKETEER_HOST в env-файле")

    only_ops = args.status or args.logs or args.rollback or args.env_check
    if not only_ops:
        miss = missing_keys(env)
        if miss:
            print(f"В {env_path} не хватает строк:")
            for k in miss:
                print(f"  {k}=    # {REQUIRED[k]}")
            return 1

    password = args.password or env.get("MARKETEER_ROOT_PASSWORD")
    if not password:
        try:
            password = getpass.getpass(f"пароль root@{host}: ")
        except EOFError:
            password = ""
    if not password:
        sys.exit("нет пароля root: передайте -p 'пароль' или добавьте MARKETEER_ROOT_PASSWORD в .env")

    ensure_paramiko()
    step(f"подключаюсь к root@{host}")
    try:
        r = Remote(host, password, args.port)
    except Exception as e:  # noqa: BLE001
        sys.exit(f"не подключился: {e}")

    try:
        if args.env_check:
            step(f"переменные в {APP}/.env (значения скрыты)")
            r.run(f"sed -nE 's/^([A-Za-z_]+)=(.*)$/  \\1 = <\\2>/p' {APP}/.env | "
                  "sed -E 's/<[^>]+>/<задано>/; s/<>/<пусто>/'", check=False)
            return 0
        if args.status:
            status(r); return 0
        if args.logs:
            logs(r); return 0
        if args.rollback:
            rollback(r); status(r); return 0

        if args.bootstrap or needs_bootstrap(r):
            bootstrap(r)
        else:
            print("  машина уже подготовлена")
        ensure_dirs(r)
        repo_url = env.get("MARKETEER_GIT_URL") or env.get("MARKETEER_GIT_SSH")
        if repo_url and not args.sync:
            code_from_github(r, repo_url, env.get("MARKETEER_GIT_BRANCH", "main"))
        else:
            code_from_laptop(r)
            if not repo_url:
                print("  (MARKETEER_GIT_URL не задан: /update в чате работать не будет, обновляйте этим скриптом)")
        write_env(r, env)
        build_image(r, args.rebuild)
        install_unit(r)
        time.sleep(5)
        status(r)
        print("\nГотово. Напишите боту в группе: /start@имя_бота")
        return 0
    except RuntimeError as e:
        print(f"\nОшибка: {e}")
        return 1
    finally:
        r.client.close()


if __name__ == "__main__":
    sys.exit(main())
