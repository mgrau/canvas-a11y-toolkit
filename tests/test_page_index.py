"""The page index is listed once per client, kept current by the client's
own writes, and re-checked with Canvas before a page is reported missing.

Offline: a fake Canvas that holds pages in memory and counts requests.
"""
import pytest

from canvas_api import Canvas, slugify


class Response:
    def __init__(self, payload, status=200, link=""):
        self.payload, self.status_code = payload, status
        self.ok = status < 400
        self.text = str(payload)
        self.headers = {"Link": link}

    def json(self):
        return self.payload


class FakeCanvas:
    """Just enough of the pages API: list (100 a page), search, create,
    update, delete."""
    headers: dict = {}

    def __init__(self, n=250):
        self.pages = [{"page_id": i, "url": f"page-{i}", "title": f"Page {i}"} for i in range(n)]
        self.calls = []

    def request(self, method, url, params=None, data=None, **kw):
        path = url.split("/api/v1/", 1)[1].split("?", 1)[0]
        self.calls.append((method, path, dict(params or {})))
        base = "courses/111/pages"
        if method == "GET" and path == base:
            params = params or {}
            if "search_term" in params:
                return Response([p for p in self.pages
                                 if params["search_term"].lower() in p["title"].lower()])
            page = int(url.split("page=")[1]) if "page=" in url else 1
            chunk = self.pages[(page - 1) * 100: page * 100]
            more = page * 100 < len(self.pages)
            link = f'<https://x/api/v1/{base}?page={page + 1}>; rel="next"' if more else ""
            return Response(chunk, link=link)
        if method == "POST" and path == base:
            title = data["wiki_page[title]"]
            p = {"page_id": len(self.pages) + 1000, "url": slugify(title), "title": title}
            self.pages.append(p)
            return Response({**p, "body": data["wiki_page[body]"]})
        if method == "PUT" and path.startswith(base + "/"):
            url_slug = path.rsplit("/", 1)[1]
            p = next(p for p in self.pages if p["url"] == url_slug)
            return Response({**p, "body": data["wiki_page[body]"]})
        if method == "DELETE" and path.startswith(base + "/"):
            url_slug = path.rsplit("/", 1)[1]
            self.pages = [p for p in self.pages if p["url"] != url_slug]
            return Response({})
        raise AssertionError(f"unexpected {method} {path}")

    def lists(self):
        return sum(1 for m, p, q in self.calls if m == "GET" and "search_term" not in q)

    def searches(self):
        return sum(1 for m, p, q in self.calls if m == "GET" and "search_term" in q)


@pytest.fixture
def fake():
    return FakeCanvas()


@pytest.fixture
def c(fake):
    canvas = Canvas.from_env()
    canvas.session = fake
    return canvas


def test_index_listed_once(c, fake):
    for i in range(50):
        assert c.find_page(f"Page {i}")["url"] == f"page-{i}"
    assert fake.lists() == 3          # 250 pages, 100 a page, once
    assert fake.searches() == 0


def test_many_parts_cost_one_listing(c, fake):
    titles = [f"Manual (Part {k} of 64): Section {k}" for k in range(1, 65)]
    for t in titles:                  # predicting the links between parts
        c.find_page(t)
    for t in titles:                  # pushing each part
        c.upsert_page(t, "<p>x</p>")
    for t in titles:                  # checking the links, then re-pushing
        assert c.find_page(t)["title"] == t
        c.upsert_page(t, "<p>y</p>")
    assert fake.lists() == 3
    # One search per new title for the prediction and one before the create.
    assert fake.searches() == 2 * 64
    assert sum(m == "POST" for m, _, _ in fake.calls) == 64
    assert sum(m == "PUT" for m, _, _ in fake.calls) == 64


def test_page_created_elsewhere_is_found_not_duplicated(c, fake):
    c.pages()                         # this client's index is now loaded
    fake.pages.append({"page_id": 9999, "url": "made-elsewhere", "title": "Made Elsewhere"})
    c.upsert_page("Made Elsewhere", "<p>x</p>")
    assert not any(m == "POST" for m, _, _ in fake.calls)
    assert [p for p in fake.pages if p["title"] == "Made Elsewhere"] == [
        {"page_id": 9999, "url": "made-elsewhere", "title": "Made Elsewhere"}]


def test_delete_forgets_the_page(c, fake):
    assert c.find_page("Page 7")
    c.delete_page("page-7")
    assert c.find_page("Page 7") is None
    assert all(p["url"] != "page-7" for p in c.pages())


def test_cache_holds_no_bodies(c, fake):
    c.upsert_page("New Page", "<p>secret draft</p>")
    assert all("body" not in p for p in c.pages())


def test_guesses_never_ask_canvas(c, fake):
    # The splitter tries candidate splits; their titles mostly never exist.
    for n in range(40, 70):
        for k in range(1, n + 1):
            c.find_page(f"Manual (Part {k} of {n}): Section {k}", recheck=False)
    assert fake.lists() == 3
    assert fake.searches() == 0
