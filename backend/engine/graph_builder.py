"""Compile a stored flow document into a LangGraph StateGraph.

`interrupt_before` is the union of the flow's list and every node with
`require_approval_before`. The default template therefore compiles with
`interrupt_before=["implementer"]`. Retry re-entries are resumed by the runner
when `approve_every_entry` is false, so a review rejection does not demand a
second human approval.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from backend.config import checkpoint_path
from backend.engine.runtime import make_executor
from backend.events import EventBus
from backend.marketplace.manager import SkillManager
from backend.storage.session_store import FeatureSessionStore

ALLOWED_CONDITIONS = {"always", "on_pass", "on_fail", "on_scale_issue"}
ALLOWED_ROLES = {"architect", "tdd", "implementer", "reviewer", "qa_auditor", "custom", "gate", "terminal"}
ALLOWED_MODES = {"plan", "ask", "agent"}


class FlowError(ValueError):
    pass


class PipelineState(TypedDict, total=False):
    feature_id: str
    flow_id: str
    workspace: str
    prd: str
    artifacts: dict
    retry_counts: dict
    route: str
    verdict: str
    last_node: str
    last_output: str
    error: str
    qa_report: dict
    approval_packet: str


def validate_flow(flow: dict[str, Any]) -> dict[str, Any]:
    if not flow.get("id"):
        raise FlowError("Flow id is required")
    nodes = flow.get("nodes") or []
    if not nodes:
        raise FlowError("Flow needs at least one node")
    ids = [node.get("id") for node in nodes]
    if any(not node_id or not isinstance(node_id, str) for node_id in ids):
        raise FlowError("Every node needs a string id")
    if len(ids) != len(set(ids)):
        raise FlowError("Node ids must be unique")
    known = set(ids)
    entry = flow.get("entry") or ids[0]
    if entry not in known:
        raise FlowError(f"Entry node '{entry}' is not in the flow")
    for node in nodes:
        if node.get("role_type", "custom") not in ALLOWED_ROLES:
            raise FlowError(f"Unsupported role '{node.get('role_type')}' on {node['id']}")
        if node.get("cursor_mode", "agent") not in ALLOWED_MODES:
            raise FlowError(f"Unsupported cursor mode '{node.get('cursor_mode')}' on {node['id']}")
        node.setdefault("display_name", node["id"])
        node.setdefault("system_prompt", "")
        node.setdefault("behavior_data", {})
        node.setdefault("enabled_skills", [])
        node.setdefault("model", "")
        node.setdefault("provider", "cursor")
        node.setdefault("timeout_s", 1800)
        node.setdefault("max_retries", 3)
        node.setdefault("require_approval_before", False)
        node.setdefault("approve_every_entry", False)
        node.setdefault("enabled", True)
        node.setdefault("position", {"x": 0, "y": 0})
        node.setdefault("cursor_mode", "agent")
        node.setdefault("role_type", "custom")
    edges = flow.get("edges") or []
    edge_ids = []
    for index, edge in enumerate(edges):
        edge.setdefault("id", f"e-{index}-{edge.get('source')}-{edge.get('target')}")
        edge_ids.append(edge["id"])
        if edge.get("source") not in known or edge.get("target") not in known:
            raise FlowError(f"Edge {edge['id']} points at an unknown node")
        condition = edge.get("condition") or "always"
        if condition not in ALLOWED_CONDITIONS:
            raise FlowError(f"Edge {edge['id']} has unknown condition '{condition}'")
        edge["condition"] = condition
        edge.setdefault("source_handle", "fail" if condition == "on_fail" else "scale" if condition == "on_scale_issue" else "out")
        edge.setdefault("target_handle", "back" if condition in {"on_fail", "on_scale_issue"} else "in")
    if len(edge_ids) != len(set(edge_ids)):
        raise FlowError("Edge ids must be unique")
    for node_id in flow.get("interrupt_before") or []:
        if node_id not in known:
            raise FlowError(f"interrupt_before references unknown node '{node_id}'")
    flow["entry"] = entry
    flow.setdefault("name", flow["id"])
    flow.setdefault("interrupt_before", [])
    return flow


def interrupt_nodes(flow: dict[str, Any]) -> list[str]:
    disabled = {node["id"] for node in flow["nodes"] if node.get("enabled", True) is False}
    ordered: list[str] = []
    for node_id in flow.get("interrupt_before") or []:
        if node_id not in ordered and node_id not in disabled:
            ordered.append(node_id)
    for node in flow["nodes"]:
        if node.get("require_approval_before") and node["id"] not in ordered and node["id"] not in disabled:
            ordered.append(node["id"])
    return ordered


def compile_flow(flow: dict[str, Any], store: FeatureSessionStore, skills: SkillManager, bus: EventBus, checkpointer):
    flow = validate_flow(flow)
    graph = StateGraph(PipelineState)
    for node in flow["nodes"]:
        graph.add_node(node["id"], make_executor(node["id"], store, skills, bus))
    graph.add_edge(START, flow["entry"])
    outgoing: dict[str, list[dict]] = {node["id"]: [] for node in flow["nodes"]}
    for edge in flow["edges"]:
        outgoing[edge["source"]].append(edge)
    for node in flow["nodes"]:
        edges = outgoing[node["id"]]
        if not edges:
            graph.add_edge(node["id"], END)
            continue
        if len(edges) == 1 and edges[0]["condition"] == "always":
            graph.add_edge(node["id"], edges[0]["target"])
            continue
        mapping = {edge["condition"]: edge["target"] for edge in edges}
        mapping["circuit_open"] = END

        def router(state: PipelineState, *args: Any, mapping: dict[str, str] = mapping) -> str:
            route = state.get("route") or "on_pass"
            if route not in mapping:
                return "circuit_open" if "circuit_open" in mapping else next(iter(mapping))
            return route

        graph.add_conditional_edges(node["id"], router, mapping)
    interrupts = interrupt_nodes(flow)
    if interrupts:
        return graph.compile(checkpointer=checkpointer, interrupt_before=interrupts)
    return graph.compile(checkpointer=checkpointer)


def open_checkpointer(path: Path | None = None):
    """Return a SQLite LangGraph saver. The connection is kept on the saver object."""
    target = path or checkpoint_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    from langgraph.checkpoint.sqlite import SqliteSaver

    connection = sqlite3.connect(str(target), check_same_thread=False)
    saver = SqliteSaver(connection)
    setup = getattr(saver, "setup", None)
    if callable(setup):
        setup()
    saver._jedoc_connection = connection  # type: ignore[attr-defined]
    return saver
