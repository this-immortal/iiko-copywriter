#!/usr/bin/env python3
"""
Генерация / редактирование изображений через Gemini API (Nano Banana 2).

Использует стабильный generateContent REST-эндпоинт, без внешних зависимостей
(только стандартная библиотека). Ключ берётся из переменной окружения
GEMINI_API_KEY, либо из .env-файла (--env-file, ./.env,
~/.config/nano-banana/.env).

Примеры:
    python3 generate_image.py --prompt "A cozy coffee bar, warm light" \
        --out out.png --aspect-ratio 16:9 --size 2K

    python3 generate_image.py --prompt "Добавь шапку на кота" \
        --input cat.png --out cat_hat.png
"""
import argparse
import base64
import json
import mimetypes
import os
import sys
import urllib.error
import urllib.request

def load_env_file(path):
    """Читает простой .env (KEY=VALUE), не перезаписывая уже заданные переменные."""
    if not os.path.isfile(path):
        return
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = val


def resolve_api_key(explicit_env_path=None):
    """Ищет GEMINI_API_KEY: переменная окружения -> --env-file -> ./.env ->
    ~/.config/nano-banana/.env. Возвращает ключ или пустую строку."""
    if os.environ.get("GEMINI_API_KEY", "").strip():
        return os.environ["GEMINI_API_KEY"].strip()
    candidates = []
    if explicit_env_path:
        candidates.append(explicit_env_path)
    candidates.append(os.path.join(os.getcwd(), ".env"))
    candidates.append(os.path.expanduser("~/.config/nano-banana/.env"))
    for path in candidates:
        load_env_file(path)
        if os.environ.get("GEMINI_API_KEY", "").strip():
            return os.environ["GEMINI_API_KEY"].strip()
    return ""


API_HOST = "https://generativelanguage.googleapis.com"
ENDPOINT = "/v1beta/models/{model}:generateContent"
DEFAULT_MODEL = "gemini-3.1-flash-image-preview"

VALID_RATIOS = {"1:1", "16:9", "9:16", "4:3", "3:4", "3:2", "2:3",
                "5:4", "4:5", "21:9", "4:1", "1:4", "8:1", "1:8"}
VALID_SIZES = {"512px", "1K", "2K", "4K"}


def build_parts(prompt, input_paths):
    parts = []
    for path in input_paths:
        if not os.path.isfile(path):
            sys.exit(f"Входной файл не найден: {path}")
        mime = mimetypes.guess_type(path)[0] or "image/png"
        with open(path, "rb") as f:
            data = base64.b64encode(f.read()).decode("utf-8")
        parts.append({"inline_data": {"mime_type": mime, "data": data}})
    parts.append({"text": prompt})
    return parts


def main():
    ap = argparse.ArgumentParser(description="Генерация изображений через Nano Banana 2 (Gemini API).")
    ap.add_argument("--prompt", required=True, help="Текстовое описание картинки.")
    ap.add_argument("--out", required=True, help="Путь для сохранения PNG.")
    ap.add_argument("--input", action="append", default=[],
                    help="Входное изображение для редактирования/композиции (можно повторять, до 14).")
    ap.add_argument("--aspect-ratio", default="1:1", help="Соотношение сторон, напр. 16:9.")
    ap.add_argument("--size", default="1K", help="Разрешение: 512px, 1K, 2K, 4K.")
    ap.add_argument("--model", default=DEFAULT_MODEL, help="ID модели Gemini.")
    ap.add_argument("--search", action="store_true", help="Включить grounding через Google Search.")
    ap.add_argument("--env-file", default=None,
                    help="Путь к .env-файлу с GEMINI_API_KEY=... (если ключ не в переменной окружения).")
    args = ap.parse_args()

    api_key = resolve_api_key(args.env_file)
    if not api_key:
        sys.exit("GEMINI_API_KEY не найден. Задайте его одним из способов:\n"
                 "  - переменная окружения:  export GEMINI_API_KEY=...\n"
                 "  - файл --env-file путь/к/.env  со строкой  GEMINI_API_KEY=...\n"
                 "  - файл ./.env в рабочем каталоге\n"
                 "  - файл ~/.config/nano-banana/.env\n"
                 "Ключ можно получить на https://aistudio.google.com/apikey")

    if args.aspect_ratio not in VALID_RATIOS:
        print(f"Предупреждение: нестандартное соотношение '{args.aspect_ratio}'.", file=sys.stderr)
    if args.size not in VALID_SIZES:
        sys.exit(f"Недопустимый --size '{args.size}'. Допустимо: {', '.join(sorted(VALID_SIZES))} "
                 "(K — заглавная).")
    if len(args.input) > 14:
        sys.exit("Слишком много входных изображений (максимум 14).")

    body = {
        "contents": [{"parts": build_parts(args.prompt, args.input)}],
        "generationConfig": {
            "responseModalities": ["IMAGE"],
            "imageConfig": {
                "aspectRatio": args.aspect_ratio,
                "imageSize": args.size,
            },
        },
    }
    if args.search:
        body["tools"] = [{"google_search": {}}]

    url = API_HOST + ENDPOINT.format(model=args.model)
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json", "x-goog-api-key": api_key},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=300) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")
        sys.exit(f"Ошибка API (HTTP {e.code}): {detail}")
    except urllib.error.URLError as e:
        sys.exit(f"Сетевая ошибка: {e.reason}. Проверьте, что разрешён доступ к "
                 "generativelanguage.googleapis.com в настройках сети.")

    # Достаём первую картинку из ответа
    image_b64 = None
    for cand in payload.get("candidates", []):
        for part in cand.get("content", {}).get("parts", []):
            inline = part.get("inlineData") or part.get("inline_data")
            if inline and inline.get("data"):
                image_b64 = inline["data"]
                break
        if image_b64:
            break

    if not image_b64:
        # часто это срабатывание фильтра безопасности
        reason = json.dumps(payload, ensure_ascii=False)[:800]
        sys.exit("Модель не вернула изображение. Возможно, сработал фильтр безопасности — "
                 f"переформулируйте промпт. Ответ API: {reason}")

    out_dir = os.path.dirname(os.path.abspath(args.out))
    os.makedirs(out_dir, exist_ok=True)
    with open(args.out, "wb") as f:
        f.write(base64.b64decode(image_b64))

    print(args.out)


if __name__ == "__main__":
    main()
