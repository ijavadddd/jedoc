# Systematic debugging

1. Write down the failing signal: test name, assertion, status code, or query plan. Quote it.
2. State one hypothesis that would produce that signal.
3. Predict an observation that distinguishes the hypothesis (a log line, a row version, a count).
4. Check that observation. If it disagrees, discard the hypothesis. Do not stack a second guess on top of an untested one.
5. Fix the cause. Add a regression test that failed before the fix and passes after.
6. Store a one-paragraph post-mortem in Claude Mem when the failure was non-obvious: symptom, cause, test.

Do not rewrite the subsystem as a debugging strategy. Change the line that the evidence indicts.
