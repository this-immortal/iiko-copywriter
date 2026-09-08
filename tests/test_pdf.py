from bot.pdf import md_to_html


def test_md_to_html_has_title_and_image():
    html = md_to_html("# Заголовок статьи\n\n![](cover.png)\n\n## Раздел\n\nТекст **жирный**.\n")
    assert "<title>Заголовок статьи</title>" in html
    assert '<img alt="" src="cover.png"' in html
    assert "<h2>Раздел</h2>" in html
    assert "<strong>жирный</strong>" in html


def test_md_to_html_default_title():
    assert "<title>Статья</title>" in md_to_html("просто абзац")
