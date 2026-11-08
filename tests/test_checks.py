"""a11y_check rules, one per Panorama issue type."""
from a11y_check import check_body


def issues(html):
    return {f.issue for f in check_body(html)}


def test_clean_page_passes():
    html = ('<h2>Overview</h2><p>Text with a <a href="https://example.org/x">'
            'descriptive link</a>.</p><img src="a.png" alt="A short description.">')
    assert not {i for i in issues(html)} - {"ContentLengthIssue"}


def test_alt_text():
    assert "MissingAlternativeTextIssue" in issues('<img src="a.png">')
    assert "MissingAlternativeTextIssue" in issues('<img src="a.png" alt="">')
    assert "LongAlternativeTextIssue" in issues(f'<img src="a.png" alt="{"x" * 121}">')


def test_bare_url_link_text():
    assert "HyperlinkContextIssue" in issues(
        '<a href="https://example.org/page">https://example.org/page</a>')


def test_scanner_blocked_host():
    assert "BrokenHyperlinkIssue" in issues(
        '<a href="https://knowledge.ni.com/x">NI article</a>')


def test_empty_table():
    html = ("<table><caption>c</caption><tr><th scope='col'>A</th></tr>"
            "<tr><td></td></tr></table>")
    assert "MissingTableContentIssue" in issues(html)


def test_long_page():
    assert "ContentLengthIssue" in issues("<p>" + "word " * 3000 + "</p>")
