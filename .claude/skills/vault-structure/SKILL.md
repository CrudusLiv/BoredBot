---
name: vault-structure
description: How CrudusLiv's vault is organised. Use this to know where to read or write notes, what folders exist, Obsidian conventions (wikilinks, frontmatter), and the read/write rules.
---

# Vault Structure

Vault root: `Dynamous/Memory/`. Everything below is relative to that root unless stated otherwise.

## Top-level files (already in session context)

- `SOUL.md` — agent personality and behavioural rules
- `USER.md` — user profile, integrations, hard limits, drafting criteria
- `MEMORY.md` — session-loaded: decisions, lessons, open questions
- `DEADLINES.md` — one row per deadline; format `YYYY-MM-DD — <course> — <title>`. Heartbeat reads this for 24h/48h alerts and GCal sync.
- `PROJECTS.md` — one bullet per active project.
- `HEARTBEAT.md` — checklist the heartbeat watches every tick
- `HABITS.md` — daily pillars; reset at 08:00 KL by the heartbeat

## Daily logs

- `daily/YYYY-MM-DD.md` — append-only timestamped log. Anything new lands here first; the daily reflection (08:00 KL) promotes durable items into `MEMORY.md`.

## Content folders

- `research/<topic>.md` — research notes and learning outside coursework.
- `notes/NOTES.md` — single rolling file for topic-based notes captured mid-conversation. Append a `- YYYY-MM-DD — <topic>` bullet per note (multi-line bodies indent under the bullet). Prefer this over `daily/` for ideas, decisions, or summaries.

## Inbox

- `inbox/` — drop zone for files to be processed.
- `inbox/_processed/` — originals are moved here after processing so the same file isn't handled twice.

## File conventions

- Markdown with optional YAML frontmatter.
- **Obsidian wikilinks** `[[note title]]` for cross-references — Obsidian's graph view picks these up. Use them whenever a note references another note in the vault.
- Filenames: lowercase, hyphenated, no spaces. Predictable so wikilinks resolve.
- Dates: `YYYY-MM-DD` everywhere — sortable filenames, sortable frontmatter.

## Read / write rules

- **Read freely** from any vault file — Read tool, no asking.
- **Write to `daily/`** for time-based journal entries (what happened, session events). Append, don't replace.
- **Write to `notes/NOTES.md`** for topic-based notes captured mid-conversation — ideas, decisions, summaries. Append a `- YYYY-MM-DD — <topic>` bullet (multi-line bodies indent two spaces under the bullet); do not create separate files.
- **Write to `MEMORY.md`** only during the daily reflection or when CrudusLiv explicitly asks.
- **Never edit** `SOUL.md` or `USER.md` without explicit instruction.
- **Never delete** any file under `Dynamous/Memory/`.
- **Don't write outside the vault** for memory content. Code goes in `.claude/`; memory goes in `Dynamous/Memory/`.

## When in doubt

- Append topic-based notes to `notes/NOTES.md` as a new `- YYYY-MM-DD — <topic>` bullet. Capture time-based events to today's `daily/` log. When the distinction is unclear, use `notes/NOTES.md`.
- Ask before overwriting anything CrudusLiv wrote by hand (notes without auto-generated frontmatter).
