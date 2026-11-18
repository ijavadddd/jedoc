---
name: ponytail
description: Strict code hygiene, clean modular refactoring, dead-code elimination, naming consistency, and structural tidiness.
---

# Ponytail

Leave the diff tighter than you found it. Ponytail is the hygiene bar for implementation and review: modules with one reason to change, names that match the domain, and no leftover scaffolding.

## Structural rules

- One module, one responsibility. If the file description needs "and", split it.
- Public functions state their inputs, outputs, and failure modes. Hidden globals are a defect.
- Delete unused imports, unused functions, commented-out blocks, and feature flags that are always on.
- Do not add a wrapper whose only job is to call another function with the same arguments.
- Keep I/O at the edges. Core decisions should be callable from a unit test without a network or a clock you cannot control.
- Match the surrounding style. Do not reformat unrelated lines.

## Naming

- Use the domain noun the PRD uses. Do not invent a synonym per layer (`Order` / `OrderEntity` / `OrderDTO` / `OrderModel`) unless the representations actually differ.
- Booleans read as predicates (`is_open`, `has_capacity`).
- Functions are verbs. Types are nouns.
- Avoid `Manager`, `Helper`, `Processor`, and `Utils` unless the file is truly a grab bag you are about to delete.

## Review checklist

- Can a caller predict the failure from the signature and the nearby types?
- Is there dead code introduced by an earlier attempt in this diff?
- Are concurrency controls (locks, version columns, idempotency keys) obvious at the write site?
- Are errors handled at the boundary that can do something about them, and propagated elsewhere?
- Is the test name the behavior, not the method?

## Refactor discipline

- Behavior-preserving cleanup is welcome inside the files you already had to touch.
- Do not drive-by refactor unrelated packages.
- If a rename is necessary, rename all in-repo references in the same change and stop.
