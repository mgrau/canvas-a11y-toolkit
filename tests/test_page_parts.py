"""Long pages split into parts under Panorama's word limit."""
import page_parts


def long_page(chapters=6, words=900):
    return "".join(
        f'<section id="c{i}" class="level2"><h2>Chapter {i}</h2>'
        + "".join(f"<p>{'word ' * 150}</p>" for _ in range(words // 150))
        + "</section>" for i in range(1, chapters + 1))


def test_short_page_is_one_part():
    parts = page_parts.split("<h2>A</h2><p>short</p>", "Short", lambda t: "#")
    assert [t for t, _ in parts] == ["Short"]


def test_long_page_splits_under_limit():
    parts = page_parts.split(long_page(), "Guide", lambda t: "/p/" + t)
    assert len(parts) > 1
    assert parts[0][0] == "Guide"
    assert parts[1][0].startswith("Guide (Part 2 of ")
    from bs4 import BeautifulSoup
    for _, body in parts:
        assert page_parts.tokens(BeautifulSoup(body, "html.parser")) <= page_parts.TOKEN_LIMIT


def test_named_parts():
    titles = page_parts.titles(long_page(), "Manual", named=True)
    assert all(t.startswith("Manual (Part ") and "): " in t for t in titles)
    assert titles[0].endswith("Chapter 1")


def test_token_count_matches_panorama():
    from bs4 import BeautifulSoup
    assert page_parts.tokens(BeautifulSoup("<p>CONF:VOLT:DC 1.5 it's</p>", "html.parser")) == 5
