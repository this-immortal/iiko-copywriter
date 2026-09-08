"""Telegram-часть: триггеры, команды, приём файлов, отправка результатов."""
from __future__ import annotations

import asyncio
import json
import logging
import re
from pathlib import Path

from telegram import BotCommand, Update
from telegram.constants import ChatAction, ParseMode
from telegram.error import BadRequest
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

from .claude_runner import ClaudeRunner
from .config import Config
from .files import describe_incoming, save_incoming
from .outputs import IMAGE_EXT, OutputStore
from .pdf import md_to_pdf
from .state import format_state, read_and_clear_state
from .updater import EXIT_UPDATE, Updater, short

log = logging.getLogger("marketeer")

HELP = (
    "Я маркетолог iiko. Упомяните меня или ответьте на моё сообщение.\n\n"
    "Умею:\n"
    "• пост для Telegram-канала по брифу;\n"
    "• статью по оглавлению (файл или список пунктов), с вычиткой Яндексом и картинкой в шапке;\n"
    "• вычитать вашу статью;\n"
    "• формулировки для интерфейса: кнопки, сообщения, пустые состояния (можно со скриншотом);\n"
    "• картинку по описанию или доработку присланной.\n\n"
    "Команды: /reset — начать диалог заново, /version — версия, /update — обновиться из репозитория."
)

TG_LIMIT = 4000


def extract_prompt(text: str | None, entities, bot_username: str, bot_id: int,
                   reply_from_id: int | None = None) -> str | None:
    """Текст запроса, если сообщение адресовано боту (упоминание или ответ), иначе None."""
    text = (text or "").strip()
    mentioned = False
    for ent in entities or []:
        t = getattr(ent, "type", None)
        if t == "mention":
            tag = text[ent.offset: ent.offset + ent.length]
            if tag.lower() == f"@{bot_username}".lower():
                mentioned = True
                break
        elif t == "text_mention":
            user = getattr(ent, "user", None)
            if user is not None and user.id == bot_id:
                mentioned = True
                break
    if not (mentioned or reply_from_id == bot_id):
        return None
    return re.sub(rf"@{re.escape(bot_username)}\b", "", text, flags=re.IGNORECASE).strip()


def is_authorized(chat_id: int | None, user_id: int | None, cfg: Config) -> bool:
    """Только наш чат. Белый список людей необязателен: пустой значит «все в чате»."""
    if chat_id != cfg.chat_id or user_id is None:
        return False
    return not cfg.user_ids or user_id in cfg.user_ids


class MarketeerBot:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.runner = ClaudeRunner(cfg)
        self.outputs = OutputStore(cfg.data_dir / "outputs", cfg.output_ttl_days)
        self.uploads = cfg.data_dir / "uploads"
        self.updater = Updater(cfg.repo_dir, cfg.git_branch)
        self.app: Application | None = None
        self.exit_code = 0
        self.update_requested = False
        self._stopping = False
        self._bg_task: asyncio.Task | None = None
        self._migration_file = cfg.data_dir / "chat_migration.json"
        self._apply_saved_migration()

    # --- миграция группы в супергруппу ------------------------------------
    # Telegram меняет id чата, когда группа становится супергруппой (например,
    # после назначения бота админом). Запоминаем новый id, чтобы не молчать.

    def _apply_saved_migration(self) -> None:
        try:
            data = json.loads(self._migration_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        if data.get("from") == self.cfg.chat_id and isinstance(data.get("to"), int):
            log.info("Чат %s переехал в %s (сохранённая миграция)", self.cfg.chat_id, data["to"])
            self.cfg.chat_id = data["to"]

    async def on_migrate(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        msg = update.message
        if msg is None:
            return
        old = new = None
        if msg.migrate_to_chat_id and msg.chat.id == self.cfg.chat_id:
            old, new = msg.chat.id, msg.migrate_to_chat_id
        elif msg.migrate_from_chat_id and msg.migrate_from_chat_id == self.cfg.chat_id:
            old, new = msg.migrate_from_chat_id, msg.chat.id
        if new is None or new == self.cfg.chat_id:
            return
        self.cfg.chat_id = new
        try:
            self._migration_file.write_text(json.dumps({"from": old, "to": new}), encoding="utf-8")
        except OSError as e:
            log.warning("Не сохранил миграцию чата: %s", e)
        log.info("Группа %s стала супергруппой %s, продолжаю там", old, new)
        await self._announce(f"Группа стала супергруппой, у неё новый id. Продолжаю работать здесь. "
                             f"В .env стоит поправить MARKETEER_CHAT_ID={new}.")

    # --- жизненный цикл -------------------------------------------------

    async def post_init(self, app: Application) -> None:
        self.app = app
        await app.bot.set_my_commands([
            BotCommand("help", "что умею"),
            BotCommand("reset", "начать диалог заново"),
            BotCommand("version", "какая версия"),
            BotCommand("update", "обновиться из репозитория"),
        ])
        state = read_and_clear_state(self.cfg.data_dir)
        if state:
            msg = format_state(state)
            if msg:
                await self._announce(msg)
        self._bg_task = asyncio.get_running_loop().create_task(self._update_loop())
        log.info("Готов. chat=%s users=%s model=%s", self.cfg.chat_id, sorted(self.cfg.user_ids) or "все", self.cfg.model)

    async def _announce(self, text: str) -> None:
        try:
            await self.app.bot.send_message(self.cfg.chat_id, text)
        except Exception as e:  # noqa: BLE001
            log.warning("Не отправил в чат: %s", e)

    def _request_exit(self, code: int) -> None:
        if self._stopping:
            return
        self._stopping = True
        self.exit_code = code
        self.app.stop_running()

    async def _update_loop(self) -> None:
        """Раз в 5 с смотрим, не просили ли /update; раз в N минут проверяем удалённый коммит."""
        interval = max(60, self.cfg.update_check_min * 60)
        last_check = asyncio.get_event_loop().time()
        await asyncio.sleep(30)
        while not self._stopping:
            try:
                now = asyncio.get_event_loop().time()
                if not self.update_requested and now - last_check >= interval:
                    last_check = now
                    local, remote = await self.updater.check()
                    if remote and remote != local:
                        await self._announce(f"Вижу новый коммит {short(remote)} (у меня {short(local)}), обновлюсь, как освобожусь.")
                        self.update_requested = True
                if self.update_requested and self.runner.active == 0:
                    await self._announce("Обновляюсь, вернусь через минуту.")
                    self._request_exit(EXIT_UPDATE)
                    return
            except Exception:  # noqa: BLE001
                log.exception("update loop")
            await asyncio.sleep(5)

    # --- команды --------------------------------------------------------

    def _auth(self, update: Update) -> bool:
        chat = update.effective_chat
        user = update.effective_user
        ok = is_authorized(chat.id if chat else None, user.id if user else None, self.cfg)
        if not ok and chat is not None:
            log.info("Игнорирую chat=%s user=%s", chat.id, user.id if user else None)
        return ok

    async def cmd_help(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._auth(update):
            return
        local = await self.updater.local_commit()
        await update.message.reply_text(f"{HELP}\n\nВерсия: {short(local)}.")

    async def cmd_version(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._auth(update):
            return
        local, remote = await self.updater.check()
        if remote is None:
            tail = "удалённый репозиторий недоступен."
        elif remote == local:
            tail = "это последняя версия."
        else:
            tail = f"в репозитории уже {short(remote)}, могу обновиться: /update."
        await update.message.reply_text(f"Версия {short(local)}, {tail}")

    async def cmd_reset(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._auth(update):
            return
        had = self.runner.sessions.reset(update.effective_user.id)
        await update.message.reply_text("Начинаем заново." if had else "Диалога и не было, начинаем с чистого листа.")

    async def cmd_update(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._auth(update):
            return
        local, remote = await self.updater.check()
        if remote is None:
            await update.message.reply_text("Не достучался до репозитория, обновиться не могу.")
            return
        if remote == local:
            await update.message.reply_text(f"Уже последняя версия ({short(local)}).")
            return
        self.update_requested = True
        busy = self.runner.active
        await update.message.reply_text(
            f"Обновлюсь до {short(remote)}" + (f", как закончу текущие задачи ({busy})." if busy else " сейчас.")
        )

    # --- сообщения ------------------------------------------------------

    async def on_text(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._auth(update):
            return
        msg = update.message
        if msg is None:
            return
        reply_from = msg.reply_to_message.from_user.id if msg.reply_to_message and msg.reply_to_message.from_user else None
        prompt = extract_prompt(msg.text, msg.entities, ctx.bot.username, ctx.bot.id, reply_from)
        if prompt is None:
            return
        if not prompt:
            await msg.reply_text("Да? Напишите, что нужно сделать.")
            return
        await self.execute(update, ctx, prompt, [])

    async def on_file(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._auth(update):
            return
        msg = update.message
        if msg is None:
            return
        reply_from = msg.reply_to_message.from_user.id if msg.reply_to_message and msg.reply_to_message.from_user else None
        prompt = extract_prompt(msg.caption, msg.caption_entities, ctx.bot.username, ctx.bot.id, reply_from)
        if prompt is None:
            return
        if msg.document:
            file_id, filename = msg.document.file_id, msg.document.file_name
        elif msg.photo:
            photo = msg.photo[-1]
            file_id, filename = photo.file_id, f"photo_{photo.file_unique_id}.jpg"
        else:
            return
        path = await save_incoming(ctx.bot, file_id, filename, self.uploads, self.cfg.max_upload_mb)
        if path is None:
            await msg.reply_text(f"Файл больше {self.cfg.max_upload_mb} МБ, Telegram такие ботам не отдаёт.")
            return
        await self.execute(update, ctx, prompt or "Посмотри присланный файл и скажи, что это и что с ним можно сделать.", [path])

    # --- выполнение -----------------------------------------------------

    async def execute(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE, prompt: str, incoming: list[Path]) -> None:
        msg = update.message
        chat_id = update.effective_chat.id
        user_id = update.effective_user.id
        if self.update_requested:
            await msg.reply_text("Сейчас обновлюсь и потом сделаю, напишите ещё раз через минуту.")
            return

        self.outputs.cleanup(self.uploads)
        run_dir = self.outputs.new_run()
        full_prompt = self._compose(prompt, incoming, run_dir)

        stop = asyncio.Event()
        typer = asyncio.create_task(self._keep_typing(ctx, chat_id, stop))
        try:
            if self.runner.active >= self.cfg.max_concurrent:
                await msg.reply_text("Занят другими задачами, встал в очередь.")
            res = await self.runner.run(full_prompt, user_id)
        finally:
            stop.set()
            await typer

        if not res.ok:
            await self._reply_error(msg, res.kind, res.text)
            return
        await self._send_text(msg, res.text or "Готово, но ответить нечем: результат в файлах ниже.")
        await self._send_outputs(ctx, chat_id, msg.message_id, run_dir)

    def _compose(self, prompt: str, incoming: list[Path], run_dir: Path) -> str:
        parts = [prompt.strip(), "", "[Служебная приписка от бота, пользователю не показывать]",
                 f"Каталог результатов этого запроса: {run_dir}/ (клади сюда файлы; всё, что здесь появится, уйдёт в чат;",
                 "файлы, начинающиеся с точки, в чат не уходят)."]
        if incoming:
            parts.append("Входящие файлы от пользователя:")
            parts.append(describe_incoming(incoming))
        return "\n".join(parts)

    async def _keep_typing(self, ctx, chat_id: int, stop: asyncio.Event) -> None:
        while not stop.is_set():
            try:
                await ctx.bot.send_chat_action(chat_id, ChatAction.TYPING)
            except Exception:  # noqa: BLE001
                pass
            try:
                await asyncio.wait_for(stop.wait(), timeout=4.0)
            except asyncio.TimeoutError:
                pass

    async def _reply_error(self, msg, kind: str, detail: str) -> None:
        if kind == "auth":
            text = "Claude не пускает: истёк или не задан токен подписки. Нужен новый CLAUDE_CODE_OAUTH_TOKEN."
        elif kind == "timeout":
            text = detail
        else:
            text = "Не получилось: " + (detail[:1200] or "ошибка без подробностей, смотрите лог.")
        await msg.reply_text(text)

    async def _send_text(self, msg, text: str) -> None:
        for i in range(0, len(text), TG_LIMIT):
            chunk = text[i:i + TG_LIMIT]
            try:
                await msg.reply_text(chunk, parse_mode=ParseMode.MARKDOWN)
            except BadRequest:
                await msg.reply_text(chunk)

    async def _send_outputs(self, ctx, chat_id: int, reply_to: int, run_dir: Path) -> None:
        files = self.outputs.collect(run_dir)
        # PDF нужен статьям; пост для Telegram остаётся текстом и post.md.
        for md in [f for f in files if f.suffix.lower() == ".md" and not f.name.lower().startswith("post")]:
            if not md.with_suffix(".pdf").exists():
                pdf = await asyncio.to_thread(md_to_pdf, md)
                if pdf:
                    files.append(pdf)
        limit = self.cfg.max_send_mb * 1024 * 1024
        for f in sorted(set(files)):
            size = f.stat().st_size
            if size > limit:
                await ctx.bot.send_message(chat_id, f"{f.name} больше {self.cfg.max_send_mb} МБ, не отправлю.", reply_to_message_id=reply_to)
                continue
            try:
                with open(f, "rb") as fh:
                    await ctx.bot.send_document(chat_id, document=fh, filename=f.name, reply_to_message_id=reply_to)
                log.info("Отправил %s (%s байт)", f, size)
            except Exception as e:  # noqa: BLE001
                log.error("Не отправил %s: %s", f, e)
                await ctx.bot.send_message(chat_id, f"Не смог отправить {f.name}: {e}", reply_to_message_id=reply_to)


def run(cfg: Config) -> int:
    handlers = [logging.StreamHandler()]
    if cfg.log_path:
        handlers.append(logging.FileHandler(cfg.log_path))
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s", handlers=handlers)
    logging.getLogger("httpx").setLevel(logging.WARNING)

    bot = MarketeerBot(cfg)
    app = Application.builder().token(cfg.token).post_init(bot.post_init).build()
    app.add_handler(CommandHandler(["start", "help"], bot.cmd_help))
    app.add_handler(CommandHandler("version", bot.cmd_version))
    app.add_handler(CommandHandler(["reset", "new"], bot.cmd_reset))
    app.add_handler(CommandHandler("update", bot.cmd_update))
    app.add_handler(MessageHandler(filters.StatusUpdate.MIGRATE, bot.on_migrate))
    app.add_handler(MessageHandler(filters.Document.ALL | filters.PHOTO, bot.on_file))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, bot.on_text))
    app.run_polling(allowed_updates=Update.ALL_TYPES)
    log.info("Выход с кодом %s", bot.exit_code)
    return bot.exit_code
