---
name: superpowers
description: Structured engineering workflows for brainstorming, planning before code, red-green-refactor TDD, and systematic root-cause debugging.
---

# Superpowers

This suite is the engineering discipline for Jedoc nodes that design, specify tests, or write code. Read the focused note that matches the moment, then follow it.

| Moment | Note |
| --- | --- |
| The problem is still fuzzy | `brainstorming.md` |
| You are about to change behavior | `test-driven-development.md` |
| A test or a runtime is failing and the cause is not proven | `systematic-debugging.md` |

## Shared rules

1. Plan the behavior in writing before editing production code. The plan names files, public functions, and the tests that will fail first.
2. One behavior at a time. Finish red, green, refactor before starting the next behavior.
3. Do not weaken a test to make a change pass. If the test is wrong, fix the test and say why.
4. Debugging starts from a failing signal, not from a hunch. Form one hypothesis, test it, then move.
5. Stop when the requested behaviors are green. Do not add speculative features.

## Plan-before-code checklist

- Which files will you create or change?
- Which existing modules must stay untouched?
- What is the first failing test, and which requirement does it lock?
- What error and concurrency cases are in scope for this change?
- How will you know you are done?

If you cannot answer those, you are still brainstorming. Do not edit `src/` yet.
