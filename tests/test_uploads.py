"""A push uploads an image only when its bytes are new to Canvas.

Offline: a fake Canvas that holds files in memory and counts uploads.
"""
import pytest

import canvas as cv
import canvas_api
from canvas_api import Canvas


class Response:
    def __init__(self, payload, status=200, link=""):
        self.payload, self.status_code = payload, status
        self.ok = status < 400
        self.text = str(payload)
        self.headers = {"Link": link}

    def json(self):
        return self.payload


class FakeCanvas:
    """Just enough of the files API: announce, upload, lock, list a folder,
    delete."""
    headers: dict = {}

    def __init__(self):
        self.files = {}  # id -> file
        self.uploads = 0
        self.listings = 0
        self.pending = None

    def request(self, method, url, params=None, data=None, **kw):
        path = url.split("/api/v1/", 1)[1].split("?", 1)[0]
        if method == "POST" and path == "courses/111/files":
            self.pending = data
            return Response({"upload_url": "https://s3.example/up", "upload_params": {}})
        if method == "PUT" and path.startswith("files/"):
            f = self.files[int(path.split("/")[1])]
            f["locked"] = data["locked"] == "true"
            return Response(dict(f))
        if method == "GET" and path.startswith("folders/") and path.endswith("/files"):
            self.listings += 1
            folder = int(path.split("/")[1])
            return Response([dict(f) for f in self.files.values() if f["folder_id"] == folder])
        raise AssertionError(f"unexpected {method} {path}")

    def s3_post(self, url, data=None, files=None, **kw):
        self.uploads += 1
        name, handle, _ = files["file"]
        fid = len(self.files) + 500
        self.files[fid] = {"id": fid, "display_name": name, "size": len(handle.read()),
                           "folder_id": int(self.pending["parent_folder_id"]), "locked": False}
        return Response(dict(self.files[fid]), status=201)


@pytest.fixture
def fake(monkeypatch, tmp_path):
    f = FakeCanvas()
    monkeypatch.setattr(canvas_api.requests, "post", f.s3_post)
    monkeypatch.setattr(cv, "UPLOADS", tmp_path / ".uploads.json")
    return f


def client(fake):
    canvas = Canvas.from_env()
    canvas.session = fake
    return canvas


def image(tmp_path, name="fig-01.png", data=b"\x89PNG one"):
    p = tmp_path / name
    p.write_bytes(data)
    return p


def test_unchanged_image_is_not_uploaded_again(fake, tmp_path):
    p = image(tmp_path)
    first, uploaded = cv.upload_once(client(fake), p, 7)
    assert uploaded and fake.uploads == 1
    # A later push is a new process: a new client, the record on disk.
    again, uploaded = cv.upload_once(client(fake), p, 7)
    assert not uploaded and again["id"] == first["id"] and fake.uploads == 1


def test_changed_image_is_uploaded(fake, tmp_path):
    p = image(tmp_path)
    cv.upload_once(client(fake), p, 7)
    p.write_bytes(b"\x89PNG two, edited")
    _, uploaded = cv.upload_once(client(fake), p, 7)
    assert uploaded and fake.uploads == 2


def test_image_deleted_in_canvas_is_uploaded(fake, tmp_path):
    p = image(tmp_path)
    info, _ = cv.upload_once(client(fake), p, 7)
    del fake.files[info["id"]]
    _, uploaded = cv.upload_once(client(fake), p, 7)
    assert uploaded and fake.uploads == 2


def test_many_images_cost_one_listing(fake, tmp_path):
    paths = [image(tmp_path, f"fig-{i:02}.png", f"art {i}".encode()) for i in range(40)]
    for p in paths:
        cv.upload_once(client(fake), p, 7)
    fake.listings = 0
    c = client(fake)
    assert not any(cv.upload_once(c, p, 7)[1] for p in paths)
    assert fake.listings == 1 and fake.uploads == 40


def test_new_uploads_are_locked_and_reuse_keeps_lock_state(fake, tmp_path):
    p = image(tmp_path)
    info, _ = cv.upload_once(client(fake), p, 7)
    assert fake.files[info["id"]]["locked"]
    fake.files[info["id"]]["locked"] = False  # the instructor released it
    cv.upload_once(client(fake), p, 7)
    assert not fake.files[info["id"]]["locked"]


def test_same_name_in_another_folder_is_its_own_file(fake, tmp_path):
    p = image(tmp_path)
    cv.upload_once(client(fake), p, 7)
    _, uploaded = cv.upload_once(client(fake), p, 8)
    assert uploaded and fake.uploads == 2
