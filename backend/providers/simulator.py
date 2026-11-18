"""Deterministic stand-in for the Cursor CLI.

Used when JEDOC_EXECUTION_MODE=simulate, or when the `agent` binary is absent in auto mode.
The scripted reviewer rejects the first pass so the retry loop and persistent chat_id can be exercised.
"""

from __future__ import annotations

import os
import re


def _retry(prompt: str, agent_id: str) -> int:
    match = re.search(rf"{re.escape(agent_id)}=(\d+)", prompt)
    if match:
        return int(match.group(1))
    return 0


def scripted_response(agent_id: str, prompt: str) -> str:
    if agent_id == "prd_scale_architect":
        return _architect()
    if agent_id == "tdd_spec_writer":
        return _tdd()
    if agent_id == "implementer":
        return _implementer(prompt)
    if agent_id == "adversarial_reviewer":
        fails = int(os.environ.get("JEDOC_SIMULATE_REVIEW_FAILS", "1"))
        if _retry(prompt, "implementer") < fails:
            return _review_fail()
        return _review_pass()
    if agent_id == "live_10m_qa_db_auditor":
        if "SCALE_ISSUE_DEMO" in prompt:
            return _qa("SCALE_ISSUE")
        if re.search(r'"severity":\s*"high"', prompt):
            return _qa("FAIL")
        return _qa("PASS")
    return (
        "<<<FILE:NOTES.md>>>\n"
        f"# {agent_id}\n\nScripted custom node completed the requested read of the PRD.\n"
        "<<<END FILE>>>\n"
        "VERDICT: PASS\n"
    )


def _architect() -> str:
    return """<<<FILE:PRD_OPTIMIZED.md>>>
# Optimized PRD — reserved capacity

## Goal
Let a buyer reserve inventory without creating a hot row or a lost update at the stated concurrency budget.

## Non-goals
- Cross-region active-active writes.
- A general workflow engine.

## Scale budget
- 10_000_000 registered users, 50_000 reservation attempts per second peak.
- p99 reservation latency 150ms excluding client RTT.
- Duplicate submits with the same idempotency key return the original decision.

## Requirements
1. A reservation is a conditional update: it succeeds only when available quantity covers the request.
2. The write is idempotent on `(account_id, idempotency_key)`.
3. Money and quantities are integers. No binary floats.
4. Reads of availability may be cached for at most one second and never authorize the write.
5. Conflict returns HTTP 409. Validation returns HTTP 422.

## Risks
- A single counter row for a popular SKU will serialize writes. Mitigation in scope: partition reservation keys by SKU and keep the conditional update on that partition only.
<<<END FILE>>>
<<<FILE:ARCHITECTURE_SPEC.md>>>
# Architecture spec

```mermaid
flowchart LR
  client[Client] --> api[Reservation API]
  api --> db[(Inventory partition)]
  api --> idem[(Idempotency keys)]
```

## Ownership
- The inventory service owns available quantity for a SKU partition.
- No other service decrements that quantity.

## Write path
1. Insert the idempotency key or return the stored decision.
2. `UPDATE inventory SET available = available - :qty WHERE sku = :sku AND available >= :qty`.
3. If zero rows change, return 409.
4. Record the decision on the idempotency row in the same transaction.

## Forbidden
- Read-modify-write in application memory.
- `SELECT *` on the inventory table to authorize a write.
- A global sequence row touched by every reservation.
<<<END FILE>>>
VERDICT: PASS
"""


def _tdd() -> str:
    return """<<<FILE:tests/test_capacity.py>>>
import pytest

from capacity.inventory import reserve


def test_reserve_rejects_oversubscription():
    with pytest.raises(ValueError):
        reserve(2, 3)


def test_reserve_is_exact_integer_math():
    assert reserve(5, 2) == 3


def test_reserve_rejects_non_positive_request():
    with pytest.raises(ValueError):
        reserve(5, 0)
<<<END FILE>>>
<<<FILE:TESTS_PLAN.md>>>
# Test plan

Red tests cover oversubscription, exact integer decrement, and a non-positive request.
They live under `tests/` and do not modify `src/`. Concurrency at the database layer is specified in ARCHITECTURE_SPEC.md; these unit tests lock the pure decision function the SQL conditional update must mirror.
<<<END FILE>>>
VERDICT: PASS
"""


def _implementer(prompt: str) -> str:
    idempotency_note = ""
    if _retry(prompt, "implementer") >= 1:
        idempotency_note = (
            "\n    Callers must run this predicate in the same transaction as the\n"
            "    idempotency insert on (account_id, idempotency_key).\n"
        )
    return f"""<<<FILE:src/capacity/__init__.py>>>
<<<END FILE>>>
<<<FILE:src/capacity/inventory.py>>>
def reserve(available: int, requested: int) -> int:
    \"\"\"Return the remaining quantity after a conditional reservation.
{idempotency_note}
    Mirrors an `UPDATE` that succeeds only when `available >= requested`.
    Quantities are integers. A non-positive request or an oversubscribe is a conflict.
    \"\"\"
    if not isinstance(available, int) or isinstance(available, bool):
        raise TypeError("available must be an int")
    if not isinstance(requested, int) or isinstance(requested, bool):
        raise TypeError("requested must be an int")
    if requested <= 0 or requested > available:
        raise ValueError("insufficient")
    return available - requested
<<<END FILE>>>
<<<FILE:IMPLEMENTATION_NOTES.md>>>
# Implementation notes

`reserve` is the pure form of the conditional inventory update. The SQL write path in the architecture spec must use the same predicate. Tests were not modified.
<<<END FILE>>>
VERDICT: PASS
"""


def _review_fail() -> str:
    return """<<<FILE:REVIEW.md>>>
# Review

VERDICT: FAIL

The conditional decrement is the right shape, but the first pass does not yet show the idempotency key constraint next to the write. Add a short comment in `src/capacity/inventory.py` pointing at the `(account_id, idempotency_key)` requirement from ARCHITECTURE_SPEC.md, and keep quantities as integers.

Line note: `src/capacity/inventory.py` — document that callers must apply this predicate inside the same transaction as the idempotency insert.
<<<END FILE>>>
VERDICT: FAIL
"""


def _review_pass() -> str:
    return """<<<FILE:REVIEW.md>>>
# Review

The working tree matches ARCHITECTURE_SPEC.md: integer quantities, a conditional predicate, and tests that reject oversubscription. No test files were weakened. No hot-row counter was introduced in application code.

VERDICT: PASS
<<<END FILE>>>
VERDICT: PASS
"""


def _qa(verdict: str) -> str:
    return f"""<<<FILE:QA_REPORT.md>>>
# QA and data audit

Sustained window completed under the Jedoc harness. Read-only integrity checks ran against any local SQLite files. Docker Compose and Playwright are recorded in the harness steps; a missing compose file is not a product failure for this pure decision module.

## Data checks
- Quantity math stays in integers.
- No orphan write is possible in the pure function: it returns a new remaining value and does not persist a partial row.

VERDICT: {verdict}
<<<END FILE>>>
VERDICT: {verdict}
"""
