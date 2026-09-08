#!/usr/bin/env python3
"""
yandex-editor: отправляет текст агенту-редактору Яндекса (OpenAI-совместимый
Responses API на ai.api.cloud.yandex.net) и печатает отредактированный вариант.

Зависимостей нет — только стандартная библиотека.

Агент умеет и редактировать, и писать по скелету — поведение задаёт инструкция
во входе. Поэтому есть флаги:
    --edit                 только вычитка языка, без переписывания и смены смысла
    --correct              можно менять формулировки/структуру, смысл сохраняется
    --instruction "текст"  своя инструкция перед текстом (любая задача)
без флагов входной текст уходит как есть (агент решает сам по своему промпту).

Использование:
    python3 yandex_edit.py --edit --file path/to/text.md
    python3 yandex_edit.py --correct --file text.md --out text.fixed.md
    python3 yandex_edit.py --instruction "Сократи вдвое" --file text.md
    echo "текст" | python3 yandex_edit.py --edit --out result.md

Конфигурация (берётся из окружения или из ~/.config/nano-banana/.env):
    YANDEX_API_KEY    — ключ API Яндекса (обязательно)
    YANDEX_PROJECT_ID — id каталога Яндекс Облака (обязательно; принимается и YANDEX_PROJECT)
    YANDEX_PROMPT_ID  — id сохранённого промпта агента-редактора (обязательно)
    YANDEX_BASE_URL   — базовый URL (по умолчанию https://ai.api.cloud.yandex.net/v1)
"""
import argparse
import json
import os
import sys
import urllib.error
import urllib.request

ENV_FILE = os.path.expanduser("~/.config/nano-banana/.env")
DEFAULT_BASE_URL = "https://ai.api.cloud.yandex.net/v1"

EDIT_INSTRUCTION = (
    "Отредактируй следующий текст: только вычитка языка — грамматика, пунктуация, "
    "согласование, гладкость. Не переписывай заново, не добавляй новые разделы и "
    "мысли, не меняй смысл и факты. Верни отредактированный текст без комментариев."
)

CORRECT_INSTRUCTION = (
    "Скорректируй следующий текст: можно менять формулировки, порядок слов и "
    "структуру предложений, переписывать неудачные места ради ясности и гладкости. "
    "СОХРАНИ смысл, логику и факты. Не добавляй новых мыслей и разделов, ничего не "
    "выдумывай, не делай обещаний, которых нет в тексте. Верни только исправленный "
    "текст без комментариев."
)


def load_env_file(path):
    """Подгружает KEY=VALUE из env-файла в os.environ, не перезатирая уже заданное."""
    if not os.path.isfile(path):
        return
    with open(path, "r", encoding="utf-8") as fh:
        for raw in fh:
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = val


def extract_text(data):
    """Достаёт текст из ответа Responses API (output_text или output[].content[].text)."""
    if isinstance(data.get("output_text"), str) and data["output_text"]:
        return data["output_text"]
    parts = []
    for item in data.get("output", []) or []:
        for chunk in item.get("content", []) or []:
            txt = chunk.get("text")
            if txt:
                parts.append(txt)
    return "\n".join(parts).strip()


def main():
    ap = argparse.ArgumentParser(description="Редактура текста агентом Яндекса")
    ap.add_argument("--file", help="файл с текстом (иначе читаем stdin)")
    ap.add_argument("--out", help="куда записать результат (иначе stdout)")
    ap.add_argument("--prompt-id", help="переопределить YANDEX_PROMPT_ID")
    ap.add_argument(
        "--edit",
        action="store_true",
        help="режим вычитки: только язык, без переписывания и смены смысла",
    )
    ap.add_argument(
        "--correct",
        action="store_true",
        help="режим коррекции: можно менять формулировки/структуру, смысл сохраняется",
    )
    ap.add_argument(
        "--instruction",
        help="своя инструкция, добавляется перед текстом (перебивает --edit/--correct)",
    )
    ap.add_argument("--timeout", type=int, default=180, help="таймаут запроса, сек")
    args = ap.parse_args()

    load_env_file(ENV_FILE)

    api_key = os.environ.get("YANDEX_API_KEY")
    if not api_key:
        sys.exit(
            "Нет YANDEX_API_KEY. Добавьте строку YANDEX_API_KEY=... в "
            + ENV_FILE
            + " (права 600) и повторите."
        )

    base_url = os.environ.get("YANDEX_BASE_URL", DEFAULT_BASE_URL).rstrip("/")
    project = os.environ.get("YANDEX_PROJECT_ID") or os.environ.get("YANDEX_PROJECT")
    prompt_id = args.prompt_id or os.environ.get("YANDEX_PROMPT_ID")
    missing = [n for n, v in (("YANDEX_PROJECT_ID", project), ("YANDEX_PROMPT_ID", prompt_id)) if not v]
    if missing:
        sys.exit("Не заданы " + ", ".join(missing) + " (id каталога Яндекс Облака и id промпта "
                 "агента-редактора). Добавьте их в окружение или в " + ENV_FILE + ".")

    if args.file:
        with open(args.file, "r", encoding="utf-8") as fh:
            text = fh.read()
    else:
        text = sys.stdin.read()
    if not text.strip():
        sys.exit("Пустой вход: нечего редактировать.")

    if args.instruction:
        instruction = args.instruction
    elif args.correct:
        instruction = CORRECT_INSTRUCTION
    elif args.edit:
        instruction = EDIT_INSTRUCTION
    else:
        instruction = None
    if instruction:
        message = instruction.strip() + "\n\n" + text
    else:
        message = text

    payload = json.dumps(
        {"prompt": {"id": prompt_id}, "input": message}
    ).encode("utf-8")

    req = urllib.request.Request(
        base_url + "/responses",
        data=payload,
        method="POST",
        headers={
            "Authorization": "Bearer " + api_key,
            "Content-Type": "application/json",
            "OpenAI-Project": project,
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=args.timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")
        sys.exit(f"Ошибка API {exc.code}: {body}")
    except urllib.error.URLError as exc:
        sys.exit(f"Сетевая ошибка: {exc.reason}")

    result = extract_text(data)
    if not result:
        sys.exit("Пустой ответ от агента. Сырой ответ:\n" + json.dumps(data, ensure_ascii=False)[:2000])

    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(result + "\n")
        print(f"Готово: результат записан в {args.out}", file=sys.stderr)
    else:
        sys.stdout.write(result + "\n")


if __name__ == "__main__":
    main()
