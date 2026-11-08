"""Find the course workspace and read its settings.

Every script works on a *workspace*: the folder holding `course.toml`. It is
found by walking up from the current directory, so run the scripts from
anywhere inside the course folder:

    cd ~/teaching/phys101/spring2027
    ~/teaching/canvas-a11y-toolkit/scripts/canvas.py whoami

`CANVAS_WORKSPACE=/path/to/course` overrides the search. Settings live in
`course.toml` (see templates/course.toml); the Canvas token lives in the
workspace's `.env` as `CANVAS_TOKEN`, never in course.toml, because
course.toml is committed and .env is not.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # Python < 3.11: run the scripts through uv
    sys.exit("Python 3.11+ is needed (the scripts run it through `uv run`).")

TOOLKIT = Path(__file__).resolve().parent.parent


class ConfigError(RuntimeError):
    pass


def find_root(start: Path | None = None) -> Path:
    env = os.environ.get("CANVAS_WORKSPACE")
    if env:
        root = Path(env).expanduser().resolve()
        if not (root / "course.toml").exists():
            raise ConfigError(f"CANVAS_WORKSPACE={env} has no course.toml")
        return root
    here = (start or Path.cwd()).resolve()
    for d in (here, *here.parents):
        if (d / "course.toml").exists():
            return d
    raise ConfigError(
        f"No course.toml in {here} or any folder above it.\n"
        "cd into the course workspace, or make one with "
        "`scripts/new_course.py <folder>`."
    )


def load_env(path: Path) -> dict[str, str]:
    """Read .env into a dict. Real environment variables win."""
    env: dict[str, str] = {}
    if path.exists():
        for line in path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
    env.update({k: v for k, v in os.environ.items() if k.startswith("CANVAS_")})
    return env


@dataclass
class Settings:
    root: Path
    name: str
    canvas_url: str
    course_id: str
    source_course_ids: list[str]
    timezone: str
    token: str
    panorama_tool_id: int | None
    alt_limit: int
    word_limit: int
    proxy_prefix: str
    own_hosts: list[str] = field(default_factory=list)
    scanner_blocked: list[str] = field(default_factory=list)

    @property
    def source_dir(self) -> Path:
        """Where export_course.py puts the old course (gitignored)."""
        return self.root / "source"

    @property
    def notes_dir(self) -> Path:
        """Panorama dumps and other private working files (gitignored)."""
        return self.root / "_notes"


_cached: Settings | None = None


def settings() -> Settings:
    global _cached
    if _cached is not None:
        return _cached
    root = find_root()
    with open(root / "course.toml", "rb") as f:
        t = tomllib.load(f)
    env = load_env(root / ".env")
    course = t.get("course", {})
    pan = t.get("panorama", {})
    checks = t.get("checks", {})
    missing = [k for k in ("canvas_url", "course_id") if not course.get(k)]
    if missing:
        raise ConfigError(f"course.toml [course] is missing {', '.join(missing)}")
    _cached = Settings(
        root=root,
        name=course.get("name", root.name),
        canvas_url=str(course["canvas_url"]).rstrip("/"),
        course_id=str(course["course_id"]),
        source_course_ids=[str(c) for c in course.get("source_course_ids", [])],
        timezone=course.get("timezone", "America/New_York"),
        token=env.get("CANVAS_TOKEN", ""),
        panorama_tool_id=pan.get("tool_id"),
        alt_limit=int(pan.get("alt_limit", 120)),
        word_limit=int(pan.get("word_limit", 2900)),
        proxy_prefix=t.get("library", {}).get("proxy_prefix", ""),
        own_hosts=list(checks.get("own_hosts", [])),
        scanner_blocked=list(checks.get("scanner_blocked", [])),
    )
    if _cached.course_id in _cached.source_course_ids:
        raise ConfigError("course_id is also listed in source_course_ids. "
                          "The tools write only to course_id; fix course.toml.")
    return _cached


def settings_or_defaults() -> Settings | None:
    """Settings if there is a workspace, else None (for pure checks/tests)."""
    try:
        return settings()
    except ConfigError:
        return None
