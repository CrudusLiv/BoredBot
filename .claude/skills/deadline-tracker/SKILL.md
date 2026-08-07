---
name: deadline-tracker
description: Parse and track deadlines from vault notes. Use when CrudusLiv asks about upcoming deadlines, assignments, or when a lecture note is saved that contains due dates.
---

# Deadline Tracker

Scan the vault for upcoming deadlines and surface them in a sorted, actionable list.

## When to invoke

- CrudusLiv asks "what's due?" / "any deadlines?" / "what assignments do I have?"
- After summarising a lecture note that contains assignment dates or submission info
- The heartbeat tick includes a deadline check (run the agent, post result to Discord)

## Procedure

1. **Run the backend agent:**
   ```
   py .claude/scripts/agents/deadline_tracker.py
   ```
   Output is a bullet list sorted by date:
   ```
   • [Course] · [Item] · [Date/timeframe] · [Source file]
   ```
   Or exactly `No deadlines found.` if the vault has none.

2. **Parse the output.** The agent already formats the list — relay it directly unless CrudusLiv asked for a specific course or timeframe, in which case filter the list before responding.

3. **Check DEADLINES.md** at `Dynamous/Memory/DEADLINES.md` for any manually tracked items the agent's regex might have missed (especially items without deadline keywords in the text).

4. **Respond inline.** Surface the sorted list in the conversation. Do not write the result back to any file mid-conversation — the agent already writes its summary to agent state.

## Edge cases

- Vault is empty or has no lecture notes yet — reply "No deadlines found in vault yet."
- The agent fails (LLM unavailable) — fall back to reading DEADLINES.md directly and listing the `## Active` section.
- CrudusLiv asks for a specific course — filter by `[Course]` prefix in the bullet list.

## Don't

- Don't create or modify DEADLINES.md during this skill — that file is maintained by the heartbeat (Slice 3).
- Don't run the full memory indexer just to check deadlines — the agent reads markdown files directly.
