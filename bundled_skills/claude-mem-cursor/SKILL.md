---
name: claude-mem-cursor
description: Capture, compress, and retrieve engineering decisions, architectural facts, and bug post-mortems in a local SQLite store exposed to Cursor as an MCP server.
---

# Claude Mem (local)

Jedoc ships a small stdio MCP server at `.cursor/skills/claude-mem-cursor/server.py`. It stores memories in `.cursor/claude-mem.sqlite` inside the workspace. Nothing is sent to an external memory service.

## Tools

- `memory_store` — write a compressed memory. Fields: `title`, `kind` (`decision`, `fact`, `postmortem`, `constraint`), `content`, optional `tags`.
- `memory_search` — keyword search across title, content, and tags.
- `memory_list` — newest memories first.

## What to store

Store a memory when the team learned something that a later session would otherwise rediscover:

- A scale constraint that changed the design ("inventory decrements must be conditional updates, never read-modify-write").
- An API contract decision and the alternative that was rejected.
- A bug post-mortem: symptom, cause, and the test that now locks the fix.
- A forbidden pattern for this repository.

## What not to store

- Secrets, tokens, customer payloads, or raw production rows.
- Transcripts of the whole session. Compress to the decision and the reason.
- Temporary debugging notes that will be obvious from the code.

## Procedure

1. At the start of a task, call `memory_search` with the feature name and the subsystem you are about to touch.
2. Treat returned constraints as binding unless the current PRD explicitly overrides them. If you override one, store a new decision that says so.
3. Before you finish, store at most three memories. One is usually enough.
4. Titles are short and specific. Content is a few sentences a stranger can act on, including file or table names when they matter.

## Failure mode

If the MCP server is unavailable, say so in your summary and continue. Do not invent memories you did not retrieve.
