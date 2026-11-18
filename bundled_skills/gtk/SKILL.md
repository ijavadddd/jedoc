---
name: gtk
description: Git, testing, and toolkit automation — branch and commit hygiene, test runner orchestration, fixture generation, and environment verification.
---

# GTK

GTK is the delivery toolkit: version control hygiene, the test command, fixtures, and a check that the environment you are about to trust is the one you think it is.

## Git

- Work on a feature branch when the repository already has a default branch. Do not commit to `main` or `master` unless the user explicitly told you to.
- Commits are small and about one behavior. The message says why.
- Do not commit secrets, `.env`, local databases, or `graphify-out/` noise unless the PRD says those artifacts are source.
- Inspect `git status` and `git diff` before you claim the change is complete. Mention untracked files that you intentionally left out.
- Jedoc's orchestrator does not commit for you between pipeline stages, so the reviewer can still see the working tree diff. Only commit when the task itself asks for a commit.

## Tests

- Detect the runner from the repo: `pytest`, `go test`, `cargo test`, `npm test`. Do not invent a second runner.
- Run the narrowest test that covers the behavior, then the suite you touched.
- Quote the command and the pass/fail summary in your final notes.
- Fixtures live next to the tests that use them, are deterministic, and do not call production services.
- A fixture that needs a clock or randomness takes it as an argument.

## Environment

Before declaring a green run, record:

- The test command.
- The language runtime version you actually executed.
- Whether Docker, a database, or a browser was required and whether it was reachable.
- Any test you could not run, and why.

Do not report a skipped integration test as a pass.

## CI shape

If the repo has CI config, read it and match it. If it does not, propose a single command the CI job should run. Do not add a pipeline file unless the PRD asks for one.
