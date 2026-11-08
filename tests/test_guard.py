"""The client refuses every write the toolkit must never make.

These run offline: a refused call raises before any request is sent, and an
allowed one is stopped by the fake session below.
"""
import pytest

from canvas_api import Canvas, Refused


class Sent(Exception):
    pass


class FakeSession:
    headers: dict = {}

    def request(self, method, url, **kw):
        raise Sent(method, url, kw.get("data"))


@pytest.fixture
def c():
    canvas = Canvas.from_env()
    canvas.session = FakeSession()
    return canvas


def allowed(c, method, path, data=None):
    with pytest.raises(Sent):
        c.request(method, path, data=data)


def refused(c, method, path, data=None):
    with pytest.raises(Refused):
        c.request(method, path, data=data)


def test_course_from_toml(c):
    assert c.course_id == "111"


def test_page_create_and_update(c):
    allowed(c, "POST", "courses/111/pages",
            {"wiki_page[title]": "T", "wiki_page[published]": "false"})
    allowed(c, "PUT", "courses/111/pages/t", {"wiki_page[body]": "x"})


@pytest.mark.parametrize("data", [
    {"wiki_page[published]": "true"},
    {"wiki_page[published]": "false"},     # on update this would unpublish
    {"wiki_page[front_page]": "true"},
    {"module[published]": "true"},
    {"published": "true"},
    {"hidden": "false"},
    {"locked": "false"},
    {"lock_at": "2027-01-01"},
])
def test_no_publish_unlock_or_visibility(c, data):
    refused(c, "PUT", "courses/111/pages/t", data)


def test_publish_on_create_refused(c):
    refused(c, "POST", "courses/111/pages", {"wiki_page[published]": "true"})
    refused(c, "POST", "courses/111/discussion_topics", {"published": "true"})


def test_other_courses_refused(c):
    refused(c, "PUT", "courses/222/pages/t", {"wiki_page[body]": "x"})
    refused(c, "POST", "courses/999/pages", {"wiki_page[title]": "x"})
    refused(c, "DELETE", "https://canvas.example.edu/api/v1/courses/222/pages/t")


def test_course_settings_refused_except_syllabus(c):
    allowed(c, "PUT", "courses/111", {"course[syllabus_body]": "<p>x</p>"})
    refused(c, "PUT", "courses/111", {"course[default_view]": "wiki"})
    refused(c, "PUT", "courses/111", {"course[event]": "offer"})
    refused(c, "PUT", "courses/111", {"course[image_id]": "5"})
    refused(c, "DELETE", "courses/111")


def test_only_locking_files(c):
    allowed(c, "PUT", "files/5", {"locked": "true"})
    refused(c, "PUT", "files/5", {"locked": "false"})
    refused(c, "PUT", "users/self/settings", {"x": "y"})


def test_source_course_is_read_only():
    src = Canvas.source()
    assert src.course_id == "222" and src.read_only
    src.session = FakeSession()
    with pytest.raises(Refused):
        src.request("POST", "courses/222/pages", data={"wiki_page[title]": "x"})
    with pytest.raises(Sent):
        src.request("GET", "courses/222/pages")


def test_source_cannot_be_target():
    with pytest.raises(Refused):
        Canvas.source("111")
    with pytest.raises(Refused):
        Canvas("https://x", "t", "222", forbidden=("222",))


def test_no_student_data_calls():
    for name in ("students", "submissions", "all_submissions", "custom_columns",
                 "set_front_page", "publish_module", "upsert_announcement"):
        assert not hasattr(Canvas, name), name
