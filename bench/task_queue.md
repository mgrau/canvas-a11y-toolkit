## Pushing and Panorama in this run

- **A push worker is running** in this workspace. Don't push guides or
  manuals yourself: queue each one with `@TOOLKIT@/scripts/push_queue.py add`
  as soon as it passes its gate, and go on to the next document (the
  push-to-canvas skill, "Many pages: queue them"). Check
  `push_queue.py status` now and then, fix anything `failed`, and queue it
  again. Build the modules once the pages show `pushed`.
- **Panorama's findings arrive by themselves.** A watcher copies YuJa
  Panorama's score and issues for every scanned page into
  `_notes/yuja/summary.txt` every ten minutes. Pages are scanned some
  minutes after they are pushed. Before you finish, read it and fix what
  it lists for pages that are already scanned (the fix-yuja skill, from
  step 3), then queue those pages again.

