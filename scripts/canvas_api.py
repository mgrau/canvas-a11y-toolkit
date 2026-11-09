"""Thin client for the Canvas LMS REST API.

Only what a content conversion needs: pages, the Syllabus tab, files,
discussions and modules. Everything is scoped to one course, and the client
itself enforces the safety rules (see `_guard`), so no caller and no model
driving the scripts can get around them:

- it writes only to the course in course.toml (`course_id`);
- it never writes to a source course (`source_course_ids`), which can only
  be read, through `Canvas.source()`;
- it never publishes, unlocks or hides anything, and never changes the
  front page or the course's settings: those are the instructor's steps;
- it has no calls for students, grades or submissions, so student data
  never passes through it.

Canvas API reference: https://canvas.instructure.com/doc/api/
"""

from __future__ import annotations

import re
import sys
import time
import mimetypes
import unicodedata
from pathlib import Path
from typing import Any, Iterator

import requests

import config


class CanvasError(RuntimeError):
    pass


class ConfigError(CanvasError):
    pass


class Refused(CanvasError):
    """A write the toolkit never makes. Do not work around it."""


# Form fields that publish, unlock or reveal something, or change how the
# course presents itself. The toolkit never sends them, with one exception:
# published=false when *creating* (POST) a page or discussion, because Canvas
# publishes a new discussion unless told not to. On an update (PUT) even
# published=false is refused: on a live item it would unpublish what the
# instructor released.
FORBIDDEN_FIELDS = re.compile(
    r"(^|\[)(published|publish|unlock_at|lock_at|hidden|front_page|default_view|"
    r"event|is_public|is_public_to_auth_users|public_syllabus|"
    r"public_syllabus_to_auth|visibility|delayed_post_at|unpublish)(\]|$)"
)

# --------------------------------------------------------------------------
# Client
# --------------------------------------------------------------------------


class Canvas:
    """A course-scoped Canvas API client."""

    def __init__(
        self,
        base_url: str,
        token: str,
        course_id: str | int,
        timezone: str = "America/New_York",
        dry_run: bool = False,
        read_only: bool = False,
        forbidden: tuple[str, ...] = (),
    ):
        self.base_url = base_url.rstrip("/")
        self.api = f"{self.base_url}/api/v1"
        self.course_id = str(course_id)
        self.timezone = timezone
        self.dry_run = dry_run
        self.read_only = read_only
        self.forbidden = tuple(str(c) for c in forbidden)
        if self.course_id in self.forbidden and not read_only:
            raise Refused(f"course {self.course_id} is a source course: read only")
        self.session = requests.Session()
        self.session.headers["Authorization"] = f"Bearer {token}"
        self._pages: list[dict] | None = None  # see pages()

    @classmethod
    def from_env(cls, dry_run: bool = False) -> "Canvas":
        """The client for the course being built (course_id in course.toml)."""
        cfg = cls._settings()
        return cls(cfg.canvas_url, cfg.token, cfg.course_id, cfg.timezone,
                   dry_run=dry_run, forbidden=tuple(cfg.source_course_ids))

    @classmethod
    def source(cls, course_id: str | int | None = None) -> "Canvas":
        """A read-only client for a source course (export_course.py)."""
        cfg = cls._settings()
        cid = str(course_id or (cfg.source_course_ids or [""])[0])
        if not cid:
            raise ConfigError("no source course: set source_course_ids in course.toml")
        if cid == cfg.course_id:
            raise Refused("the source course must not be the course being built")
        return cls(cfg.canvas_url, cfg.token, cid, cfg.timezone, read_only=True)

    @staticmethod
    def _settings():
        try:
            cfg = config.settings()
        except config.ConfigError as e:
            raise ConfigError(str(e)) from None
        if not cfg.token:
            raise ConfigError(
                f"No CANVAS_TOKEN in {cfg.root / '.env'}.\n"
                "Copy .env.example to .env and fill it in (the comments there "
                "say how to make a token)."
            )
        return cfg

    # -- plumbing ----------------------------------------------------------

    def _url(self, path: str) -> str:
        if path.startswith("http"):
            return path
        return f"{self.api}/{path.lstrip('/')}"

    def _guard(self, method: str, url: str, data: Any) -> None:
        """Refuse any write outside the toolkit's rules (module docstring)."""
        if self.read_only:
            raise Refused(f"read-only client (course {self.course_id}): "
                          f"refusing to {method} {url}")
        path = url.split("/api/v1/", 1)[-1].split("?")[0]
        # Course-scoped calls must name our course; the only others are
        # locking a file we uploaded (files/<id>) and Canvas's upload
        # confirmation.
        m = re.match(r"courses/(\d+)(/|$)", path)
        if m:
            if m.group(1) != self.course_id or m.group(1) in self.forbidden:
                raise Refused(f"refusing to {method} course {m.group(1)}: "
                              f"the toolkit writes only to course {self.course_id}")
            if path.rstrip("/") == f"courses/{self.course_id}" and method != "PUT":
                raise Refused(f"refusing to {method} the course itself")
        elif not re.match(r"files/\d+(/create_success)?$", path):
            raise Refused(f"refusing to {method} {path}: not a course write")
        for k, v in (data or {}).items() if isinstance(data, dict) else ():
            create_draft = (method == "POST" and str(v).lower() == "false"
                            and k in ("published", "wiki_page[published]"))
            if FORBIDDEN_FIELDS.search(k) and not create_draft:
                raise Refused(f"refusing to send {k}={v!r}: publishing, "
                              "unlocking and visibility are the instructor's steps")
            if k == "locked" and str(v).lower() != "true":
                raise Refused("refusing to unlock a file: the instructor does that")
        if path.rstrip("/") == f"courses/{self.course_id}":
            allowed = {"course[syllabus_body]"}
            extra = set(data or {}) - allowed
            if extra:
                raise Refused(f"refusing to change course settings {sorted(extra)}")

    def request(self, method: str, path: str, **kwargs: Any) -> requests.Response:
        """One API call, with retry on rate-limit and transient server errors."""
        writes = method.upper() in ("POST", "PUT", "DELETE", "PATCH")
        if writes:
            self._guard(method.upper(), self._url(path), kwargs.get("data"))
        if writes and self.dry_run:
            raise CanvasError(
                f"dry-run: refusing to {method.upper()} {path}"
            )

        url = self._url(path)
        delay = 1.0
        for attempt in range(6):
            response = self.session.request(method, url, timeout=60, **kwargs)

            # Canvas signals its leaky-bucket throttle as a 403 with this body.
            throttled = response.status_code == 403 and (
                "Rate Limit Exceeded" in response.text
            )
            if throttled or response.status_code in (500, 502, 503, 504):
                if attempt == 5:
                    break
                time.sleep(delay)
                delay *= 2
                continue

            if not response.ok:
                raise CanvasError(
                    f"{method.upper()} {url} -> {response.status_code}\n"
                    f"{response.text[:800]}"
                )
            return response

        raise CanvasError(
            f"{method.upper()} {url} still failing after retries "
            f"({response.status_code}): {response.text[:400]}"
        )

    def get(self, path: str, **params: Any) -> Any:
        return self.request("GET", path, params=params).json()

    def paginate(self, path: str, **params: Any) -> Iterator[dict]:
        """Yield every item across Canvas's Link-header pagination."""
        params.setdefault("per_page", 100)
        url: str | None = self._url(path)
        first = True
        while url:
            response = self.request("GET", url, params=params if first else None)
            first = False
            payload = response.json()
            if isinstance(payload, list):
                yield from payload
            else:
                yield payload
            url = _next_link(response.headers.get("Link", ""))

    def post(self, path: str, **kwargs: Any) -> Any:
        return self.request("POST", path, **kwargs).json()

    def put(self, path: str, **kwargs: Any) -> Any:
        return self.request("PUT", path, **kwargs).json()

    # -- identity ----------------------------------------------------------

    def whoami(self) -> dict:
        return self.get("users/self/profile")

    def course(self) -> dict:
        return self.get(f"courses/{self.course_id}")

    # -- reading -----------------------------------------------------------

    def assignments(self) -> list[dict]:
        return list(self.paginate(f"courses/{self.course_id}/assignments"))

    def pages(self) -> list[dict]:
        """The page index (titles and addresses, no bodies).

        Fetched once per client and then kept current by this client's own
        creates, updates and deletes. Listing every page costs one request
        per 100 pages, and a long manual pushed as 64 parts used to list the
        whole course several times per part: about 25 minutes for one
        manual in a 350-page course (Nov 8 2026). find_page() asks Canvas
        again before reporting a page missing, so a page another process
        created since is still found.
        """
        if self._pages is None:
            self._pages = list(self.paginate(f"courses/{self.course_id}/pages"))
        return list(self._pages)

    def _remember_page(self, page: dict) -> None:
        """Put a page's index entry into the cached index (replace or add)."""
        if self._pages is None or not page.get("url"):
            return
        entry = {k: v for k, v in page.items() if k != "body"}
        for i, p in enumerate(self._pages):
            if p.get("page_id") == entry.get("page_id") or p["url"] == entry["url"]:
                self._pages[i] = entry
                return
        self._pages.append(entry)

    def _forget_page(self, url_slug: str) -> None:
        if self._pages is not None:
            self._pages = [p for p in self._pages if p["url"] != url_slug]

    def modules(self) -> list[dict]:
        return list(self.paginate(f"courses/{self.course_id}/modules"))

    def find_page(self, title: str, recheck: bool = True) -> dict | None:
        """The index entry for a page, by title (or Canvas's address for it).

        recheck=False trusts the loaded index alone: for guesses that are
        verified later anyway, like predicting the links between parts while
        the splitter tries out candidate splits (hundreds of titles that
        never exist).
        """
        def match(p: dict) -> bool:
            return p["title"] == title or p["url"] == slugify(title)

        for p in self.pages():
            if match(p):
                return p
        if not recheck:
            return None
        # Not in the index this client loaded. Another process (a second
        # push running alongside) may have created it since, and missing it
        # here would create a duplicate, so ask Canvas: one request.
        try:
            fresh = list(self.paginate(f"courses/{self.course_id}/pages", search_term=title))
        except CanvasError:  # Canvas refuses some search terms (too short)
            self._pages = None
            fresh = self.pages()
        for p in fresh:
            if match(p):
                self._remember_page(p)
                return p
        return None

    def page_body(self, title: str) -> str | None:
        """The live body of a page, or None if it does not exist.

        find_page returns the entry from the *index*, which Canvas serves
        without a body. Anything comparing find_page(...)["body"] is comparing
        against nothing and will happily conclude a page is empty when it is
        not — which silently disarms the overwrite guard. Fetch the page.
        """
        found = self.find_page(title)
        if not found:
            return None
        full = self.get(f"courses/{self.course_id}/pages/{found['url']}")
        return full.get("body")

    # -- writing -----------------------------------------------------------

    def upsert_page(self, title: str, body: str) -> dict:
        """Create or update a wiki page, keyed on its URL slug.

        No published flag is ever sent (`_guard` refuses it). Canvas creates
        a page unpublished by default, and an update without the flag leaves
        a page the instructor already published as it is.
        """
        payload = {
            "wiki_page[title]": title,
            "wiki_page[body]": body,
        }
        # Update the page found by title, at the address Canvas gave it, and
        # create one only if there is none. A PUT to slugify(title) creates a
        # page when the slug is not quite Canvas's (Canvas spells "5.1" as
        # "5-dot-1"), so pushing a title like "Part 2: 5.1 Setup" made a new
        # "...-2" duplicate every time (Nov 8 2026).
        existing = self.find_page(title)
        if existing:
            page = self.put(
                f"courses/{self.course_id}/pages/{existing['url']}", data=payload
            )
        else:
            payload["wiki_page[published]"] = "false"
            page = self.post(f"courses/{self.course_id}/pages", data=payload)
        if existing and page.get("url") != existing["url"]:
            self._forget_page(existing["url"])
        self._remember_page(page)
        return page

    # -- deleting ----------------------------------------------------------
    #
    # Canvas moves deleted objects to a workflow_state of "deleted" rather than
    # dropping the row, so an accident is recoverable through the course's
    # "Undelete" page (/courses/:id/undelete) for a while. Do not rely on it.

    def delete_page(self, url_slug: str) -> dict:
        result = self.request(
            "DELETE", f"courses/{self.course_id}/pages/{url_slug}"
        ).json()
        self._forget_page(url_slug)
        return result

    def delete_module(self, module_id: int | str) -> dict:
        return self.request(
            "DELETE", f"courses/{self.course_id}/modules/{module_id}"
        ).json()

    def discussions(self) -> list[dict]:
        return list(self.paginate(f"courses/{self.course_id}/discussion_topics"))

    def find_discussion(self, title: str) -> dict | None:
        for d in self.discussions():
            if d["title"] == title:
                return d
        return None

    def upsert_discussion(self, title: str, body: str) -> dict:
        """Create or update a discussion topic, keyed on its exact title.

        Unlike pages there is no slug to PUT to, so an existing topic has to be
        looked up by title first. Renaming a topic in the source file therefore
        creates a second one rather than renaming the original.
        """
        payload = {
            "title": title,
            "message": body,
        }
        existing = self.find_discussion(title)
        if existing:
            return self.put(
                f"courses/{self.course_id}/discussion_topics/{existing['id']}",
                data=payload,
            )
        # Canvas publishes a new topic unless told not to.
        payload["published"] = "false"
        return self.post(
            f"courses/{self.course_id}/discussion_topics", data=payload
        )

    def delete_discussion(self, topic_id: int | str) -> dict:
        return self.request(
            "DELETE", f"courses/{self.course_id}/discussion_topics/{topic_id}"
        ).json()

    # -- modules -----------------------------------------------------------

    def upsert_module(self, name: str, position: int | None = None) -> dict:
        """Create or find a module by name. Existing items are left alone."""
        for module in self.modules():
            if module["name"] == name:
                return module
        data = {"module[name]": name}
        if position is not None:
            data["module[position]"] = position
        return self.post(f"courses/{self.course_id}/modules", data=data)

    def module_items(self, module_id: int | str) -> list[dict]:
        return list(
            self.paginate(f"courses/{self.course_id}/modules/{module_id}/items")
        )

    def add_module_item(
        self,
        module_id: int | str,
        title: str,
        item_type: str,
        content_id: int | str | None = None,
        page_url: str | None = None,
        indent: int = 0,
        external_url: str | None = None,
    ) -> dict:
        """Append one item. `item_type` is Canvas's: Assignment, Page, File,
        Discussion, SubHeader, ExternalUrl."""
        data = {
            "module_item[title]": title,
            "module_item[type]": item_type,
            "module_item[indent]": indent,
        }
        if content_id is not None:
            data["module_item[content_id]"] = content_id
        if page_url is not None:
            # Pages are addressed by their URL slug rather than a content id.
            data["module_item[page_url]"] = page_url
        if external_url is not None:
            data["module_item[external_url]"] = external_url
        return self.post(
            f"courses/{self.course_id}/modules/{module_id}/items", data=data
        )

    def files(self) -> list[dict]:
        return list(self.paginate(f"courses/{self.course_id}/files", per_page=100))

    def set_syllabus_body(self, html: str) -> dict:
        """Write the course's built-in Syllabus tab (not a wiki page)."""
        return self.put(
            f"courses/{self.course_id}", data={"course[syllabus_body]": html}
        )

    def upload_file(
        self, local_path: Path, folder: str = "course files", *,
        folder_id: int | None = None, locked: bool | None = None,
    ) -> dict:
        """Upload a file; use a locked folder ID for drafts awaiting review.

        A folder ID avoids path ambiguity. The parent must already be locked
        to protect the file during upload; locked=True also locks the file
        itself before returning. Omitting both options preserves old callers.
        """
        local_path = Path(local_path)
        content_type = (
            mimetypes.guess_type(local_path.name)[0] or "application/octet-stream"
        )

        # Step 1 — tell Canvas what is coming, get a signed upload target.
        target = self.post(
            f"courses/{self.course_id}/files",
            data={
                "name": local_path.name,
                "size": local_path.stat().st_size,
                "content_type": content_type,
                **({"parent_folder_id": folder_id} if folder_id is not None
                   else {"parent_folder_path": folder}),
                "on_duplicate": "overwrite",
            },
        )

        # Step 2 — POST the bytes to the (usually S3) upload URL. This one is
        # unauthenticated: the params are already signed, and sending our
        # bearer token to a third-party host would leak it.
        with open(local_path, "rb") as handle:
            upload = requests.post(
                target["upload_url"],
                data=target.get("upload_params", {}),
                files={"file": (local_path.name, handle, content_type)},
                allow_redirects=False,
                timeout=300,
            )
        if upload.status_code not in (200, 201, 301, 302, 303):
            raise CanvasError(
                f"upload of {local_path.name} failed "
                f"({upload.status_code}): {upload.text[:400]}"
            )

        # Step 3 — some backends hand back the file directly, others redirect
        # to a confirmation endpoint that does need our token.
        if upload.status_code in (301, 302, 303):
            location = upload.headers["Location"]
            result = self.request("GET", location).json()
        else:
            result = upload.json()
        # Every upload is locked: students see it only once the instructor
        # unlocks it. `locked` is kept for old callers and must be True.
        if locked is False:
            raise Refused("uploads are always locked")
        result = self.put(f"files/{result['id']}", data={"locked": "true"})
        return result


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


def _next_link(link_header: str) -> str | None:
    """Pull the rel="next" URL out of a Link header."""
    for part in link_header.split(","):
        match = re.match(r'\s*<([^>]+)>\s*;\s*rel="next"', part)
        if match:
            return match.group(1)
    return None


def slugify(title: str) -> str:
    """Canvas's page-URL convention: lowercase, non-alphanumerics to hyphens.

    Canvas spells "&" out as "and" rather than dropping it, so "Week 1 —
    August 25 & 27" becomes week-1-august-25-and-27. Getting this wrong makes
    a page look missing and a module item fail with "invalid page_url".

    Canvas *deletes* an apostrophe rather than replacing it, so "Grover's"
    becomes "grovers" and not "grover-s". Getting that wrong is worse than a
    missing page: upsert_page PUTs to the slug, and a PUT to a slug that does
    not exist CREATES a page, which Canvas then names from the title and
    de-duplicates to "...-2". The result was a fresh duplicate on every single
    push, silently, for any title containing an apostrophe.

    Accents are folded the same way, so "Café" gives "cafe" rather than "caf".

    Even so, prefer the `url` Canvas returns when creating a page over
    recomputing it here — the server is the authority. This function was
    checked against every page title in the live course.
    """
    slug = unicodedata.normalize("NFKD", title)
    slug = "".join(ch for ch in slug if not unicodedata.combining(ch))
    slug = slug.lower().replace("&", " and ")
    slug = re.sub(r"['’]", "", slug)
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    return slug.strip("-")


def confirm(prompt: str, assume_yes: bool = False) -> bool:
    """Ask before writing to a live course students can see."""
    if assume_yes:
        return True
    if not sys.stdin.isatty():
        raise CanvasError(
            "refusing to write to Canvas without confirmation "
            "(pass --yes to skip this prompt)"
        )
    return input(f"{prompt} [y/N] ").strip().lower() in ("y", "yes")
