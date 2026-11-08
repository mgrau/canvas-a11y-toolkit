# Writing HTML that survives Canvas

Canvas runs every page body through a sanitizer. What we learned:

- `<style>` blocks and `<script>` are dropped. Put all styling **inline**
  on elements (`style="..."`).
- `display:flex`, `display:grid`, `border-radius` and `linear-gradient()`
  survive. `box-shadow` is stripped.
- `role` and `aria-label` survive. `aria-current` is stripped.
- Inline `<svg>` is dropped. The push uploads each one as a file and swaps
  in an `<img>` (alt from its `<title>`).
- `data:` image URIs are dropped. The push decodes them to files and
  uploads them.
- HTML comments are **kept** in the stored body, where any student can read
  them with View Source. The push strips them all.
- Canvas shows the page title as the page's `<h1>`. Page content starts at
  `<h2>`; the push shifts Quarto's headings down one level.
- Canvas adds the school's theme stylesheet and scripts to every page; they
  show up in the stored body and are harmless.
- Internal links: write `/courses/COURSE_ID/pages/<slug>`. The push fills in
  the real id, so the same source works in next year's course.
- A page's address (slug) is Canvas's choice and not always what you'd
  guess ("5.1" becomes "5-dot-1"). The toolkit finds pages by title.
- A new discussion is published by default; the client creates it with
  `published=false`.
- The front page must be published, so choosing it is the instructor's
  step.
- Panorama scans unpublished and locked content too, so drafts count
  toward the score.
