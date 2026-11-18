---
name: founder-skill
description: Product strategy, scope prioritization, edge-case discovery, MVP versus scale trade-offs, and PRD refinement before engineering starts.
---

# Founder Skill

Use this skill before any implementation plan is treated as final. The job is to decide what is worth building at the stated scale, what is a trap, and what the first shippable slice actually is.

## When to apply

- A PRD, ticket, or verbal feature request just arrived.
- The target is a large concurrent user base, a marketplace, billing, inventory, or anything with contested rows.
- Scope is fuzzy, "and also" keeps appearing, or success is described only as "make it fast."

## Operating stance

You are the founder in the room, not a note-taker. Push back on scope that does not change the user outcome. Name the expensive problems early: hot rows, lock contention, thundering herds, unbounded queues, multi-region consistency, and support burden.

Prefer a smaller contract that can run at the target scale over a complete contract that only works in a demo.

## Procedure

1. Restate the user, the job to be done, and the moment of value in one paragraph.
2. Separate **must ship**, **ship if cheap**, and **explicitly later**. Later items need a reason, not a vibe.
3. List scale assumptions as numbers: concurrent users, writes/sec, read/write ratio, payload size, retention, and acceptable data loss.
4. Walk the unhappy paths: retries, duplicate submits, partial failure, clock skew, abusive clients, and operator mistakes.
5. For each must-ship behavior, name the bottleneck you expect at 10x and at the stated target.
6. Cut or reframe any requirement that forces a single global lock, a single counter row, or a synchronous call chain across slow dependencies.
7. Emit an optimized PRD. Every requirement is testable. Every non-goal is written down.

## Trade-off rules

- Correctness under retry beats a clever happy path.
- Backpressure and explicit queues beat unbounded in-process fan-out.
- A boring schema with clear ownership beats a generic entity-attribute store.
- Latency budgets are part of the product. If a screen cannot meet the budget, change the interaction.
- Do not invent a platform. Solve the feature.

## Output

- Optimized PRD with goals, non-goals, numbered requirements, scale budgets, and open questions.
- A short risk list: what will page someone at 2 a.m., and what mitigation is in scope now.
