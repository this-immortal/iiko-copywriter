#!/usr/bin/env python3
"""GitHub для этого репозитория: создать репо, закоммитить и запушить, добавить deploy-ключ бота.

  deploy/github.py                       создать репо (если нет), закоммитить всё, запушить main
  deploy/github.py --name другое-имя    имя репо (по умолчанию iiko-copywriter)
  deploy/github.py --public              публичный вместо приватного
  deploy/github.py --no-commit           только remote и push того, что уже закоммичено
  deploy/github.py --deploy-key 'ssh-ed25519 AAAA...'   добавить read-only deploy-ключ (его печатает install.py)

Токен: строка GITHUB_PAT=... в .env в корне репозитория (или в .secrets, там можно и просто
токеном первой строкой). Оба файла в .gitignore. Токен в вывод не попадает.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
API = "https://api.github.com"


def read_token() -> str:
    for name in (".env", ".secrets"):
        p = ROOT / name
        if not p.is_file():
            continue
        text = p.read_text(encoding="utf-8")
        m = re.search(r"^\s*GITHUB_PAT\s*=\s*['\"]?([A-Za-z0-9_]+)", text, re.M)
        if not m and name == ".secrets":
            m = re.search(r"\b((?:github_pat_|ghp_)[A-Za-z0-9_]+)", text)
        if m:
            return m.group(1)
    sys.exit("не нашёл GITHUB_PAT ни в .env, ни в .secrets в корне репозитория")


def api(token: str, method: str, path: str, body: dict | None = None) -> tuple[int, dict]:
    req = urllib.request.Request(
        API + path, method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Authorization": "Bearer " + token, "Accept": "application/vnd.github+json",
                 "X-GitHub-Api-Version": "2022-11-28", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            raw = r.read().decode()
            return r.status, (json.loads(raw) if raw else {})
    except urllib.error.HTTPError as e:
        raw = e.read().decode(errors="replace")
        try:
            return e.code, json.loads(raw)
        except ValueError:
            return e.code, {"message": raw[:300]}


def git(*args: str, env: dict | None = None, check: bool = True) -> str:
    r = subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, text=True, env=env)
    if check and r.returncode != 0:
        sys.exit(f"git {' '.join(args)}: {r.stderr.strip() or r.stdout.strip()}")
    return r.stdout.strip()


def main() -> int:
    ap = argparse.ArgumentParser(description="GitHub: создать репо, запушить, добавить deploy-ключ")
    ap.add_argument("--name", default="iiko-copywriter")
    ap.add_argument("--public", action="store_true")
    ap.add_argument("--no-commit", action="store_true")
    ap.add_argument("-m", "--message", default="Бот-маркетолог iiko: код, скиллы, база знаний, деплой")
    ap.add_argument("--deploy-key", help="публичный ssh-ключ бота (строка или путь к .pub)")
    ap.add_argument("--list", action="store_true", help="показать репозитории, доступные токену")
    ap.add_argument("--force", action="store_true", help="push с --force-with-lease (после переписывания истории)")
    args = ap.parse_args()

    token = read_token()
    code, user = api(token, "GET", "/user")
    if code != 200:
        sys.exit(f"токен не принят GitHub ({code}): {user.get('message')}")
    login = user["login"]
    print(f"→ GitHub: {login}")

    if args.list:
        code, repos = api(token, "GET", "/user/repos?per_page=100&sort=updated&affiliation=owner,collaborator")
        if code != 200 or not isinstance(repos, list):
            sys.exit(f"список репо не получен ({code}): {repos if isinstance(repos, dict) else ''}")
        if not repos:
            print("→ токену не доступен ни один репозиторий")
        for r in repos:
            print(f"  {r['full_name']:<40} {'private' if r['private'] else 'public':<8} push={r['permissions'].get('push')}  {r['html_url']}")
        return 0

    code, repo = api(token, "GET", f"/repos/{login}/{args.name}")
    if code == 200:
        print(f"→ репо уже есть: {repo['html_url']} ({'публичный' if not repo['private'] else 'приватный'})")
    elif code == 404:
        code, repo = api(token, "POST", "/user/repos", {
            "name": args.name, "private": not args.public,
            "description": "Telegram-бот маркетолог iiko: посты, статьи, UI-тексты, картинки",
            "has_wiki": False, "has_projects": False,
        })
        if code not in (200, 201):
            sys.exit(f"не создал репо ({code}): {repo.get('message')} {repo.get('errors', '')}")
        print(f"→ создал репо: {repo['html_url']} ({'публичный' if args.public else 'приватный'})")
    else:
        sys.exit(f"не проверил репо ({code}): {repo.get('message')}")

    if args.deploy_key:
        key = args.deploy_key
        if Path(key).expanduser().is_file():
            key = Path(key).expanduser().read_text().strip()
        code, resp = api(token, "POST", f"/repos/{login}/{args.name}/keys",
                         {"title": "marketeer-bot (read-only)", "key": key, "read_only": True})
        if code in (200, 201):
            print("→ deploy-ключ добавлен")
        elif code == 422 and "already in use" in json.dumps(resp):
            print("→ deploy-ключ уже был добавлен")
        else:
            sys.exit(f"deploy-ключ не добавлен ({code}): {resp.get('message')} {resp.get('errors', '')}")
        return 0

    remote_url = f"https://github.com/{login}/{args.name}.git"
    remotes = git("remote")
    if "origin" in remotes.split():
        git("remote", "set-url", "origin", remote_url)
    else:
        git("remote", "add", "origin", remote_url)
    print(f"→ origin = {remote_url}")

    if not args.no_commit:
        if git("status", "--porcelain"):
            git("add", "-A")
            git("commit", "-q", "-m", args.message)
            print(f"→ коммит: {git('log', '--oneline', '-1')}")
        else:
            print("→ коммитить нечего")

    branch = git("rev-parse", "--abbrev-ref", "HEAD")
    env = dict(os.environ, GITHUB_TOKEN=token, GIT_TERMINAL_PROMPT="0")
    helper = "!f() { echo username=x-access-token; echo \"password=$GITHUB_TOKEN\"; }; f"
    push = ["push", "-u", "origin", branch] + (["--force-with-lease"] if args.force else [])
    out = subprocess.run(
        ["git", "-C", str(ROOT), "-c", "credential.helper=", "-c", f"credential.helper={helper}", *push],
        capture_output=True, text=True, env=env,
    )
    if out.returncode != 0:
        sys.exit("push не прошёл: " + (out.stderr.strip() or out.stdout.strip())[:600])
    print(f"→ запушил {branch}: {repo['html_url']}")
    ssh_url = f"git@github.com:{login}/{args.name}.git"
    print(f"\nДля самообновления бота в .env должна быть строка:\n  MARKETEER_GIT_SSH={ssh_url}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
