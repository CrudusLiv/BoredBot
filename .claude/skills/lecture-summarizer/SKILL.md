---
name: lecture-summarizer
description: Convert a PowerPoint (.pptx) or PDF lecture into a structured Obsidian note under lectures/<course>/. Use when CrudusLiv drops a file in inbox/ or asks to summarize a lecture.
---

# Lecture Summariser

Turn a raw `.pptx` or `.pdf` into a study-friendly markdown note under `Dynamous/Memory/lectures/<course>/`.

## When to invoke

- A file appears in `Dynamous/Memory/inbox/` with extension `.pptx` or `.pdf`.
- CrudusLiv pastes a path and asks to summarize.
- The heartbeat tick detects new inbox files (Phase 6 wires this).

## Procedure

1. **Extract text** with the bundled script:
   ```
   py .claude/skills/lecture-summarizer/scripts/extract.py <path-to-file>
   ```
   Output is JSON. For `.pptx`: `{ type, filename, slide_count, slides: [{ slide_num, title, bullets, notes }] }`. For `.pdf`: `{ type, filename, page_count, pages: [{ page_num, text }] }`.

2. **Determine the course.** If the filename has a clear course code (e.g. `CS101_lecture3.pptx`), use it. Otherwise ask CrudusLiv. If they don't answer, default to `_uncategorised`.

3. **Generate the summary** in this exact structure:

   ```markdown
   ---
   course: <course code>
   lesson_num: <integer or "?">
   date: <today's YYYY-MM-DD — NOT the file's mtime>
   source_file: inbox/_processed/<original filename>
   tags: [<3-6 specific topic tags>]
   ---

   # <Lesson title>

   ## Key concepts
   - one concept per line, plain English
   - 5-10 bullets total

   ## Worked examples
   <Reproduce verbatim any worked examples / formulas / code from the slides. Math notation stays exact — do not paraphrase.>

   ## Open questions
   - things the slides referenced but didn't fully explain
   - things to clarify before the next class

   ## Study cards
   - Q: ...
     A: ...
   - Q: ...
     A: ...
   ```

4. **Save** to `Dynamous/Memory/lectures/<course>/<YYYY-MM-DD>_<topic-slug>.md`. Slug is the topic, lowercase, hyphenated, no spaces.

5. **Move the source file** to `Dynamous/Memory/inbox/_processed/`:
   ```powershell
   Move-Item "Dynamous\Memory\inbox\<filename>" "Dynamous\Memory\inbox\_processed\"
   ```

6. **Record the lecture in the daily note** by running:
   ```
   py .claude/scripts/vault/daily.py lecture <course> "<topic>" "lectures/<course>/<slug>.md"
   ```
   `<topic>` is the lesson title used as the note heading (e.g. `"Sorting Algorithms"`).


7. **Tick the habit.** If `HABITS.md` `Lecture engagement` is unchecked today, check it off.

8. **Update the concept wiki.** Invoke the `concept-wiki` skill with the path of the note just saved.

## Quality bar

- **Worked examples are verbatim.** Math notation, code, formulas — leave them exactly as on the slides. Paraphrasing math turns wrong.
- **Tags are specific.** Pick 3-6 topic tags like `pointers`, `recursion`, `bigO` — not `lecture`, `study`, or course code (the course is already in `course:`).
- **Bullets, not paragraphs.** Lectures study from bullets. Paragraphs don't stick.
- **Cross-link** with `[[wikilinks]]` if a concept connects to an earlier lecture's note.

## Edge cases

- Slide deck is image-only (script returns empty `text` for those slides) — surface a warning: "Slides X-Y appear to be images. OCR is not yet wired up (Phase 5b). Re-export with text if possible." Continue with what's available.
- File extension is `.ppt` (legacy) — script returns an error. Tell CrudusLiv to re-save as `.pptx`.
- `python-pptx` or `pypdf` not installed — error mentions the install command. Run `py -m pip install -r .claude/requirements.txt`.

## Don't

- Don't summarise into prose paragraphs. Bullets only.
- Don't invent worked examples. Empty section is fine if the slides don't have one.
- Don't skip frontmatter — Obsidian uses it for graph view and the indexer reads `tags`.
- Don't process files outside `inbox/`. Other locations may be in-progress notes the user is editing.
