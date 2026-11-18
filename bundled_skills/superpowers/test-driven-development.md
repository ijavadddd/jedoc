# Test-driven development

Red, green, refactor. In that order. No production code for a behavior that does not already have a failing test.

## Red

- Write one test that describes the behavior in the domain's language.
- Run it and confirm it fails because the behavior is missing, not because the test is broken.
- The test owns the contract: inputs, outputs, and the failure you care about (conflict, timeout, duplicate, precision).

## Green

- Write the least production code that turns that test green.
- Do not handle the next requirement in the same breath.

## Refactor

- With the test green, tidy names and structure.
- Re-run the test. Refactor does not change behavior.

## Scope fences in Jedoc

- The TDD node writes tests only. It does not "just stub" production code to cheat a green bar.
- The implementer node makes existing tests pass and does not edit tests to hide a failure.
- Concurrency and idempotency requirements need tests that would fail on a read-modify-write implementation.
