---
name: graphify
description: Map a repository's Python AST, TypeScript imports, and database models into graphify-out/GRAPH_REPORT.md so architecture and review use the real topology.
---

# Graphify

Do not guess the shape of the repository. Generate a structural report and read it.

## Command

From the workspace root:

```bash
python3 .cursor/skills/graphify/graphify_cli.py .
```

The command writes `graphify-out/GRAPH_REPORT.md`. It uses only the Python standard library: `ast` for Python files, a conservative import scan for TypeScript and JavaScript, and heuristics for SQLAlchemy models and `CREATE TABLE` statements.

Jedoc also runs this command before the architect node when this skill is enabled, and attaches the report to the prompt.

## How to use the report

- Start from the modules and tables that the feature will actually touch.
- Note import cycles, unexpected cross-package imports, and tables with no obvious owner.
- If the report disagrees with a mental model, the report wins until you verify the file.
- Cite file paths from the report in the architecture spec. Do not invent services that are not in the tree.
- Re-run the command after large structural edits so review sees the new graph.

## Limits

The scanner does not execute the project and does not resolve dynamic imports. Say when a conclusion is outside what the report can show.
