# Установка бота на VPS

Одна команда с ноутбука, на VPS нужен Ubuntu 22.04+ и пароль root:

```bash
deploy/install.sh 1.2.3.4 -p 'пароль_root'
```

Без `-p` пароль спросит. Скрипт сам: ставит podman, создаёт пользователя
`marketeer` без sudo, заливает код, кладёт секреты, собирает образ и
поднимает сервис. Повторный запуск обновляет код и перезапускает бота.
Нужен только `python3`; библиотека `paramiko` ставится сама в `deploy/.venv`.

## Что должно лежать в `~/.config/nano-banana/.env`

Файл уже есть, в нём ключи Gemini и Яндекса и `YANDEX_PROJECT_ID`. Добавьте
строки:

```
MARKETEER_BOT_TOKEN=123456:ABC...      # токен от @BotFather
MARKETEER_CHAT_ID=-1001234567890       # id группы
MARKETEER_USER_IDS=11111111,22222222   # кто может давать задания
CLAUDE_CODE_OAUTH_TOKEN=...            # результат команды `claude setup-token`
YANDEX_PROMPT_ID=...                   # id промпта агента-редактора в Яндекс Облаке
```

Если чего-то нет, скрипт скажет, каких строк не хватает, и ничего не будет
делать. Id группы и людей подскажет команда `deploy/install.sh --discover`:
добавьте бота в группу, напишите там `/start@имя_бота` и запустите её.
В @BotFather отключите Group Privacy (`/setprivacy` → Disable), иначе бот не
увидит ответы на свои сообщения.

Необязательные строки: `MARKETEER_HOST` (чтобы не писать IP),
`MARKETEER_ROOT_PASSWORD` (чтобы не спрашивал пароль), `MARKETEER_GIT_SSH`
(см. ниже), `CLAUDE_MODEL`, `CLAUDE_MAX_TURNS`, `SESSION_TTL_HOURS`,
`UPDATE_CHECK_MIN`.

## Откуда берётся код

Пока строки `MARKETEER_GIT_SSH` нет, код заливается с ноутбука архивом при
каждом запуске скрипта; команда `/update` в чате не работает.

Репозиторий: `this-immortal/iiko-copywriter`. Чтобы бот обновлялся из него,
добавьте `MARKETEER_GIT_SSH=git@github.com:this-immortal/iiko-copywriter.git`.
При первом запуске скрипт напечатает deploy-ключ бота; добавьте его в
репозиторий одной командой (токен GitHub лежит в `.secrets`):

```bash
deploy/github.py --name iiko-copywriter --deploy-key 'ssh-ed25519 AAAA... marketeer-deploy'
```

и запустите установку ещё раз. Дальше бот обновляется сам: по `/update` и
по опросу раз в 15 минут. Тот же `deploy/github.py` без параметров коммитит
и пушит текущее состояние проекта.

## Полезное

```bash
deploy/install.sh 1.2.3.4 --status     # состояние сервиса и последние строки лога
deploy/install.sh 1.2.3.4 --logs       # лог в реальном времени, Ctrl+C для выхода
deploy/install.sh 1.2.3.4 --rebuild    # пересобрать образ (новая версия Claude Code)
deploy/install.sh 1.2.3.4 --rollback   # откатить код на предыдущий коммит
deploy/install.sh 1.2.3.4 --sync       # залить код с ноутбука, даже если задан GitHub
```

Что где лежит на сервере: `/home/marketeer/app/repo` (код), `app/data`
(uploads, outputs, sessions.json, venv, HOME для Claude Code), `app/.env`
(600), `app/deploy_key`. В контейнере: `/app/repo` (rw, для git),
`/work/repo` (ro, рабочий каталог Claude), `/work/data`.
