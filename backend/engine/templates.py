"""Built-in Jedoc Million-User Enterprise Pipeline."""

from __future__ import annotations

FLOW_ID = "jedoc-million-user"

OUTPUT_CONTRACT = """
Output contract:
- Emit every deliverable between markers exactly like this:
<<<FILE:relative/path.md>>>
content
<<<END FILE>>>
- End with a single final line `VERDICT: PASS`, `VERDICT: FAIL`, or `VERDICT: SCALE_ISSUE`.
- SCALE_ISSUE is only for an architectural miss (hot row, cross-partition transaction, unbounded fan-out). Ordinary bugs are FAIL.
""".strip()


def default_flow() -> dict:
    return {
        "id": FLOW_ID,
        "name": "Jedoc Million-User Enterprise Pipeline",
        "entry": "prd_scale_architect",
        "interrupt_before": ["implementer"],
        "nodes": [
            {
                "id": "prd_scale_architect",
                "display_name": "PRD Scale Architect",
                "role_type": "architect",
                "cursor_mode": "plan",
                "model": "claude-sonnet-4-6",
                "timeout_s": 600,
                "max_retries": 2,
                "require_approval_before": False,
                "approve_every_entry": False,
                "enabled_skills": ["founder-skill", "napkin", "graphify", "claude-mem-cursor"],
                "position": {"x": 0, "y": 40},
                "system_prompt": (
                    "You are the PRD scale architect. You are in plan mode: do not edit files. "
                    "Map the real repository from the graphify report, sketch the hot path and the write path, "
                    "and audit the PRD for millions of concurrent users. Reject hot rows, lock convoys, "
                    "N+1 queries, horizontal state that is actually a single lock, and cache designs that "
                    "authorize writes. Produce PRD_OPTIMIZED.md and ARCHITECTURE_SPEC.md."
                ),
                "behavior_data": {
                    "target_concurrent_users": 10000000,
                    "peak_writes_per_second": 50000,
                    "latency_p99_ms": 150,
                    "forbidden_db_patterns": [
                        "single hot row",
                        "cross-partition transactions",
                        "N+1 queries",
                        "unbounded offset pagination",
                        "binary floats for money or quantities",
                    ],
                    "required_outputs": ["PRD_OPTIMIZED.md", "ARCHITECTURE_SPEC.md"],
                },
            },
            {
                "id": "tdd_spec_writer",
                "display_name": "TDD Spec Writer",
                "role_type": "tdd",
                "cursor_mode": "agent",
                "model": "composer-1.5",
                "timeout_s": 600,
                "max_retries": 2,
                "require_approval_before": False,
                "approve_every_entry": False,
                "enabled_skills": ["superpowers", "gtk", "claude-mem-cursor"],
                "position": {"x": 340, "y": 40},
                "system_prompt": (
                    "You write failing tests and nothing else. Follow red-green-refactor, stopping at red. "
                    "Put tests strictly under tests/. Do not create or modify files under src/. "
                    "Cover the contract in ARCHITECTURE_SPEC.md, including conflict, idempotency, and integer precision. "
                    "Do not stub production code to force a pass."
                ),
                "behavior_data": {
                    "allowed_paths": ["tests/"],
                    "forbidden_paths": ["src/"],
                    "style": "red-green-refactor",
                    "stop_at": "red",
                },
            },
            {
                "id": "pre_impl_gate",
                "display_name": "Pre-implementation Gate",
                "role_type": "gate",
                "cursor_mode": "plan",
                "model": "",
                "timeout_s": 30,
                "max_retries": 0,
                "require_approval_before": False,
                "approve_every_entry": False,
                "enabled_skills": [
                    "founder-skill",
                    "napkin",
                    "ponytail",
                    "claude-mem-cursor",
                    "awesome-design-md",
                    "graphify",
                    "superpowers",
                    "gtk",
                ],
                "position": {"x": 680, "y": 40},
                "system_prompt": (
                    "Pause point. The orchestrator stops before the implementer so a human can review the "
                    "optimized PRD, the architecture spec, and the eight pre-installed skills."
                ),
                "behavior_data": {"prepares": "implementer"},
            },
            {
                "id": "implementer",
                "display_name": "Implementer",
                "role_type": "implementer",
                "cursor_mode": "agent",
                "model": "composer-1.5",
                "timeout_s": 900,
                "max_retries": 3,
                "require_approval_before": True,
                "approve_every_entry": False,
                "enabled_skills": ["superpowers", "ponytail", "awesome-design-md", "gtk", "claude-mem-cursor"],
                "position": {"x": 1020, "y": 40},
                "system_prompt": (
                    "You write production code until the tests pass. Do not modify files under tests/. "
                    "Follow the architecture spec. Keep modules small, names domain-accurate, and the write "
                    "path free of read-modify-write. If a review or QA note is attached, address those lines "
                    "without expanding scope."
                ),
                "behavior_data": {
                    "allowed_paths": ["src/", "DESIGN.md"],
                    "forbidden_paths": ["tests/"],
                    "done_when": "tests_pass",
                },
            },
            {
                "id": "adversarial_reviewer",
                "display_name": "Adversarial Reviewer",
                "role_type": "reviewer",
                "cursor_mode": "plan",
                "model": "gpt-5",
                "timeout_s": 600,
                "max_retries": 3,
                "require_approval_before": False,
                "approve_every_entry": False,
                "enabled_skills": ["ponytail", "graphify", "claude-mem-cursor"],
                "position": {"x": 1020, "y": 300},
                "system_prompt": (
                    "You are a hostile reviewer in plan mode. Compare the git diff to ARCHITECTURE_SPEC.md. "
                    "Check hygiene, security, integer precision, idempotency, and concurrency. "
                    "If the diff edits tests to weaken them, or the write path can oversell, return VERDICT: FAIL "
                    "with file and line notes. Return VERDICT: PASS only when you would ship it."
                ),
                "behavior_data": {
                    "must_cite": ["ARCHITECTURE_SPEC.md"],
                    "focus": ["hygiene", "security", "concurrency", "precision"],
                },
            },
            {
                "id": "live_10m_qa_db_auditor",
                "display_name": "Live 10m QA / DB Auditor",
                "role_type": "qa_auditor",
                "cursor_mode": "plan",
                "model": "gpt-5",
                "timeout_s": 900,
                "max_retries": 2,
                "require_approval_before": False,
                "approve_every_entry": False,
                "enabled_skills": ["gtk", "claude-mem-cursor"],
                "position": {"x": 680, "y": 300},
                "system_prompt": (
                    "You are the QA and data auditor in plan mode. A harness has already run the sustained window "
                    "and read-only database checks. Read the harness report. Fail on integrity errors, float money, "
                    "orphaned rows, or a latency budget miss. If the design itself cannot meet the scale budget, "
                    "return VERDICT: SCALE_ISSUE so the architect reopens the spec. Otherwise VERDICT: PASS or FAIL."
                ),
                "behavior_data": {
                    "target_concurrent_users": 10000000,
                    "min_duration_seconds": 600,
                    "latency_sla_ms": 200,
                    "error_rate_max": 0.001,
                    "checks": [
                        "EXPLAIN ANALYZE",
                        "foreign key integrity",
                        "numeric precision",
                        "orphaned records",
                    ],
                },
            },
            {
                "id": "feature_complete",
                "display_name": "Feature Complete",
                "role_type": "terminal",
                "cursor_mode": "plan",
                "model": "",
                "timeout_s": 10,
                "max_retries": 0,
                "require_approval_before": False,
                "approve_every_entry": False,
                "enabled_skills": [],
                "position": {"x": 340, "y": 300},
                "system_prompt": "Terminal sink. The feature passed QA.",
                "behavior_data": {},
            },
        ],
        "edges": [
            _edge("e-arch-tdd", "prd_scale_architect", "tdd_spec_writer", "always", "out", "in"),
            _edge("e-tdd-gate", "tdd_spec_writer", "pre_impl_gate", "always", "out", "in"),
            _edge("e-gate-impl", "pre_impl_gate", "implementer", "always", "out", "in"),
            _edge("e-impl-rev", "implementer", "adversarial_reviewer", "always", "out", "in"),
            _edge("e-rev-fail", "adversarial_reviewer", "implementer", "on_fail", "fail", "back"),
            _edge("e-rev-pass", "adversarial_reviewer", "live_10m_qa_db_auditor", "on_pass", "out", "in"),
            _edge("e-qa-fail", "live_10m_qa_db_auditor", "implementer", "on_fail", "fail", "back"),
            _edge("e-qa-scale", "live_10m_qa_db_auditor", "prd_scale_architect", "on_scale_issue", "scale", "back"),
            _edge("e-qa-pass", "live_10m_qa_db_auditor", "feature_complete", "on_pass", "out", "in"),
        ],
    }


def _edge(edge_id: str, source: str, target: str, condition: str, source_handle: str, target_handle: str) -> dict:
    return {
        "id": edge_id,
        "source": source,
        "target": target,
        "condition": condition,
        "source_handle": source_handle,
        "target_handle": target_handle,
    }
