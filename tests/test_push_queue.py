"""The push queue pushes a page only after its gate passes, one at a time.

Offline: the toolkit scripts are replaced by stubs that log their calls.
"""
import os
import sys
import time
from types import SimpleNamespace

import pytest

import push_queue as pq

STUB = """#!/bin/sh
echo "$(basename $0) $*" >> {calls}
case "$(basename $0)" in
  pdf2qmd.py) grep -q BROKEN "$2" && {{ echo "0/1 files pass"; exit 1; }}; echo "1/1 files pass";;
  a11y_check.py) echo "0 page(s) fail";;
  canvas.py) echo "-> https://canvas.example/courses/1/pages/x";;
esac
"""


@pytest.fixture
def ws(tmp_path, monkeypatch):
    scripts = tmp_path / "stubs"
    scripts.mkdir()
    calls = tmp_path / "calls.txt"
    for name in ("pdf2qmd.py", "a11y_check.py", "canvas.py"):
        f = scripts / name
        f.write_text(STUB.format(calls=calls))
        f.chmod(0o755)
    work = tmp_path / "ws"
    (work / "manuals/demo").mkdir(parents=True)
    (work / "guides/lab").mkdir(parents=True)
    (work / "course.toml").write_text("")
    (work / "manuals/demo/demo.qmd").write_text('---\ncanvas-title: "Demo Manual"\n---\nText\n')
    (work / "guides/lab/lab.qmd").write_text("---\ntitle: Lab\n---\nText\n")
    old = time.time() - 120
    for q in work.glob("*/*/*.qmd"):
        os.utime(q, (old, old))
    monkeypatch.chdir(work)
    monkeypatch.setattr(pq, "SCRIPTS", scripts)
    return SimpleNamespace(calls=calls, work=work)


def add(*qmd, title=None):
    return pq.cmd_add(SimpleNamespace(qmd=list(qmd), title=title))


def drain():
    pq.cmd_run(SimpleNamespace(once=True, interval=0))


def calls(ws):
    return ws.calls.read_text().splitlines() if ws.calls.exists() else []


def test_manual_is_checked_then_pushed_with_named_parts(ws):
    assert add("manuals/demo/demo.qmd") == 0
    drain()
    c = calls(ws)
    assert c[0].startswith("pdf2qmd.py --check manuals/demo/demo.qmd --render --diff")
    assert c[1] == "a11y_check.py --links manuals/demo/demo.html"
    assert c[2] == "canvas.py --yes push page manuals/demo/demo.html --title Demo Manual --named-parts"
    assert pq.load("manuals-demo")["state"] == "pushed"


def test_guide_needs_a_title_and_is_pushed_without_named_parts(ws):
    assert add("guides/lab/lab.qmd") == 1
    assert add("guides/lab/lab.qmd", title="Lab 1") == 0
    drain()
    assert calls(ws)[-1] == "canvas.py --yes push page guides/lab/lab.html --title Lab 1"


def test_failed_gate_is_not_pushed(ws):
    (ws.work / "manuals/demo/demo.qmd").write_text('---\ncanvas-title: "Demo"\n---\nBROKEN\n')
    old = time.time() - 120
    os.utime(ws.work / "manuals/demo/demo.qmd", (old, old))
    add("manuals/demo/demo.qmd")
    drain()
    assert not any(c.startswith("canvas.py") for c in calls(ws))
    item = pq.load("manuals-demo")
    assert item["state"] == "failed" and item["last"].startswith("gate:")


def test_page_being_edited_waits(ws):
    add("manuals/demo/demo.qmd")
    os.utime(ws.work / "manuals/demo/demo.qmd")  # just edited
    assert pq.next_item() is None
    old = time.time() - 120
    os.utime(ws.work / "manuals/demo/demo.qmd", (old, old))
    assert pq.next_item()["key"] == "manuals-demo"
