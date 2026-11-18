"""Jedoc HTTP and WebSocket server."""

from __future__ import annotations

import asyncio
import json
import re
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from backend.config import checkpoint_path, cors_origins, data_dir, resolved_execution_mode
from backend.engine.git_target import GitError, bind_workspace, inspect_repo, list_projects, pick_project_folder
from backend.engine.project_chat import iter_project_chat
from backend.engine.graph_builder import FlowError, validate_flow
from backend.engine.runner import PipelineRunner, new_thread_id
from backend.engine.templates import FLOW_ID
from backend.events import EventBus
from backend.marketplace.manager import SkillError, SkillManager
from backend.providers.cursor_cli import agent_status, begin_cursor_login, cursor_logout, list_cursor_models
from backend.storage.session_store import FeatureSessionStore


class FeatureIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    prd: str = ""
    workspace_path: str | None = None
    flow_id: str | None = None
    project_path: str | None = None
    branch: str | None = None
    use_worktree: bool = False


class TargetIn(BaseModel):
    project_path: str
    branch: str
    use_worktree: bool = False


class ApproveIn(BaseModel):
    note: str = ""


class FlowIn(BaseModel):
    definition: dict[str, Any]


class NodePatch(BaseModel):
    display_name: str | None = None
    role_type: str | None = None
    cursor_mode: str | None = None
    model: str | None = None
    system_prompt: str | None = None
    behavior_data: dict[str, Any] | None = None
    enabled_skills: list[str] | None = None
    require_approval_before: bool | None = None
    approve_every_entry: bool | None = None
    max_retries: int | None = None
    timeout_s: int | None = None
    position: dict[str, float] | None = None
    provider: str | None = None
    enabled: bool | None = None


class EdgeIn(BaseModel):
    source: str
    target: str
    condition: str = "on_pass"
    source_handle: str | None = None
    target_handle: str | None = None


class ToggleIn(BaseModel):
    enabled: bool
    workspace: str | None = None
    skill_ids: list[str] | None = None


class ContentIn(BaseModel):
    path: str
    content: str
    workspace: str | None = None
    skill_ids: list[str] | None = None


class SyncIn(BaseModel):
    workspace: str
    skill_ids: list[str] | None = None


class ProjectChatIn(BaseModel):
    workspace: str
    message: str = Field(min_length=1, max_length=20000)
    mode: str = "ask"
    model: str = ""
    provider: str = "cursor"
    thread_id: str = ""


class ProjectThreadIn(BaseModel):
    workspace: str
    thread_id: str = ""


class ProviderIn(BaseModel):
    api_key: str | None = None
    clear_api_key: bool = False
    endpoint: str | None = None
    enabled: bool | None = None


def create_app() -> FastAPI:
    store = FeatureSessionStore()
    skills = SkillManager(store)
    bus = EventBus(store)
    runner = PipelineRunner(store, skills, bus)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        import aiosqlite
        from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

        path = checkpoint_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(str(path)) as connection:
            saver = AsyncSqliteSaver(connection)
            await saver.setup()
            runner.checkpointer = saver
            runner.startup()
            yield
        for task in list(runner.tasks.values()):
            if not task.done():
                task.cancel()

    app = FastAPI(title="Jedoc", version="1.0.0", lifespan=lifespan)
    app.state.store = store
    app.state.skills = skills
    app.state.bus = bus
    app.state.runner = runner
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins(),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(SkillError)
    async def skill_error(_, exc: SkillError):
        from fastapi.responses import JSONResponse

        return JSONResponse(status_code=400, content={"detail": str(exc)})

    @app.exception_handler(FlowError)
    async def flow_error(_, exc: FlowError):
        from fastapi.responses import JSONResponse

        return JSONResponse(status_code=400, content={"detail": str(exc)})

    @app.exception_handler(GitError)
    async def git_error(_, exc: GitError):
        from fastapi.responses import JSONResponse

        return JSONResponse(status_code=400, content={"detail": str(exc)})

    @app.get("/api/health")
    async def health():
        return {"ok": True, "service": "jedoc", "execution_mode": resolved_execution_mode()}

    @app.get("/api/agent/status")
    async def status():
        return await agent_status(app.state.store.provider_credentials("cursor"))

    @app.get("/api/git/projects")
    def git_projects():
        return list_projects()

    @app.get("/api/git/repo")
    def git_repo(path: str):
        return inspect_repo(path)

    @app.post("/api/git/pick")
    async def git_pick():
        path = await pick_project_folder()
        if not path:
            return {"path": None, "repo": None}
        try:
            repo = inspect_repo(path)
        except GitError:
            repo = None
        return {"path": path, "repo": repo}

    @app.get("/api/project-chat")
    def get_project_chat(workspace: str):
        path = str(Path(workspace).expanduser().resolve())
        payload = app.state.store.project_chat(path)
        payload["execution_mode"] = resolved_execution_mode()
        return payload

    @app.delete("/api/project-chat")
    def delete_project_chat(workspace: str):
        path = str(Path(workspace).expanduser().resolve())
        app.state.store.reset_project_chat(path)
        return {"ok": True}

    @app.post("/api/project-chat/new")
    def new_project_chat(body: ProjectThreadIn):
        path = str(Path(body.workspace).expanduser().resolve())
        if not Path(path).is_dir():
            raise HTTPException(400, "That project folder does not exist")
        payload = app.state.store.start_project_thread(path)
        payload["execution_mode"] = resolved_execution_mode()
        return payload

    @app.post("/api/project-chat/open")
    def open_project_chat(body: ProjectThreadIn):
        path = str(Path(body.workspace).expanduser().resolve())
        if not body.thread_id:
            raise HTTPException(400, "Choose a chat")
        payload = app.state.store.open_project_thread(path, body.thread_id)
        if payload is None:
            raise HTTPException(404, "That chat is not in this project")
        payload["execution_mode"] = resolved_execution_mode()
        return payload

    @app.post("/api/project-chat")
    async def post_project_chat(body: ProjectChatIn):
        path = Path(body.workspace).expanduser().resolve()
        if not path.is_dir():
            raise HTTPException(400, "That project folder does not exist")
        message = body.message.strip()
        if not message:
            raise HTTPException(400, "Write a message first")

        async def events():
            queue: asyncio.Queue[dict | None] = asyncio.Queue()

            async def produce() -> None:
                try:
                    async for event in iter_project_chat(
                        app.state.store,
                        workspace=str(path),
                        message=message,
                        mode=body.mode,
                        model=body.model,
                        provider=body.provider or "cursor",
                        thread_id=body.thread_id,
                    ):
                        await queue.put(event)
                except ValueError as exc:
                    await queue.put({"type": "error", "detail": str(exc)})
                except Exception as exc:
                    await queue.put({"type": "error", "detail": str(exc) or "The provider chat failed"})
                finally:
                    await queue.put(None)

            producer = asyncio.create_task(produce())
            try:
                while True:
                    try:
                        event = await asyncio.wait_for(queue.get(), timeout=10)
                    except TimeoutError:
                        # Keep the proxy connection alive while Cursor is still thinking.
                        yield ": ping\n\n"
                        continue
                    if event is None:
                        break
                    yield _sse(event)
            finally:
                producer.cancel()

        return StreamingResponse(
            events(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
        )

    @app.get("/api/providers")
    async def list_provider_accounts():
        providers = app.state.store.list_providers()
        status_info = await agent_status(app.state.store.provider_credentials("cursor"))
        for item in providers:
            if item["id"] == "cursor":
                item["authenticated"] = bool(status_info.get("authenticated"))
                item["auth_detail"] = status_info.get("detail") or ""
                item["installed"] = bool(status_info.get("installed"))
        return providers

    @app.put("/api/providers/cursor")
    def save_cursor(body: ProviderIn):
        saved = app.state.store.update_provider(
            "cursor",
            api_key=body.api_key,
            clear_api_key=body.clear_api_key,
            endpoint=body.endpoint,
            enabled=body.enabled,
        )
        if saved is None:
            raise HTTPException(404, "Cursor provider is not installed")
        return saved

    @app.post("/api/providers/cursor/refresh")
    async def refresh_cursor():
        credentials = app.state.store.provider_credentials("cursor")
        status_info = await agent_status(credentials)
        listed = await list_cursor_models(credentials)
        models = listed.get("models") or []
        if models:
            app.state.store.update_provider("cursor", models=models)
        provider = next(item for item in app.state.store.list_providers() if item["id"] == "cursor")
        provider["authenticated"] = bool(status_info.get("authenticated"))
        provider["auth_detail"] = status_info.get("detail") or ""
        provider["installed"] = bool(status_info.get("installed"))
        provider["models_error"] = listed.get("error") or ""
        return provider

    @app.post("/api/providers/cursor/login")
    async def login_cursor():
        return await begin_cursor_login(app.state.store.provider_credentials("cursor"))

    @app.post("/api/providers/cursor/logout")
    async def logout_cursor():
        result = await cursor_logout(app.state.store.provider_credentials("cursor"))
        return result

    @app.get("/api/sample-prd")
    def sample_prd():
        path = Path(__file__).resolve().parents[1] / "engine" / "sample_prd.md"
        return {"markdown": path.read_text(encoding="utf-8")}

    @app.get("/api/flows")
    def list_flows():
        return app.state.store.list_flows()

    @app.get("/api/flows/{flow_id}")
    def get_flow(flow_id: str):
        flow = app.state.store.get_flow(flow_id)
        if flow is None:
            raise HTTPException(404, "Flow not found")
        return flow

    @app.put("/api/flows/{flow_id}")
    def put_flow(flow_id: str, body: FlowIn):
        definition = dict(body.definition)
        definition["id"] = flow_id
        saved = validate_flow(definition)
        existing = app.state.store.get_flow(flow_id)
        return app.state.store.save_flow(saved, is_template=bool(existing and existing.get("is_template")))

    @app.post("/api/flows/{flow_id}/nodes")
    def add_node(flow_id: str, body: NodePatch):
        flow = _require_flow(app, flow_id)
        node_id = f"agent_{uuid.uuid4().hex[:8]}"
        node = {
            "id": node_id,
            "display_name": body.display_name or "Custom Agent",
            "role_type": body.role_type or "custom",
            "cursor_mode": body.cursor_mode or "agent",
            "model": body.model or "",
            "provider": body.provider or "cursor",
            "system_prompt": body.system_prompt or "You are a custom Jedoc agent. Follow the PRD and the output contract.",
            "behavior_data": body.behavior_data or {},
            "enabled_skills": body.enabled_skills if body.enabled_skills is not None else _enabled_catalog(app),
            "require_approval_before": bool(body.require_approval_before),
            "approve_every_entry": bool(body.approve_every_entry),
            "max_retries": body.max_retries if body.max_retries is not None else 3,
            "timeout_s": body.timeout_s if body.timeout_s is not None else 600,
            "position": body.position or {"x": 80, "y": 80},
            "enabled": True if body.enabled is None else body.enabled,
        }
        flow["nodes"].append(node)
        return app.state.store.save_flow(validate_flow(flow), is_template=bool(flow.get("is_template")))

    @app.patch("/api/flows/{flow_id}/nodes/{node_id}")
    def patch_node(flow_id: str, node_id: str, body: NodePatch):
        flow = _require_flow(app, flow_id)
        node = _require_node(flow, node_id)
        data = body.model_dump(exclude_none=True)
        node.update(data)
        return app.state.store.save_flow(validate_flow(flow), is_template=bool(flow.get("is_template")))

    @app.delete("/api/flows/{flow_id}/nodes/{node_id}")
    def delete_node(flow_id: str, node_id: str):
        flow = _require_flow(app, flow_id)
        _require_node(flow, node_id)
        flow["nodes"] = [node for node in flow["nodes"] if node["id"] != node_id]
        flow["edges"] = [edge for edge in flow["edges"] if edge["source"] != node_id and edge["target"] != node_id]
        flow["interrupt_before"] = [item for item in flow.get("interrupt_before") or [] if item != node_id]
        if flow.get("entry") == node_id:
            flow["entry"] = flow["nodes"][0]["id"] if flow["nodes"] else ""
        return app.state.store.save_flow(validate_flow(flow), is_template=bool(flow.get("is_template")))

    @app.post("/api/flows/{flow_id}/edges")
    def add_edge(flow_id: str, body: EdgeIn):
        flow = _require_flow(app, flow_id)
        edge = {
            "id": f"e-{uuid.uuid4().hex[:8]}",
            "source": body.source,
            "target": body.target,
            "condition": body.condition,
        }
        if body.source_handle:
            edge["source_handle"] = body.source_handle
        if body.target_handle:
            edge["target_handle"] = body.target_handle
        flow["edges"].append(edge)
        return app.state.store.save_flow(validate_flow(flow), is_template=bool(flow.get("is_template")))

    @app.delete("/api/flows/{flow_id}/edges/{edge_id}")
    def delete_edge(flow_id: str, edge_id: str):
        flow = _require_flow(app, flow_id)
        remaining = [edge for edge in flow["edges"] if edge["id"] != edge_id]
        if len(remaining) == len(flow["edges"]):
            raise HTTPException(404, "Edge not found")
        flow["edges"] = remaining
        return app.state.store.save_flow(validate_flow(flow), is_template=bool(flow.get("is_template")))

    @app.get("/api/skills")
    def list_skills(workspace: str | None = None):
        return app.state.skills.list_skills(workspace)

    @app.patch("/api/skills/{skill_id}/toggle")
    def toggle_skill(skill_id: str, body: ToggleIn):
        item = app.state.skills.set_enabled(skill_id, body.enabled)
        synced = None
        if body.workspace:
            ids = body.skill_ids if body.skill_ids is not None else _enabled_catalog(app)
            synced = app.state.skills.sync(body.workspace, ids)
        return {"skill": item, "sync": synced}

    @app.put("/api/skills/{skill_id}/content")
    def put_skill_content(skill_id: str, body: ContentIn):
        item = app.state.skills.set_content(skill_id, body.path, body.content)
        synced = None
        if body.workspace:
            ids = body.skill_ids if body.skill_ids is not None else _enabled_catalog(app)
            synced = app.state.skills.sync(body.workspace, ids)
        return {"skill": item, "sync": synced}

    @app.post("/api/skills/sync")
    def sync_skills(body: SyncIn):
        if body.skill_ids is None:
            return app.state.skills.sync_global(body.workspace)
        return app.state.skills.sync(body.workspace, body.skill_ids)

    @app.get("/api/features")
    def list_features():
        return app.state.store.list_features()

    @app.post("/api/features", status_code=201)
    def create_feature(body: FeatureIn):
        flow_id = body.flow_id or FLOW_ID
        if app.state.store.get_flow(flow_id) is None:
            raise HTTPException(404, "Flow not found")
        bound = _bind_feature_workspace(body.name, body.prd, body.workspace_path, body.project_path, body.branch, body.use_worktree)
        return app.state.store.create_feature(
            name=body.name.strip(),
            prd=body.prd,
            workspace_path=bound["workspace_path"],
            flow_id=flow_id,
            project_path=bound["project_path"],
            branch=bound["branch"],
            use_worktree=bound["use_worktree"],
        )

    @app.patch("/api/features/{feature_id}/target")
    def set_feature_target(feature_id: str, body: TargetIn):
        feature = _require_feature(app, feature_id)
        if feature["status"] in {"running", "paused"}:
            raise HTTPException(409, "Wait until the pipeline is idle before changing the checkout")
        bound = _bind_feature_workspace(
            feature["name"],
            feature["prd"],
            None,
            body.project_path,
            body.branch,
            body.use_worktree,
        )
        updated = app.state.store.update_feature(
            feature_id,
            workspace_path=bound["workspace_path"],
            project_path=bound["project_path"],
            branch=bound["branch"],
            use_worktree=1 if bound["use_worktree"] else 0,
        )
        return updated

    @app.get("/api/features/{feature_id}")
    def get_feature(feature_id: str):
        feature = app.state.store.get_feature(feature_id)
        if feature is None:
            raise HTTPException(404, "Feature not found")
        return {
            **feature,
            "sessions": app.state.store.list_sessions(feature_id),
            "artifacts": app.state.store.list_artifacts(feature_id),
        }

    @app.post("/api/features/{feature_id}/start", status_code=202)
    async def start_feature(feature_id: str):
        feature = _require_feature(app, feature_id)
        if feature["status"] == "paused":
            raise HTTPException(409, "Feature is waiting for approval. Use approve.")
        if feature["status"] in {"running", "archived", "completed"}:
            raise HTTPException(409, f"Cannot start a feature that is {feature['status']}")
        if feature["status"] == "failed":
            app.state.store.update_feature(feature_id, thread_id=new_thread_id(), error="")
        try:
            app.state.runner.launch(feature_id, resume=False)
        except RuntimeError as exc:
            raise HTTPException(409, str(exc)) from exc
        return {"status": "running", "feature_id": feature_id}

    @app.post("/api/features/{feature_id}/approve", status_code=202)
    async def approve_feature(feature_id: str, body: ApproveIn):
        feature = _require_feature(app, feature_id)
        if feature["status"] != "paused":
            raise HTTPException(409, "Feature is not waiting for approval")
        try:
            app.state.runner.launch(feature_id, resume=True, note=body.note)
        except RuntimeError as exc:
            raise HTTPException(409, str(exc)) from exc
        return {"status": "running", "feature_id": feature_id}

    @app.post("/api/features/{feature_id}/mark-done")
    async def mark_done(feature_id: str):
        _require_feature(app, feature_id)
        archived = await app.state.runner.mark_done(feature_id)
        feature = app.state.store.get_feature(feature_id)
        return {"feature": feature, "archived_sessions": archived}

    @app.post("/api/features/{feature_id}/sessions/{agent_id}/reset")
    def reset_session(feature_id: str, agent_id: str):
        feature = _require_feature(app, feature_id)
        if feature["status"] == "running":
            raise HTTPException(409, "Wait until the feature is paused or idle before resetting a context")
        archived = app.state.store.archive_session(feature_id, agent_id)
        if archived is None:
            raise HTTPException(404, "No active session for that agent")
        return {"archived": archived, "sessions": app.state.store.list_sessions(feature_id)}

    @app.get("/api/features/{feature_id}/sessions")
    def list_sessions(feature_id: str, agent_id: str | None = None):
        _require_feature(app, feature_id)
        sessions = app.state.store.list_sessions(feature_id)
        turns = app.state.store.list_turns(feature_id, agent_id)
        return {"sessions": sessions, "turns": turns}

    @app.get("/api/features/{feature_id}/events")
    async def events_sse(feature_id: str):
        _require_feature(app, feature_id)

        async def stream():
            queue = app.state.bus.subscribe(feature_id)
            try:
                for item in app.state.store.list_audit(feature_id, limit=400):
                    yield _sse(item["payload"])
                while True:
                    try:
                        payload = await asyncio.wait_for(queue.get(), timeout=10)
                    except TimeoutError:
                        yield ": ping\n\n"
                        continue
                    yield _sse(payload)
            finally:
                app.state.bus.unsubscribe(feature_id, queue)

        return StreamingResponse(stream(), media_type="text/event-stream")

    @app.websocket("/ws/features/{feature_id}")
    async def feature_socket(feature_id: str, websocket: WebSocket):
        feature = app.state.store.get_feature(feature_id)
        if feature is None:
            await websocket.close(code=4404)
            return
        await websocket.accept()
        queue = app.state.bus.subscribe(feature_id)
        try:
            history = [item["payload"] for item in app.state.store.list_audit(feature_id, limit=400)]
            await websocket.send_json(
                {
                    "type": "hello",
                    "feature": feature,
                    "events": history,
                    "sessions": app.state.store.list_sessions(feature_id),
                    "artifacts": app.state.store.list_artifacts(feature_id),
                }
            )
            while True:
                payload = await queue.get()
                await websocket.send_json(payload)
        except WebSocketDisconnect:
            return
        finally:
            app.state.bus.unsubscribe(feature_id, queue)

    return app


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload, default=str)}\n\n"


def _require_flow(app: FastAPI, flow_id: str) -> dict:
    flow = app.state.store.get_flow(flow_id)
    if flow is None:
        raise HTTPException(404, "Flow not found")
    return flow


def _require_feature(app: FastAPI, feature_id: str) -> dict:
    feature = app.state.store.get_feature(feature_id)
    if feature is None:
        raise HTTPException(404, "Feature not found")
    return feature


def _require_node(flow: dict, node_id: str) -> dict:
    node = next((item for item in flow["nodes"] if item["id"] == node_id), None)
    if node is None:
        raise HTTPException(404, "Node not found")
    return node


def _enabled_catalog(app: FastAPI) -> list[str]:
    return [item["id"] for item in app.state.skills.list_skills() if item["enabled"]]


def _bind_feature_workspace(
    name: str,
    prd: str,
    workspace_path: str | None,
    project_path: str | None,
    branch: str | None,
    use_worktree: bool,
) -> dict[str, Any]:
    from backend.engine.workspace import prepare_workspace

    if project_path:
        bound = bind_workspace(project_path, branch or "", use_worktree, name)
        prepare_workspace(Path(bound["workspace_path"]), prd)
        return bound
    workspace = Path(workspace_path).expanduser() if workspace_path else _default_workspace(name)
    prepare_workspace(workspace, prd)
    return {
        "workspace_path": str(workspace.resolve()),
        "project_path": "",
        "branch": "",
        "use_worktree": False,
    }


def _default_workspace(name: str) -> Path:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "feature"
    return data_dir() / "workspaces" / f"{slug}-{uuid.uuid4().hex[:6]}"


app = create_app()
