# План: маркетолог iiko

Спека: [spec.md](spec.md)

## Решение

Один репозиторий, три слоя. Слой «мозг»: Claude Code, запущенный как
`claude -p` с рабочим каталогом в корне репозитория, поэтому он сам видит
`CLAUDE.md`, `.claude/skills/*` и `knowledge/`. Авторизация по подписке через
токен `claude setup-token` (живёт год, переменная `CLAUDE_CODE_OAUTH_TOKEN`).
Слой «руки»: Python-бот на `python-telegram-bot`, урезанный мост v2: ловит
упоминание, кладёт файлы в `uploads/`, зовёт `claude -p`, отправляет в чат
всё новое из `outputs/`. Слой «ноги»: rootless-контейнер podman под
пользователем `iiko_copywriter`, юнит `systemd --user` с linger, код и знания
смонтированы томом из git-checkout, поэтому обновление кода не требует
пересборки образа.

Самообновление устроено через супервизор внутри контейнера
(`deploy/entrypoint.sh`): он запускает бота в цикле; код выхода 75 означает
«обнови меня», супервизор делает `git fetch` и `reset --hard origin/main`,
запоминает прежний коммит, перезапускает. Если после обновления бот упал
раньше чем через 90 секунд, супервизор откатывает на прежний коммит и пишет
в `state.json`, а бот при старте читает этот файл и рассказывает чату, что
случилось.

Раскладка репозитория:

```
bot/            telegram.py, claude_runner.py, files.py, pdf.py, updater.py
.claude/        settings.json (DISABLE_AUTOUPDATER, deny на правку репо)
.claude/skills/ iiko-copywriting, nano-banana-image, yandex-editor  (база)
                tg-post, article, ui-text, image                    (сценарии)
knowledge/      iiko.md (содержание от Василия), brand/ (лого, палитра)
deploy/         bootstrap.sh (sudo, один раз), install.sh (с ноутбука),
                Containerfile, entrypoint.sh, marketeer.service, local.env.example
CLAUDE.md       роль, куда класть результаты, ссылки на knowledge/
```

Сценарные скиллы, а не длинный `CLAUDE.md`: Claude Code выбирает скилл по
описанию, и каждый сценарий (пост, статья, UI-текст, картинка) держит свой
порядок действий: какой базовый скилл, когда звать `yandex_edit.py`, как
сливать правки, как назвать файл в `outputs/`. PDF из `.md` делает бот сам
(WeasyPrint), не модель: детерминированно и без лишнего хода.

## Что берём из моста Фабикс (`bot.py` v2)

| Функция v2 | Что делаем |
|---|---|
| `is_authorized`, `extract_prompt` | берём как есть; чат один, белый список людей необязателен (пустой = все в чате) |
| `run_claude` | берём; убираем `SHOW_COST` (подписка), модель одна, добавляем `--add-dir` для `outputs/` |
| `SESSIONS: dict[chat_id]` | ключ меняем на `user_id`, кладём в `sessions.json` с таймстампом, срок 8 ч |
| `download_file`, `snapshot_outputs`, `send_new_outputs`, `cleanup_outputs` | берём; PNG и PDF шлём как документ, `.md` тоже |
| `_keep_typing`, `reply_long`, `execute_and_reply` | берём |
| `classify_model`, `make_plan`, `on_button`, `PENDING`, `DANGER_PATTERN` | выбрасываем |
| `ALLOWED_TOOLS` с git и npm | заменяем на `Read,Glob,Grep,Write,Bash(python3 .claude/skills/*),Bash(pandoc *)` |
| `handle` | добавляем `/start`, `/help`, `/version`, `/update` |

Скиллы копируем из `~/.agents/skills/`. Правим: `yandex_edit.py:24`
(`YANDEX_PROJECT` → читать и `YANDEX_PROJECT_ID`, `ENV_FILE` по умолчанию не
нужен, в контейнере всё в env), `nano-banana-image/SKILL.md` (пути
`/mnt/user-data/outputs/` → каталог результатов, убрать `present_files`).

## Данные

Всё на томе `~/app/data` (в контейнере `/work/data`):

```
uploads/<ts>_<имя>          входящие файлы, чистим вместе с outputs
outputs/<run_id>/           результаты одного запуска, TTL 7 дней
sessions.json               {user_id: {session_id, last_ts}}
state.json                  {event: started|updated|rolled_back, commit, prev, error}
home/.claude/               HOME Claude Code: сессии для --resume, настройки
venv/                       зависимости бота, ставятся супервизором по хэшу requirements.txt
```

Репозиторий смонтирован дважды: rw в `/app/repo` для супервизора (git) и
ro в `/work/repo` как рабочий каталог Claude. Так модель физически не может
править код и скиллы, а `git reset --hard` при обновлении ничего не затирает.

Секреты в `~/app/.env` (600), в контейнер через `EnvironmentFile`:
`TELEGRAM_BOT_TOKEN`, `ALLOWED_CHAT_ID`, `ALLOWED_USER_IDS`,
`CLAUDE_CODE_OAUTH_TOKEN`, `GEMINI_API_KEY`, `YANDEX_API_KEY`,
`YANDEX_PROJECT_ID`. Deploy-ключ в `~/app/deploy_key`, в контейнер ro.

## Контракты

Команды чата: `/start` и `/help` (что умею, коммит), `/reset` (новый диалог
для отправителя), `/version`, `/update` (только допущенные). Триггер работы:
`@бот текст` или ответ на сообщение бота, с файлом или без.

Бот → Claude: текст пользователя, затем служебная приписка: пути входящих
файлов и каталог `outputs/<run_id>/`, куда класть результаты. Ответ
`--output-format json`: `result`, `session_id`. Статья считается готовой,
когда в `outputs/` появился `.md`; бот сам делает рядом `.pdf`.

Бот → супервизор: код выхода 0 (штатно), 75 (обновись), иное (упал).
Супервизор → бот: `state.json` перед стартом.

Ноутбук → VPS (`deploy/install.py`, paramiko): IP и пароль root
параметрами, всё остальное из `.env` в корне репозитория (файл в
.gitignore). Заходит только под root, команды
пользователя `iiko_copywriter` гоняет через `runuser -l`. Первый запуск делает
bootstrap (podman, пользователь, linger), дальше идемпотентно: код архивом
с ноутбука или `fetch` из GitHub, `.env`, образ (если изменился
`Containerfile`), юнит. Юнит `systemd --user` запускает `podman run` в
foreground: так работает и на Ubuntu 22.04 с podman 3.4, где нет quadlet.

## Что рассмотрели и отвергли

| Вариант | Почему нет |
|---|---|
| Claude Agent SDK (Python) | работает только по API-ключу, подписку не принимает (проверено по докам) |
| Голый Messages API, SKILL.md в промпте | платим за токены, теряем Read/Bash и автоподбор скиллов, переписываем оркестрацию сами |
| Docker под root и root-юнит, как в `SETUP.md` | противоречит R-12; и не хочется давать боту root на машине |
| venv + `systemd --user` без контейнера | WeasyPrint, pandoc и шрифты требуют apt, то есть root при каждой смене зависимостей; запасной путь, если podman на VPS не заведётся |
| Пересборка образа при каждом обновлении | минуты на `podman build` на каждый пуш; код монтируем томом, образ трогаем редко |
| Webhook GitHub вместо опроса | нужен публичный порт и TLS; опрос раз в 15 минут ничего не стоит |
| Роутинг по трём моделям и кнопки из v2 | задачи однотипные, опасных действий нет, одна модель проще |
| Один контекст на чат, как в v2 | несколько человек перебивают друг друга; сессия на пользователя |
| PDF через pandoc + LaTeX или headless Chromium | +1 ГБ к образу в первом случае, капризы sandbox в rootless во втором; WeasyPrint около 50 МБ |

## Риски

Лимиты подписки. Бот делит окно лимитов с моей интерактивной работой. [?]
Сколько токенов съедает статья с проходом через Яндекс, не мерил; если
упрёмся, переводим посты на `--model sonnet`.

Условия подписки. `setup-token` документирован для скриптов и CI, но Anthropic
запрещает отдавать подписку третьим лицам как продукт. У нас внутренний бот
для своей команды; считаю, что это допустимо, но я не юрист.

Rootless podman на VPS требует subuid/subgid и cgroups v2. На старых ядрах и
OpenVZ не заведётся. [?] Какой дистрибутив и виртуализация на VPS, не знаю;
`bootstrap.sh` пишу под Ubuntu 22.04+. Проверяем его на реальной машине до
всего остального; если нет, откатываемся на venv-вариант из таблицы выше.

[?] Синтаксис правил `Write(outputs/**)` в `--allowedTools` документацией не
подтверждён. План Б: `--permission-mode acceptEdits` плюс `--add-dir`.

Яндекс-редактор меняет термины, слияние правок в Claude эвристическое.
Проверяем руками на трёх статьях перед тем, как отдать маркетологам.

Токен подписки истекает через год. Бот при 401 от `claude` пишет в чат
«нет авторизации, обновите токен», а не молчит.

## Как проверяем

Юнит-тесты (`pytest`): триггер по упоминанию и ответу, белый список, срок
сессии, конвертация md → html для PDF. Локально на Mac WeasyPrint не ставим,
сам PDF проверяем в контейнере.

Podman на ноутбуке нет, поэтому первая сборка образа сразу на VPS. Дальше
десять пунктов из «Как поймём, что готово» в спеке, руками, в тестовой
группе.

Откат: `install.sh --rollback` делает `git checkout` на прежний коммит и
перезапуск; либо чиним и `/update`.
