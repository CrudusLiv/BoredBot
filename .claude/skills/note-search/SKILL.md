---
name: note-search
description: Hybrid semantic + keyword search over CrudusLiv's vault. Use whenever you need to recall something said before, find similar past drafts for voice-matching, or retrieve lecture content.
---

# Note Search

Hybrid vector + keyword search over the entire indexed vault — lectures, projects, research, daily logs, sent drafts, and the four core files.

## When to invoke

- "Have I noted anything about X?"
- "Find a similar past reply" — use `--path-prefix drafts/sent` for voice-matching before drafting a new reply.
- "What did the lecture on Y say?"
- Before generating any draft (Gmail / Discord / Outlook), check `drafts/sent/` for tone calibration.
- When a Gmail or Discord context references something you don't recognise — search before asking the user.

## How

```
py .claude/scripts/memory/memory_search.py "<natural language query>" --top-k <N> [--path-prefix <prefix>] [--json]
```

Examples:

```
py .claude/scripts/memory/memory_search.py "binary search tree balance"
py .claude/scripts/memory/memory_search.py "voice match" --path-prefix drafts/sent --top-k 5
py .claude/scripts/memory/memory_search.py "due deadline" --top-k 3 --json
```

Each result has: `path`, `heading`, `content` (chunk text), `score` (0-1, higher is better).

## After searching

- **Cite the path** in your reply: "from `lectures/CS101/2026-06-10_pointers.md`". Helps CrudusLiv verify and jump to the source.
- If `--json`, parse the array and reason over the chunks. If plain text, just read the output.
- If no results, say so plainly: "Nothing in the vault about X." Don't invent.

## Reindex

If CrudusLiv just edited a vault file and the search isn't surfacing the change, the index is stale:

```
py .claude/scripts/memory/memory_index.py
```

Phase 9 puts this on a 10-minute Task Scheduler trigger. Until then, run manually after big edits.

## Tuning

- `--top-k 3` for quick lookups; `--top-k 10` when surveying a topic.
- `--vec-weight 0.7` (default) is the right balance. Push toward `1.0` for purely semantic queries; toward `0.0` for exact-keyword queries.
- `--path-prefix` to scope: `drafts/sent`, `lectures/CS101`, `daily`, `research`, etc.

## Don't

- Don't search for trivial recall (file paths, today's date, info already injected via SessionStart).
- Don't paginate results manually. If `--top-k 10` doesn't surface what you need, refine the query — don't keep re-running with higher `k`.
- Don't quote raw chunks at length in your reply. Summarise; cite the path. Long quoted blocks rarely earn their context cost.
