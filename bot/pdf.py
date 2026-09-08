"""Markdown → PDF для статей. HTML собираем всегда, PDF только если есть WeasyPrint."""
from __future__ import annotations

import html
import logging
import re
from pathlib import Path

import markdown

log = logging.getLogger("marketeer.pdf")

CSS = """
@page { size: A4; margin: 22mm 20mm 24mm 20mm;
        @bottom-center { content: counter(page); font-size: 9pt; color: #888; } }
body { font-family: "PT Sans", "Noto Sans", "DejaVu Sans", sans-serif;
       font-size: 11.5pt; line-height: 1.5; color: #1a1a1a; }
h1 { font-size: 24pt; line-height: 1.2; margin: 0 0 14pt; }
h2 { font-size: 16pt; margin: 22pt 0 8pt; }
h3 { font-size: 13pt; margin: 16pt 0 6pt; }
p { margin: 0 0 9pt; }
ul, ol { margin: 0 0 9pt 18pt; padding: 0; }
li { margin-bottom: 3pt; }
img { max-width: 100%; height: auto; display: block; margin: 6pt 0 14pt; border-radius: 4px; }
blockquote { margin: 8pt 0; padding: 4pt 12pt; border-left: 3px solid #c8c8c8; color: #444; }
code { font-family: "Noto Sans Mono", "DejaVu Sans Mono", monospace; font-size: 10pt; }
pre { background: #f4f4f4; padding: 8pt; white-space: pre-wrap; }
table { border-collapse: collapse; margin: 6pt 0 12pt; width: 100%; }
th, td { border: 1px solid #ccc; padding: 4pt 6pt; text-align: left; vertical-align: top; }
strong { font-weight: 700; }
"""

_H1 = re.compile(r"^\s*#\s+(.+?)\s*$", re.M)


def md_to_html(md_text: str, title: str | None = None) -> str:
    if title is None:
        m = _H1.search(md_text)
        title = m.group(1).strip() if m else "Статья"
    body = markdown.markdown(md_text, extensions=["extra", "sane_lists"], output_format="html")
    return (
        "<!DOCTYPE html><html lang=\"ru\"><head><meta charset=\"utf-8\">"
        f"<title>{html.escape(title)}</title><style>{CSS}</style></head>"
        f"<body>{body}</body></html>"
    )


def md_to_pdf(md_path: Path, pdf_path: Path | None = None) -> Path | None:
    """Возвращает путь к PDF или None, если WeasyPrint недоступен или упал."""
    pdf_path = pdf_path or md_path.with_suffix(".pdf")
    try:
        from weasyprint import HTML  # noqa: WPS433 (тяжёлый импорт по требованию)
    except Exception as e:  # ImportError или проблемы с системными библиотеками
        log.warning("WeasyPrint недоступен, PDF не будет: %s", e)
        return None
    try:
        html_text = md_to_html(md_path.read_text(encoding="utf-8"))
        HTML(string=html_text, base_url=str(md_path.parent)).write_pdf(str(pdf_path))
    except Exception as e:
        log.error("PDF из %s не собрался: %s", md_path, e)
        return None
    return pdf_path
