---
name: concept-wiki
description: Cross-reference concepts from a lecture note into Dynamous/Memory/concepts/ wiki pages. Invoked by the lecture-summarizer after a new note is saved.
---

# Concept Wiki

After a lecture is summarised, pull the key concepts out of the note and upsert them into per-concept wiki pages under `Dynamous/Memory/concepts/`.

## When to invoke

- The `lecture-summarizer` skill calls this at step 8 with the path of the freshly saved note.
- CrudusLiv asks to "update the concept wiki" or "link this lecture's concepts".

## Input

The path to the lecture note just saved, e.g.:
```
Dynamous/Memory/lectures/CS101/2026-06-18_sorting-algorithms.md
```

## Procedure

1. **Read the lecture note.** Extract the `## Key concepts` section — each bullet is a candidate concept.

2. **For each concept:**

   a. Derive the wiki page path:
      ```
      Dynamous/Memory/concepts/<concept-slug>.md
      ```
      Slug = lowercase, hyphenated, e.g. `binary-search`, `big-o-notation`.

   b. **If the page does not exist**, create it:
      ```markdown
      ---
      tags: [concept]
      ---

      # <Concept Name>

      ## Mentions

      - [[<lecture-note-wikilink>]] — <one-line context from the lecture>
      ```

   c. **If the page exists**, append to its `## Mentions` section:
      ```
      - [[<lecture-note-wikilink>]] — <one-line context from the lecture>
      ```
      Do not duplicate an entry that already links to the same note.

3. **Wikilink format.** Use the note filename without extension:
   ```
   [[2026-06-18_sorting-algorithms]]
   ```

4. **One-line context** is the bullet text from the lecture note, trimmed to ≤ 120 characters.

## Quality bar

- Only include concepts that appear in `## Key concepts` — do not mine the full note body.
- Skip concepts that are already well-represented (≥ 3 mentions in the existing page) unless the new lecture adds a genuinely new angle. Use judgment.
- Don't create a concept page for the course name, lesson number, or tags (those are metadata, not concepts).

## Don't

- Don't overwrite existing concept pages — always append to `## Mentions`.
- Don't create more than 10 concept pages per lecture invocation (too many is noise).
- Don't run this skill on non-lecture notes (daily logs, finance, etc.).
