---
name: canvas-sync
description: Merge edits made in the Canvas editor back into the source files when a push refuses to overwrite them. Use when canvas.py says "REFUSING TO PUSH" or the instructor edited a page in Canvas.
---

# Bring Canvas edits back into the source

Pushing works like git: a push is refused while Canvas holds an edit the
workspace has not seen, so the instructor's edit is never lost.

1. See what changed: `$T/canvas_sync.py status`, then
   `$T/canvas_sync.py diff page "<title>"`.
2. **Hand-written HTML (`canvas/*.html`):** `$T/canvas_sync.py pull page "<title>"`
   merges the Canvas edit into the file, word by word. If both sides
   changed the same words, the file gets git-style markers (`<<<<<<<`,
   `=======`, `>>>>>>>`). Resolve each by hand, keeping the instructor's
   wording unless it is clearly a mistake. A push refuses any file that
   still has markers.
3. **Pages rendered from a `.qmd`:** the pull cannot write to the qmd.
   Read the diff, make the same edit in the `.qmd` by hand, re-render,
   then mark it resolved: `$T/canvas_sync.py resolve page "<title>"`.
4. Push again (`push-to-canvas`).

Never use `--force` to get past the refusal unless the instructor says to
throw their Canvas edit away.

## Done when

The push goes through and the instructor's edit is in the source.
