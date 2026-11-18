"""SQLite persistence for features, Cursor chat sessions, flows, skills, artifacts, and audit logs.

FeatureSessionStore enforces the context rule: a (feature_id, agent_id) pair keeps one
active chat_id across retries and QA loops. Rows are archived, never deleted, by
mark-done or an explicit per-agent reset.
"""

from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import DateTime, Index, Integer, String, Text, create_engine, func, select, text, update
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from backend.config import db_path


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class FeatureRow(Base):
    __tablename__ = "features"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    prd: Mapped[str] = mapped_column(Text, default="")
    workspace_path: Mapped[str] = mapped_column(Text)
    project_path: Mapped[str] = mapped_column(Text, default="")
    branch: Mapped[str] = mapped_column(String(200), default="")
    use_worktree: Mapped[int] = mapped_column(Integer, default=0)
    flow_id: Mapped[str] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(32), default="draft")
    thread_id: Mapped[str] = mapped_column(String(64))
    error: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class AgentSessionRow(Base):
    __tablename__ = "agent_sessions"
    __table_args__ = (
        Index(
            "uq_active_session",
            "feature_id",
            "agent_id",
            unique=True,
            sqlite_where=text("status = 'active'"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    feature_id: Mapped[str] = mapped_column(String(36), index=True)
    agent_id: Mapped[str] = mapped_column(String(80), index=True)
    chat_id: Mapped[str] = mapped_column(String(160))
    files_json: Mapped[str] = mapped_column(Text, default="[]")
    status: Mapped[str] = mapped_column(String(20), default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class SessionTurnRow(Base):
    __tablename__ = "session_turns"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    feature_id: Mapped[str] = mapped_column(String(36), index=True)
    agent_id: Mapped[str] = mapped_column(String(80), index=True)
    chat_id: Mapped[str] = mapped_column(String(160))
    role: Mapped[str] = mapped_column(String(20))
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class FlowRow(Base):
    __tablename__ = "flows"

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    definition_json: Mapped[str] = mapped_column(Text)
    is_template: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class SkillStateRow(Base):
    __tablename__ = "skill_states"

    skill_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    enabled: Mapped[int] = mapped_column(Integer, default=1)
    overrides_json: Mapped[str] = mapped_column(Text, default="{}")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class ArtifactRow(Base):
    __tablename__ = "artifacts"
    __table_args__ = (Index("uq_artifact", "feature_id", "name", unique=True),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    feature_id: Mapped[str] = mapped_column(String(36), index=True)
    name: Mapped[str] = mapped_column(String(200))
    content: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class ProviderRow(Base):
    __tablename__ = "providers"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    kind: Mapped[str] = mapped_column(String(40))
    enabled: Mapped[int] = mapped_column(Integer, default=1)
    config_json: Mapped[str] = mapped_column(Text, default="{}")
    models_json: Mapped[str] = mapped_column(Text, default="[]")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class ProjectChatRow(Base):
    __tablename__ = "project_chats"

    workspace: Mapped[str] = mapped_column(Text, primary_key=True)
    chat_id: Mapped[str] = mapped_column(String(160), default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class ProjectThreadRow(Base):
    __tablename__ = "project_threads"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    workspace: Mapped[str] = mapped_column(Text, index=True)
    chat_id: Mapped[str] = mapped_column(String(160), default="")
    title: Mapped[str] = mapped_column(Text, default="")
    active: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class ProjectMessageRow(Base):
    __tablename__ = "project_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    workspace: Mapped[str] = mapped_column(Text, index=True)
    thread_id: Mapped[str] = mapped_column(String(36), default="", index=True)
    role: Mapped[str] = mapped_column(String(20))
    content: Mapped[str] = mapped_column(Text)
    mode: Mapped[str] = mapped_column(String(20), default="ask")
    files_json: Mapped[str] = mapped_column(Text, default="[]")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AuditLogRow(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    feature_id: Mapped[str] = mapped_column(String(36), index=True)
    node_id: Mapped[str] = mapped_column(String(80), default="")
    level: Mapped[str] = mapped_column(String(16), default="info")
    event_type: Mapped[str] = mapped_column(String(40))
    payload_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat()


class FeatureSessionStore:
    """Single SQLite boundary for Jedoc control-plane state."""

    def __init__(self, path: str | None = None) -> None:
        self._lock = threading.RLock()
        self.path = path or str(db_path())
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.engine = create_engine(
            f"sqlite:///{self.path}",
            connect_args={"check_same_thread": False},
            future=True,
        )
        self._session_factory = sessionmaker(self.engine, expire_on_commit=False, class_=Session)

    def init(self) -> None:
        with self._lock:
            Base.metadata.create_all(self.engine)
            self._migrate()
            self._ensure_cursor_provider()

    def _session(self) -> Session:
        return self._session_factory()

    def _migrate(self) -> None:
        with self.engine.begin() as connection:
            tables = {row[0] for row in connection.execute(text("SELECT name FROM sqlite_master WHERE type = 'table'"))}
            if "features" not in tables:
                return
            columns = {row[1] for row in connection.execute(text("PRAGMA table_info(features)"))}
            if "project_path" not in columns:
                connection.execute(text("ALTER TABLE features ADD COLUMN project_path TEXT DEFAULT ''"))
            if "branch" not in columns:
                connection.execute(text("ALTER TABLE features ADD COLUMN branch TEXT DEFAULT ''"))
            if "use_worktree" not in columns:
                connection.execute(text("ALTER TABLE features ADD COLUMN use_worktree INTEGER DEFAULT 0"))
            if "project_messages" in tables:
                message_columns = {row[1] for row in connection.execute(text("PRAGMA table_info(project_messages)"))}
                if "thread_id" not in message_columns:
                    connection.execute(text("ALTER TABLE project_messages ADD COLUMN thread_id TEXT DEFAULT ''"))
                if "files_json" not in message_columns:
                    connection.execute(text("ALTER TABLE project_messages ADD COLUMN files_json TEXT DEFAULT '[]'"))
            if "agent_sessions" in tables:
                session_columns = {row[1] for row in connection.execute(text("PRAGMA table_info(agent_sessions)"))}
                if "files_json" not in session_columns:
                    connection.execute(text("ALTER TABLE agent_sessions ADD COLUMN files_json TEXT DEFAULT '[]'"))
            if "project_threads" in tables and "project_chats" in tables and "project_messages" in tables:
                chats = connection.execute(text("SELECT workspace, chat_id, updated_at FROM project_chats")).fetchall()
                for workspace, chat_id, updated_at in chats:
                    unassigned = connection.execute(
                        text(
                            "SELECT COUNT(*) FROM project_messages WHERE workspace = :workspace "
                            "AND (thread_id IS NULL OR thread_id = '')"
                        ),
                        {"workspace": workspace},
                    ).scalar()
                    existing = connection.execute(
                        text("SELECT COUNT(*) FROM project_threads WHERE workspace = :workspace"),
                        {"workspace": workspace},
                    ).scalar()
                    if existing or not unassigned:
                        continue
                    title_row = connection.execute(
                        text(
                            "SELECT content FROM project_messages WHERE workspace = :workspace AND role = 'user' "
                            "ORDER BY id LIMIT 1"
                        ),
                        {"workspace": workspace},
                    ).fetchone()
                    title = " ".join((title_row[0] if title_row else "").split())[:80]
                    thread_id = str(uuid.uuid4())
                    stamp = updated_at or utcnow()
                    connection.execute(
                        text(
                            "INSERT INTO project_threads (id, workspace, chat_id, title, active, created_at, updated_at) "
                            "VALUES (:id, :workspace, :chat_id, :title, 1, :stamp, :stamp)"
                        ),
                        {
                            "id": thread_id,
                            "workspace": workspace,
                            "chat_id": chat_id or "",
                            "title": title,
                            "stamp": stamp,
                        },
                    )
                    connection.execute(
                        text(
                            "UPDATE project_messages SET thread_id = :thread_id WHERE workspace = :workspace "
                            "AND (thread_id IS NULL OR thread_id = '')"
                        ),
                        {"thread_id": thread_id, "workspace": workspace},
                    )

    def _ensure_cursor_provider(self) -> None:
        with self._session() as session:
            if session.get(ProviderRow, "cursor") is None:
                session.add(
                    ProviderRow(
                        id="cursor",
                        kind="cursor",
                        enabled=1,
                        config_json="{}",
                        models_json="[]",
                        updated_at=utcnow(),
                    )
                )
                session.commit()

    # ----- flows -----

    def save_flow(self, definition: dict[str, Any], *, is_template: bool = False) -> dict[str, Any]:
        with self._lock:
            with self._session() as session:
                row = session.get(FlowRow, definition["id"])
                now = utcnow()
                payload = json.dumps(definition)
                if row is None:
                    row = FlowRow(
                        id=definition["id"],
                        name=definition.get("name") or definition["id"],
                        definition_json=payload,
                        is_template=1 if is_template else 0,
                        created_at=now,
                        updated_at=now,
                    )
                    session.add(row)
                else:
                    row.name = definition.get("name") or row.name
                    row.definition_json = payload
                    row.is_template = 1 if is_template else row.is_template
                    row.updated_at = now
                session.commit()
        return definition

    def list_flows(self) -> list[dict[str, Any]]:
        with self._lock:
            with self._session() as session:
                rows = session.scalars(select(FlowRow).order_by(FlowRow.name)).all()
                return [self._flow_dict(row) for row in rows]

    def get_flow(self, flow_id: str) -> dict[str, Any] | None:
        with self._lock:
            with self._session() as session:
                row = session.get(FlowRow, flow_id)
                return self._flow_dict(row) if row else None

    def _flow_dict(self, row: FlowRow) -> dict[str, Any]:
        definition = json.loads(row.definition_json)
        definition["id"] = row.id
        definition["name"] = row.name
        definition["is_template"] = bool(row.is_template)
        definition["updated_at"] = _iso(row.updated_at)
        return definition

    # ----- features -----

    def create_feature(
        self,
        *,
        name: str,
        prd: str,
        workspace_path: str,
        flow_id: str,
        feature_id: str | None = None,
        project_path: str = "",
        branch: str = "",
        use_worktree: bool = False,
    ) -> dict[str, Any]:
        feature_id = feature_id or str(uuid.uuid4())
        now = utcnow()
        row = FeatureRow(
            id=feature_id,
            name=name,
            prd=prd,
            workspace_path=workspace_path,
            project_path=project_path,
            branch=branch,
            use_worktree=1 if use_worktree else 0,
            flow_id=flow_id,
            status="draft",
            thread_id=feature_id,
            error="",
            created_at=now,
            updated_at=now,
        )
        with self._lock:
            with self._session() as session:
                session.add(row)
                session.commit()
                session.refresh(row)
                return self._feature_dict(row)

    def list_features(self) -> list[dict[str, Any]]:
        with self._lock:
            with self._session() as session:
                rows = session.scalars(select(FeatureRow).order_by(FeatureRow.created_at.desc())).all()
                return [self._feature_dict(row) for row in rows]

    def get_feature(self, feature_id: str) -> dict[str, Any] | None:
        with self._lock:
            with self._session() as session:
                row = session.get(FeatureRow, feature_id)
                if row is None:
                    return None
                feature = self._feature_dict(row)
            feature["sessions"] = self.list_sessions(feature_id)
            return feature

    def update_feature(self, feature_id: str, **fields: Any) -> dict[str, Any] | None:
        with self._lock:
            with self._session() as session:
                row = session.get(FeatureRow, feature_id)
                if row is None:
                    return None
                for key, value in fields.items():
                    if hasattr(row, key) and key != "id":
                        setattr(row, key, value)
                row.updated_at = utcnow()
                session.commit()
                session.refresh(row)
                return self._feature_dict(row)

    def _feature_dict(self, row: FeatureRow) -> dict[str, Any]:
        return {
            "id": row.id,
            "name": row.name,
            "prd": row.prd,
            "workspace_path": row.workspace_path,
            "project_path": row.project_path or "",
            "branch": row.branch or "",
            "use_worktree": bool(row.use_worktree),
            "flow_id": row.flow_id,
            "status": row.status,
            "thread_id": row.thread_id,
            "error": row.error or "",
            "created_at": _iso(row.created_at),
            "updated_at": _iso(row.updated_at),
        }

    # ----- providers -----

    def list_providers(self) -> list[dict[str, Any]]:
        with self._lock:
            with self._session() as session:
                rows = session.scalars(select(ProviderRow).order_by(ProviderRow.id)).all()
                return [self._public_provider(row) for row in rows]

    def provider_credentials(self, provider_id: str) -> dict[str, str]:
        with self._lock:
            with self._session() as session:
                row = session.get(ProviderRow, provider_id)
                if row is None:
                    return {}
                config = json.loads(row.config_json or "{}")
        env: dict[str, str] = {}
        if config.get("api_key"):
            env["CURSOR_API_KEY"] = str(config["api_key"])
        if config.get("endpoint"):
            env["CURSOR_API_ENDPOINT"] = str(config["endpoint"])
        return env

    def update_provider(
        self,
        provider_id: str,
        *,
        api_key: str | None = None,
        clear_api_key: bool = False,
        endpoint: str | None = None,
        enabled: bool | None = None,
        models: list[str] | None = None,
    ) -> dict[str, Any] | None:
        with self._lock:
            with self._session() as session:
                row = session.get(ProviderRow, provider_id)
                if row is None:
                    return None
                config = json.loads(row.config_json or "{}")
                if clear_api_key:
                    config.pop("api_key", None)
                elif api_key is not None and api_key != "":
                    config["api_key"] = api_key
                if endpoint is not None:
                    config["endpoint"] = endpoint.strip()
                row.config_json = json.dumps(config)
                if enabled is not None:
                    row.enabled = 1 if enabled else 0
                if models is not None:
                    row.models_json = json.dumps(models)
                row.updated_at = utcnow()
                session.commit()
                session.refresh(row)
                return self._public_provider(row)

    def _public_provider(self, row: ProviderRow) -> dict[str, Any]:
        config = json.loads(row.config_json or "{}")
        key = str(config.get("api_key") or "")
        hint = f"••••{key[-4:]}" if len(key) >= 4 else ("••••" if key else "")
        return {
            "id": row.id,
            "name": "Cursor" if row.id == "cursor" else row.id,
            "kind": row.kind,
            "enabled": bool(row.enabled),
            "has_api_key": bool(key),
            "api_key_hint": hint,
            "endpoint": str(config.get("endpoint") or ""),
            "models": json.loads(row.models_json or "[]"),
        }

    # ----- sessions (strict chat_id persistence) -----

    def get_active_session(self, feature_id: str, agent_id: str) -> dict[str, Any] | None:
        with self._lock:
            with self._session() as session:
                row = session.scalar(
                    select(AgentSessionRow).where(
                        AgentSessionRow.feature_id == feature_id,
                        AgentSessionRow.agent_id == agent_id,
                        AgentSessionRow.status == "active",
                    )
                )
                return self._session_dict(row) if row else None

    def get_or_create_session(self, feature_id: str, agent_id: str, chat_id_factory) -> dict[str, Any]:
        """Return the active chat_id, creating one only when no active row exists.

        chat_id_factory is called without the store lock held only after a miss is
        confirmed. A second check closes the race with another creator.
        """
        existing = self.get_active_session(feature_id, agent_id)
        if existing:
            return existing
        chat_id = chat_id_factory()
        with self._lock:
            with self._session() as session:
                row = session.scalar(
                    select(AgentSessionRow).where(
                        AgentSessionRow.feature_id == feature_id,
                        AgentSessionRow.agent_id == agent_id,
                        AgentSessionRow.status == "active",
                    )
                )
                if row is not None:
                    return self._session_dict(row)
                row = AgentSessionRow(
                    feature_id=feature_id,
                    agent_id=agent_id,
                    chat_id=chat_id,
                    status="active",
                    created_at=utcnow(),
                )
                session.add(row)
                session.commit()
                session.refresh(row)
                return self._session_dict(row)

    def list_sessions(self, feature_id: str, *, include_archived: bool = True) -> list[dict[str, Any]]:
        with self._lock:
            with self._session() as session:
                stmt = select(AgentSessionRow).where(AgentSessionRow.feature_id == feature_id)
                if not include_archived:
                    stmt = stmt.where(AgentSessionRow.status == "active")
                rows = session.scalars(stmt.order_by(AgentSessionRow.created_at)).all()
                return [self._session_dict(row) for row in rows]

    def archive_session(self, feature_id: str, agent_id: str) -> dict[str, Any] | None:
        """Archive the active chat. The row stays. The next turn may create a new chat_id."""
        with self._lock:
            with self._session() as session:
                row = session.scalar(
                    select(AgentSessionRow).where(
                        AgentSessionRow.feature_id == feature_id,
                        AgentSessionRow.agent_id == agent_id,
                        AgentSessionRow.status == "active",
                    )
                )
                if row is None:
                    return None
                row.status = "archived"
                row.archived_at = utcnow()
                session.commit()
                session.refresh(row)
                return self._session_dict(row)

    def archive_feature_sessions(self, feature_id: str) -> list[dict[str, Any]]:
        """Mark-done gate. Archives every active chat for the feature. Does not delete rows."""
        with self._lock:
            with self._session() as session:
                rows = session.scalars(
                    select(AgentSessionRow).where(
                        AgentSessionRow.feature_id == feature_id,
                        AgentSessionRow.status == "active",
                    )
                ).all()
                now = utcnow()
                archived = []
                for row in rows:
                    row.status = "archived"
                    row.archived_at = now
                    archived.append(self._session_dict(row))
                feature = session.get(FeatureRow, feature_id)
                if feature is not None:
                    feature.status = "archived"
                    feature.updated_at = now
                session.commit()
                return archived

    def set_agent_chat_id(self, feature_id: str, agent_id: str, chat_id: str) -> None:
        """Point the active agent session at the Cursor CLI session, including turns already stored on the previous id."""
        with self._lock:
            with self._session() as session:
                row = session.scalar(
                    select(AgentSessionRow).where(
                        AgentSessionRow.feature_id == feature_id,
                        AgentSessionRow.agent_id == agent_id,
                        AgentSessionRow.status == "active",
                    )
                )
                if row is None or not chat_id or row.chat_id == chat_id:
                    return
                previous = row.chat_id
                row.chat_id = chat_id
                if previous:
                    session.execute(
                        update(SessionTurnRow)
                        .where(
                            SessionTurnRow.feature_id == feature_id,
                            SessionTurnRow.agent_id == agent_id,
                            SessionTurnRow.chat_id == previous,
                        )
                        .values(chat_id=chat_id)
                    )
                session.commit()

    def set_session_files(self, feature_id: str, agent_id: str, files: list[dict[str, Any]]) -> None:
        with self._lock:
            with self._session() as session:
                row = session.scalar(
                    select(AgentSessionRow).where(
                        AgentSessionRow.feature_id == feature_id,
                        AgentSessionRow.agent_id == agent_id,
                        AgentSessionRow.status == "active",
                    )
                )
                if row is None:
                    return
                row.files_json = json.dumps(files)
                session.commit()

    def _session_dict(self, row: AgentSessionRow) -> dict[str, Any]:
        try:
            files = json.loads(row.files_json or "[]")
        except json.JSONDecodeError:
            files = []
        return {
            "id": row.id,
            "feature_id": row.feature_id,
            "agent_id": row.agent_id,
            "chat_id": row.chat_id,
            "files": files if isinstance(files, list) else [],
            "status": row.status,
            "created_at": _iso(row.created_at),
            "archived_at": _iso(row.archived_at),
        }

    def append_turn(self, feature_id: str, agent_id: str, chat_id: str, role: str, content: str) -> None:
        content = content[:200_000]
        with self._lock:
            with self._session() as session:
                session.add(
                    SessionTurnRow(
                        feature_id=feature_id,
                        agent_id=agent_id,
                        chat_id=chat_id,
                        role=role,
                        content=content,
                        created_at=utcnow(),
                    )
                )
                session.commit()

    def list_turns(self, feature_id: str, agent_id: str | None = None) -> list[dict[str, Any]]:
        with self._lock:
            with self._session() as session:
                stmt = select(SessionTurnRow).where(SessionTurnRow.feature_id == feature_id)
                if agent_id:
                    stmt = stmt.where(SessionTurnRow.agent_id == agent_id)
                rows = session.scalars(stmt.order_by(SessionTurnRow.id)).all()
                return [
                    {
                        "id": row.id,
                        "feature_id": row.feature_id,
                        "agent_id": row.agent_id,
                        "chat_id": row.chat_id,
                        "role": row.role,
                        "content": row.content,
                        "created_at": _iso(row.created_at),
                    }
                    for row in rows
                ]

    # ----- skills -----

    def upsert_skill_state(self, skill_id: str, *, enabled: bool | None = None, overrides: dict | None = None) -> dict[str, Any]:
        with self._lock:
            with self._session() as session:
                row = session.get(SkillStateRow, skill_id)
                now = utcnow()
                if row is None:
                    row = SkillStateRow(
                        skill_id=skill_id,
                        enabled=1 if enabled is None else int(enabled),
                        overrides_json=json.dumps(overrides or {}),
                        updated_at=now,
                    )
                    session.add(row)
                else:
                    if enabled is not None:
                        row.enabled = int(enabled)
                    if overrides is not None:
                        row.overrides_json = json.dumps(overrides)
                    row.updated_at = now
                session.commit()
                session.refresh(row)
                return self._skill_state_dict(row)

    def get_skill_state(self, skill_id: str) -> dict[str, Any]:
        with self._lock:
            with self._session() as session:
                row = session.get(SkillStateRow, skill_id)
                if row is None:
                    return {"skill_id": skill_id, "enabled": True, "overrides": {}}
                return self._skill_state_dict(row)

    def list_skill_states(self) -> dict[str, dict[str, Any]]:
        with self._lock:
            with self._session() as session:
                rows = session.scalars(select(SkillStateRow)).all()
                return {row.skill_id: self._skill_state_dict(row) for row in rows}

    def _skill_state_dict(self, row: SkillStateRow) -> dict[str, Any]:
        return {
            "skill_id": row.skill_id,
            "enabled": bool(row.enabled),
            "overrides": json.loads(row.overrides_json or "{}"),
            "updated_at": _iso(row.updated_at),
        }

    # ----- artifacts & audit -----

    def save_artifact(self, feature_id: str, name: str, content: str) -> None:
        with self._lock:
            with self._session() as session:
                row = session.scalar(
                    select(ArtifactRow).where(ArtifactRow.feature_id == feature_id, ArtifactRow.name == name)
                )
                now = utcnow()
                if row is None:
                    session.add(
                        ArtifactRow(
                            feature_id=feature_id,
                            name=name,
                            content=content,
                            updated_at=now,
                        )
                    )
                else:
                    row.content = content
                    row.updated_at = now
                session.commit()

    def list_artifacts(self, feature_id: str) -> list[dict[str, Any]]:
        with self._lock:
            with self._session() as session:
                rows = session.scalars(
                    select(ArtifactRow).where(ArtifactRow.feature_id == feature_id).order_by(ArtifactRow.name)
                ).all()
                return [
                    {
                        "name": row.name,
                        "content": row.content,
                        "updated_at": _iso(row.updated_at),
                    }
                    for row in rows
                ]

    def add_audit(
        self,
        feature_id: str,
        event_type: str,
        payload: dict[str, Any],
        *,
        node_id: str = "",
        level: str = "info",
    ) -> dict[str, Any]:
        raw = json.dumps(payload, default=str)
        if len(raw) > 100_000:
            raw = raw[:100_000] + "…"
        now = utcnow()
        with self._lock:
            with self._session() as session:
                row = AuditLogRow(
                    feature_id=feature_id,
                    node_id=node_id,
                    level=level,
                    event_type=event_type,
                    payload_json=raw,
                    created_at=now,
                )
                session.add(row)
                session.commit()
                session.refresh(row)
                return self._audit_dict(row)

    def list_audit(self, feature_id: str, limit: int = 500) -> list[dict[str, Any]]:
        with self._lock:
            with self._session() as session:
                rows = session.scalars(
                    select(AuditLogRow)
                    .where(AuditLogRow.feature_id == feature_id)
                    .order_by(AuditLogRow.id.desc())
                    .limit(limit)
                ).all()
                return [self._audit_dict(row) for row in reversed(rows)]

    def project_chat(self, workspace: str, thread_id: str | None = None) -> dict[str, Any]:
        with self._lock:
            with self._session() as session:
                if thread_id:
                    chosen = session.get(ProjectThreadRow, thread_id)
                    if chosen is None or chosen.workspace != workspace:
                        return {}
                    self._activate_thread(session, workspace, chosen)
                thread = self._active_thread(session, workspace, create=True)
                session.commit()
                return self._project_chat_view(session, workspace, thread)

    def start_project_thread(self, workspace: str) -> dict[str, Any]:
        """Open a blank thread. The previous thread stays in history with its Cursor session."""
        with self._lock:
            with self._session() as session:
                active = self._active_thread(session, workspace, create=True)
                count = session.scalar(
                    select(func.count()).select_from(ProjectMessageRow).where(ProjectMessageRow.thread_id == active.id)
                )
                if not count:
                    session.commit()
                    return self._project_chat_view(session, workspace, active)
                active.active = 0
                fresh = ProjectThreadRow(
                    id=str(uuid.uuid4()),
                    workspace=workspace,
                    chat_id="",
                    title="",
                    active=1,
                    created_at=utcnow(),
                    updated_at=utcnow(),
                )
                session.add(fresh)
                session.commit()
                return self._project_chat_view(session, workspace, fresh)

    def open_project_thread(self, workspace: str, thread_id: str) -> dict[str, Any] | None:
        with self._lock:
            with self._session() as session:
                chosen = session.get(ProjectThreadRow, thread_id)
                if chosen is None or chosen.workspace != workspace:
                    return None
                self._activate_thread(session, workspace, chosen)
                session.commit()
                return self._project_chat_view(session, workspace, chosen)

    def set_project_chat_id(self, workspace: str, chat_id: str, thread_id: str = "") -> None:
        with self._lock:
            with self._session() as session:
                row = session.get(ProjectThreadRow, thread_id) if thread_id else None
                if row is None or row.workspace != workspace:
                    row = self._active_thread(session, workspace, create=True)
                row.chat_id = chat_id
                row.updated_at = utcnow()
                session.commit()

    def append_project_message(
        self,
        workspace: str,
        role: str,
        content: str,
        mode: str,
        thread_id: str = "",
        files: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            with self._session() as session:
                thread = session.get(ProjectThreadRow, thread_id) if thread_id else None
                if thread is None or thread.workspace != workspace:
                    thread = self._active_thread(session, workspace, create=True)
                now = utcnow()
                row = ProjectMessageRow(
                    workspace=workspace,
                    thread_id=thread.id,
                    role=role,
                    content=content,
                    mode=mode,
                    files_json=json.dumps(files or []),
                    created_at=now,
                )
                session.add(row)
                if role == "user" and not (thread.title or "").strip():
                    thread.title = " ".join(content.split())[:80]
                thread.updated_at = now
                session.commit()
                session.refresh(row)
                return self._project_message_dict(row)

    def reset_project_chat(self, workspace: str) -> None:
        with self._lock:
            with self._session() as session:
                thread = self._active_thread(session, workspace, create=False)
                if thread is None:
                    session.commit()
                    return
                rows = session.scalars(select(ProjectMessageRow).where(ProjectMessageRow.thread_id == thread.id)).all()
                for row in rows:
                    session.delete(row)
                session.delete(thread)
                session.commit()

    def _active_thread(self, session: Session, workspace: str, *, create: bool) -> ProjectThreadRow | None:
        row = session.scalar(
            select(ProjectThreadRow)
            .where(ProjectThreadRow.workspace == workspace, ProjectThreadRow.active == 1)
            .order_by(ProjectThreadRow.updated_at.desc())
        )
        if row is not None:
            return row
        row = session.scalar(
            select(ProjectThreadRow).where(ProjectThreadRow.workspace == workspace).order_by(ProjectThreadRow.updated_at.desc())
        )
        if row is not None:
            row.active = 1
            return row
        if not create:
            return None
        row = ProjectThreadRow(
            id=str(uuid.uuid4()),
            workspace=workspace,
            chat_id="",
            title="",
            active=1,
            created_at=utcnow(),
            updated_at=utcnow(),
        )
        session.add(row)
        session.flush()
        return row

    def _activate_thread(self, session: Session, workspace: str, chosen: ProjectThreadRow) -> None:
        session.execute(update(ProjectThreadRow).where(ProjectThreadRow.workspace == workspace).values(active=0))
        chosen.active = 1
        chosen.updated_at = utcnow()

    def _project_chat_view(self, session: Session, workspace: str, thread: ProjectThreadRow) -> dict[str, Any]:
        rows = session.scalars(
            select(ProjectMessageRow).where(ProjectMessageRow.thread_id == thread.id).order_by(ProjectMessageRow.id)
        ).all()
        threads = session.scalars(
            select(ProjectThreadRow).where(ProjectThreadRow.workspace == workspace).order_by(ProjectThreadRow.updated_at.desc())
        ).all()
        visible = []
        dropped = False
        for row in rows:
            if "This reply is simulated because Jedoc is not calling the provider." in (row.content or ""):
                session.delete(row)
                dropped = True
                continue
            visible.append(self._project_message_dict(row))
        if dropped:
            session.commit()
        return {
            "workspace": workspace,
            "thread_id": thread.id,
            "chat_id": thread.chat_id,
            "title": thread.title,
            "messages": visible,
            "threads": [self._project_thread_dict(item) for item in threads],
        }

    def _project_thread_dict(self, row: ProjectThreadRow) -> dict[str, Any]:
        return {
            "id": row.id,
            "title": row.title or "New chat",
            "chat_id": row.chat_id,
            "active": bool(row.active),
            "updated_at": _iso(row.updated_at),
        }

    def _project_message_dict(self, row: ProjectMessageRow) -> dict[str, Any]:
        try:
            files = json.loads(row.files_json or "[]")
        except json.JSONDecodeError:
            files = []
        return {
            "id": row.id,
            "role": row.role,
            "content": row.content,
            "mode": row.mode,
            "files": files if isinstance(files, list) else [],
            "created_at": _iso(row.created_at),
        }

    def _audit_dict(self, row: AuditLogRow) -> dict[str, Any]:
        try:
            payload = json.loads(row.payload_json or "{}")
        except json.JSONDecodeError:
            payload = {"raw": row.payload_json}
        return {
            "id": row.id,
            "feature_id": row.feature_id,
            "node_id": row.node_id,
            "level": row.level,
            "event_type": row.event_type,
            "payload": payload,
            "created_at": _iso(row.created_at),
        }
