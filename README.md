# Jedoc

Jedoc is a local multi-agent engineering workstation. A LangGraph pipeline drives the Cursor CLI (`agent`) through a feature: scale architecture, red tests, a human gate, implementation, adversarial review, and a sustained QA / data audit. The React UI shows the live topology, the Cursor stream, and the eight skills that ship with the app.

Nothing in the skill catalog is downloaded. Enable, disable, and edit the bundled files; Jedoc copies them into the feature workspace.

## What you need

- Python 3.12+
- Node.js 22+ (the UI is built with the Vite toolchain)
- Git
- The Cursor CLI on `PATH` for live runs: <https://cursor.com/docs/cli>

```bash
agent status
```

`agent status` should report that you are logged in. `agent models` lists the model ids you can type into a node's model field. Leave the field empty to use the account default.

Live runs call:

```bash
agent --workspace <repo> --trust create-chat
agent -p --output-format stream-json --stream-partial-output \
  --resume <chat_id> --workspace <repo> --trust --approve-mcps \
  [--mode plan|ask] [--model <name>] [--force --sandbox disabled] \
  "<prompt>"
```

Agent mode is the CLI default, so Jedoc omits `--mode` for `agent`. `--mode` is sent only for `plan` and `ask`.

## Run it

```bash
chmod +x start.sh
./start.sh
```

- UI: <http://127.0.0.1:5173>
- API: <http://127.0.0.1:8000>

`start.sh` binds both processes to localhost. The API can invoke the Cursor CLI inside whatever workspace you choose, so do not expose it on a public interface.

Docker Compose is the other way up. The image does not contain the Cursor CLI; mount it yourself or set `JEDOC_EXECUTION_MODE=simulate`.

```bash
docker compose up --build
```

## Execution mode

| Variable | Meaning |
| --- | --- |
| `JEDOC_EXECUTION_MODE=auto` | Use `agent` when it is on `PATH`, otherwise simulate. Default. |
| `JEDOC_EXECUTION_MODE=live` | Always call the CLI. A missing binary or an auth error fails the node. |
| `JEDOC_EXECUTION_MODE=simulate` | Deterministic local script. No Cursor requests. The scripted reviewer rejects the first implementation so you can watch the retry loop. |
| `JEDOC_QA_DURATION_S` | Override the QA window. Unset means the node value, 600 seconds. |
| `JEDOC_DEFAULT_MODEL` | Sent as `--model` for every node instead of the per-node value. |
| `JEDOC_QA_DOCKER_UP=1` | `docker compose up -d` when the workspace has a compose file. Otherwise Jedoc only runs `docker compose config`. |
| `JEDOC_SIMULATE_REVIEW_FAILS` | How many simulated review rejections to emit before PASS. Default `1`. |

## Walkthrough

1. Open the UI. The canvas is the **Jedoc Million-User Enterprise Pipeline**.
2. Confirm the CLI pill. For a dry run without spending a request, stop the app and start it with `JEDOC_EXECUTION_MODE=simulate JEDOC_QA_DURATION_S=20 ./start.sh`.
3. **New feature**. The sample PRD is a 10M-user reservation drop. Leave the workspace empty to create `data/workspaces/<slug>/`, or point at an existing repo. Jedoc writes `PRD.md`. A brand-new folder is `git init`'d. An existing repository is not committed.
4. **Start pipeline**.
   - **PRD Scale Architect** (`plan`) runs graphify, then writes `PRD_OPTIMIZED.md` and `ARCHITECTURE_SPEC.md`. Skills: founder-skill, napkin, graphify, claude-mem-cursor.
   - **TDD Spec Writer** (`agent`) may write only under `tests/`. Skills: superpowers, gtk, claude-mem-cursor.
   - **Pre-implementation gate** syncs the skill set and the graph pauses with `interrupt_before=["implementer"]`.
5. While the implementer is `WAITING_APPROVAL`, open the inspector. Toggle any of the eight skills, edit a `SKILL.md` or `.mdc` in Monaco, then **Approve & Resume**. That approval is not asked again when review sends the same agent back; set `approve_every_entry` on the node if you want a gate on every entry.
6. **Implementer** (`agent`) writes `src/` and does not keep edits under `tests/`. **Adversarial Reviewer** (`plan`) reads the diff. `VERDICT: FAIL` routes back to the implementer with the same Cursor `chat_id`.
7. **Live 10m QA / DB Auditor** (`plan`) holds the configured window (10 minutes unless `JEDOC_QA_DURATION_S` is set), inspects compose when present, and runs read-only SQLite integrity, foreign-key, and numeric-precision checks. High-severity data findings override a model PASS. `SCALE_ISSUE` returns to the architect. `FAIL` returns to the implementer. `PASS` ends on **Feature Complete**.
8. **Mark feature done** archives every `chat_id` for that feature. Rows stay in SQLite. The next feature starts clean. **Reset this agent context** archives only that agent's chat.

## Context rule

`(feature_id, agent_id)` maps to one active `chat_id`, created with `agent create-chat` (or a simulated id). Retries, review rejections, and QA loops resume that chat. The system prompt is injected on the first turn only. Context is removed from the active set only by **Reset this agent context** or **Mark feature done**. Neither path deletes the row.

## Skills

| Id | What Jedoc writes |
| --- | --- |
| `founder-skill` | `.cursor/skills/founder-skill/SKILL.md`, `.cursor/rules/founder-skill.mdc` |
| `napkin` | skill + rule for diagrams and contracts |
| `ponytail` | skill + rule for structure and naming |
| `claude-mem-cursor` | skill, rule, and a local stdio MCP (`jedoc-claude-mem`) over `.cursor/claude-mem.sqlite` |
| `awesome-design-md` | skill, `DESIGN.md`, `.cursor/rules/design-md.mdc` |
| `graphify` | skill, rule, and `graphify_cli.py` (stdlib AST / import / SQL scan → `graphify-out/GRAPH_REPORT.md`) |
| `superpowers` | planning, TDD, and debugging notes |
| `gtk` | git, test runner, and environment checks |

Edits are stored as overrides in `data/jedoc.sqlite` and win over the bundled file on the next sync. The bundled originals stay in `bundled_skills/`.

Per-agent skill lists override the catalog for that node. Before the node runs, Jedoc rewrites the managed `.cursor/` files to that list. The Skills view toggles the global catalog and, when a feature is open, syncs the enabled set into its workspace.

## Pipeline template

Stored in the `flows` table as `jedoc-million-user`. The compiler in `backend/engine/graph_builder.py` builds a LangGraph `StateGraph` from that JSON, including conditional `on_pass`, `on_fail`, and `on_scale_issue` edges and a circuit breaker at each target's `max_retries`. You can add nodes, rewire edges, and edit prompts from the canvas. Structural edits are frozen while a feature is running or paused, because the checkpoint is bound to the topology. Prompt, model, mode, and skill edits are read when the node starts, so they apply at the gate.

## Layout

```
backend/providers/cursor_cli.py      Cursor CLI chat model and create-chat
backend/storage/session_store.py     Features, chats, flows, skills, audit
backend/marketplace/manager.py       Local skill enable / edit / sync
backend/engine/graph_builder.py      Flow JSON → LangGraph
backend/engine/runtime.py            One node: sync skills, resume chat, persist files
backend/api/server.py                REST, SSE, WebSocket
frontend/                            React 19, React Flow, Monaco, xterm.js
bundled_skills/                      The eight pre-installed skills
```

## Tests

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt
JEDOC_EXECUTION_MODE=simulate pytest
```

The pipeline test runs the simulated graph, asserts the pre-implementation pause, approves, checks that the implementer kept a single `chat_id` across the review rejection, then marks the feature done without deleting session rows.

## HTTP surface

- `GET /api/health`, `GET /api/agent/status`, `GET /api/sample-prd`
- `GET|PUT /api/flows/{id}`, node and edge create / patch / delete
- `GET /api/skills`, `PATCH /api/skills/{id}/toggle`, `PUT /api/skills/{id}/content`, `POST /api/skills/sync`
- `POST /api/features`, `POST /api/features/{id}/start`, `POST /api/features/{id}/approve`
- `POST /api/features/{id}/mark-done`, `POST /api/features/{id}/sessions/{agent_id}/reset`
- `GET /api/features/{id}/events` (SSE) and `WS /ws/features/{id}`
