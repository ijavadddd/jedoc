"""In-process fan-out for live pipeline telemetry. Every event is also an audit row."""

from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import Any

from backend.storage.session_store import FeatureSessionStore


class EventBus:
    def __init__(self, store: FeatureSessionStore) -> None:
        self.store = store
        self._subs: dict[str, set[asyncio.Queue]] = defaultdict(set)

    def subscribe(self, feature_id: str) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=2000)
        self._subs[feature_id].add(queue)
        return queue

    def unsubscribe(self, feature_id: str, queue: asyncio.Queue) -> None:
        self._subs.get(feature_id, set()).discard(queue)

    async def publish(self, feature_id: str, event: dict[str, Any]) -> dict[str, Any]:
        payload = dict(event)
        payload.setdefault("feature_id", feature_id)
        saved = self.store.add_audit(
            feature_id,
            str(payload.get("type") or "log"),
            payload,
            node_id=str(payload.get("node_id") or ""),
            level=str(payload.get("level") or "info"),
        )
        payload["id"] = saved["id"]
        payload["created_at"] = saved["created_at"]
        for queue in list(self._subs.get(feature_id, set())):
            self._offer(queue, payload)
        return payload

    def _offer(self, queue: asyncio.Queue, payload: dict[str, Any]) -> None:
        try:
            queue.put_nowait(payload)
        except asyncio.QueueFull:
            try:
                queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
            try:
                queue.put_nowait(payload)
            except asyncio.QueueFull:
                pass
