---
name: napkin
description: Rapid architectural sketching, ASCII and Mermaid system diagrams, data-flow blueprints, and schema or API contract drafting.
---

# Napkin

Draw the system before anyone writes production code. A napkin sketch is a decision record: components, data ownership, request paths, and the lines where failure is allowed to stop.

## Produce these views

1. **Context.** Who calls the system, what it owns, and which existing services it must not fork.
2. **Container.** Processes, datastores, queues, caches. One box owns each piece of state.
3. **Hot path.** The synchronous request that has a latency budget, drawn as a numbered sequence.
4. **Write path.** Where the row lock lives, what is appended, what is updated in place, and what is eventually consistent.
5. **Contract.** HTTP or RPC shapes, idempotency keys, and the error taxonomy.
6. **Data.** Tables or collections, primary keys, uniqueness, and which access pattern each index serves.

## Drawing rules

- Use Mermaid (`flowchart`, `sequenceDiagram`, or `erDiagram`) plus a short prose caption.
- Every arrow has a payload name. Arrows without nouns are decoration.
- Mark sync calls with a solid arrow and async handoff with a dotted arrow.
- If two components both think they own a fact, stop and pick one owner.
- Capacity notes sit on the box: expected QPS, rough row width, and retention.
- Do not draw a service you cannot name a single responsibility for.

## Schema and API

- Prefer surrogate keys plus a natural uniqueness constraint the business actually has.
- Idempotency keys are columns, not comments.
- Pagination is keyset when the list can grow without bound. Say so on the contract.
- Money and quantities are integers in minor units unless the PRD explicitly requires a decimal type. Never binary floats.
- Write the failure responses next to the success response. Timeouts, conflicts, and validation errors are part of the contract.

## Done when

A reader who has not seen the meeting can implement the hot path without inventing a component, a table, or an error code.
