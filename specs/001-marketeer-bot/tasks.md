# Задачи: маркетолог iiko

Спека: [spec.md](spec.md) · План: [plan.md](plan.md)

Порядок = порядок выполнения. В скобках — требования, которые задача закрывает.

Репозиторий и знания

- [x] T-1. Каркас: `bot/` как пакет, `requirements.txt`, `CLAUDE.md`, `.claude/settings.json` с `DISABLE_AUTOUPDATER` и deny на правку репо → `python -m bot --check` печатает конфиг без токенов (R-10)
- [x] T-2. Скопировать `iiko-copywriting`, `nano-banana-image`, `yandex-editor` в `.claude/skills/`; поправить `yandex_edit.py` (имя переменной проекта, env без файла) и пути в SKILL.md → оба скрипта отрабатывают с `--help` и с реальным ключом на строке текста (R-10)
- [x] T-3. Сценарные скиллы `tg-post`, `article`, `ui-text`, `image`: порядок шагов, вызов Яндекса и слияние правок только в `article`, имена файлов в `outputs/` → `claude -p "пост про стоп-лист" --model opus` в корне репо на ноутбуке кладёт `.md` в `outputs/` (R-5, R-6, R-7, R-8, R-9)
- [x] T-4. `knowledge/iiko.md` по структуре `fabix-knowledge.md` с заглушками разделов и `knowledge/brand/`; содержание вставит Василий → `CLAUDE.md` ссылается, скиллы читают (R-11)

Бот

- [x] T-5. `bot/telegram.py`: триггер по упоминанию и ответу, белый список, `/start`, `/help`, `/reset`, `/version` → тесты на `extract_prompt` и `is_authorized` (R-1, R-2)
- [x] T-6. `bot/claude_runner.py`: обёртка над `claude -p` с `--resume`, сессии на пользователя в `sessions.json` со сроком 8 ч, семафор на 2 параллельных запуска → тест на истечение сессии (R-2, R-10)
- [x] T-7. `bot/files.py`: приём документов и фото в `uploads/`, `.docx` → md через pandoc в приписке к промпту → скриншот с подписью «что на экране» получает осмысленный ответ (R-3)
- [x] T-8. Отправка результатов: снимок `outputs/<run_id>/` до и после, PNG и PDF как документы, `.md` тоже; TTL 7 дней → картинка приходит без сжатия (R-4)
- [x] T-9. `bot/pdf.py`: md → html (`markdown`) → PDF (WeasyPrint), кириллический шрифт, картинки по относительным путям → тест на html, PDF глазами в контейнере (R-4, R-6)

Развёртывание

- [ ] T-10. (написано, ждёт VPS) `deploy/Containerfile`: python 3.12, node, Claude Code через native installer, pandoc, WeasyPrint с зависимостями, шрифты → `podman build` проходит на VPS (R-12)
- [ ] T-11. (написано, ждёт VPS) `deploy/entrypoint.sh`: venv по хэшу `requirements.txt`, цикл запуска бота, обработка кода 75, `state.json` → ручной прогон в контейнере (R-13, R-14)
- [ ] T-12. (написано, ждёт VPS) `deploy/bootstrap.sh` (sudo, один раз): podman, git, пользователь `marketeer`, linger, ключ с ноутбука → `podman info` под `marketeer` работает (R-12)
- [ ] T-13. (написано, ждёт VPS) `deploy/install.py` с ноутбука: IP и пароль root параметрами, остальное из `.env` в корне репо; bootstrap, код архивом или из GitHub, `.env` на сервере, сборка, юнит `systemd --user` → критерий 1 из спеки (R-12, R-15, R-16)
- [ ] T-14. (написано, ждёт GitHub) `bot/updater.py`: `/update` → выход 75; опрос `git ls-remote` раз в 15 минут при простое; сообщение в чат после старта из `state.json` → критерий 8 (R-13)
- [ ] T-15. (написано, ждёт GitHub) Откат в супервизоре: падение раньше 90 с после обновления → `reset --hard` на прежний коммит, `state.json` → критерий 9 (R-14)

Выкат и приёмка

- [x] T-16. GitHub: репо `this-immortal/iiko-copywriter` подключён скриптом `deploy/github.py` (токен в `.secrets`), код запушен. Deploy-ключ добавим после первого `install.py`: `deploy/github.py --name iiko-copywriter --deploy-key '<ключ>'` → `git ls-remote` с VPS по ключу работает
- [ ] T-17. Первый выкат на VPS, критерии 1, 7, 10 → бот отвечает на `/start`, молчит чужим, переживает reboot
- [ ] T-18. Вставить базу знаний от Василия, прогнать критерии 2–6 в тестовой группе, поправить скиллы по результату → три статьи проверены руками на термины после Яндекса
- [ ] T-19. Ужать `MAX_TURNS` и таймаут по факту замеров; записать в `notes.md`, сколько турнов и минут уходит на пост и статью

## Отложено

- Публикация в канал, веб-интерфейс, роли, архив: см. «Не делаем» в спеке.
- Автообновление образа (новая версия Claude Code): пока только через `install.sh` с ноутбука.
- Права `Write(outputs/**)` в `--allowedTools`: если синтаксис не сработает на первой сборке, остаёмся на `acceptEdits` + `--add-dir`.
