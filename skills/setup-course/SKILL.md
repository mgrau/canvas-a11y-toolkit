---
name: setup-course
description: Make a course workspace for the Canvas accessibility toolkit and connect it to Canvas. Use at the start of a new course conversion, or when canvas.py says there is no course.toml or no token.
---

# Set up a course workspace

`$T` is the toolkit's `scripts/` folder.

1. **Ask the instructor** for: the Canvas URL (`https://canvas.<school>.edu`),
   the id of the course to build (the number in its URL), the ids of any
   old courses to copy from, and the library's EZproxy prefix if they
   want DOI links proxied. Don't guess the course id.
2. **Make the workspace:**

       $T/new_course.py <folder> --canvas-url <url> --course-id <id> \
           --source <old id> --name "<course name>" [--proxy "<prefix>"]

3. **The token.** The instructor makes one (Canvas: Account -> Settings ->
   Approved Integrations -> New Access Token) and pastes it into
   `<folder>/.env` as `CANVAS_TOKEN=...`. Ask them to do this themselves.
   Never print the token, echo it, or put it anywhere else.
4. **Check the connection** from inside the folder:

       cd <folder>
       $T/canvas.py whoami

   It must print the instructor's name and the right course name. If the
   course is wrong, fix `course_id` in `course.toml` before anything else.
5. **Panorama.** `$T/canvas.py list tools` lists the course's external
   tools. Put the id of the one named like "YuJa Panorama" in `course.toml`
   under `[panorama] tool_id`. If there is none, leave it out (step 6 of
   the pipeline then uses the local checklist only).
6. **Own hosts.** In `course.toml [checks] own_hosts`, list the Canvas host
   and the library proxy host, so the link checker skips them.
7. Commit the workspace: `git add -A && git commit -m "Set up workspace"`.
   Check first that `git status` shows no `.env`, `source/`, `manuals/` or
   `_notes/`.

## Done when

- `canvas.py whoami` names the right course, and
- `git status` is clean and `.env` is not tracked (`git ls-files .env`
  prints nothing).
