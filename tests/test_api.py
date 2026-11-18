from pathlib import Path

from fastapi.testclient import TestClient


def test_api_catalog_and_feature(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("JEDOC_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("JEDOC_EXECUTION_MODE", "simulate")
    monkeypatch.setenv("JEDOC_PROJECTS_ROOT", str(tmp_path / "projects"))
    monkeypatch.setenv("JEDOC_QA_DURATION_S", "0")

    import importlib

    import backend.api.server as server

    server = importlib.reload(server)

    with TestClient(server.app) as client:
        health = client.get("/api/health")
        assert health.status_code == 200
        assert health.json()["ok"] is True
        flows = client.get("/api/flows").json()
        assert any(item["id"] == "jedoc-million-user" for item in flows)
        skills = client.get("/api/skills").json()
        assert {item["id"] for item in skills} == {
            "founder-skill",
            "napkin",
            "ponytail",
            "claude-mem-cursor",
            "awesome-design-md",
            "graphify",
            "superpowers",
            "gtk",
        }
        projects = client.get("/api/git/projects").json()
        assert projects["root"].endswith("projects")
        providers = client.get("/api/providers").json()
        assert providers[0]["id"] == "cursor"
        assert "models" in providers[0]
        created = client.post("/api/features", json={"name": "Demo", "prd": "Ship a reservation API.\n"}).json()
        assert created["status"] == "draft"
        assert Path(created["workspace_path"], "PRD.md").is_file()
        toggled = client.patch("/api/skills/ponytail/toggle", json={"enabled": False, "workspace": created["workspace_path"]})
        assert toggled.status_code == 200
        listed = client.get("/api/skills", params={"workspace": created["workspace_path"]}).json()
        ponytail = next(item for item in listed if item["id"] == "ponytail")
        assert ponytail["enabled"] is False
        added = client.post("/api/flows/jedoc-million-user/nodes", json={"display_name": "Temp agent", "role_type": "custom"}).json()
        temp = added["nodes"][-1]
        assert temp["enabled"] is True
        disabled = client.patch(f"/api/flows/jedoc-million-user/nodes/{temp['id']}", json={"enabled": False}).json()
        assert next(item for item in disabled["nodes"] if item["id"] == temp["id"])["enabled"] is False
        removed = client.delete(f"/api/flows/jedoc-million-user/nodes/{temp['id']}")
        assert removed.status_code == 200
        assert all(item["id"] != temp["id"] for item in removed.json()["nodes"])
        folder = tmp_path / "repo"
        folder.mkdir()
        client.put("/api/providers/cursor", json={"enabled": False})
        sent = client.post("/api/project-chat", json={"workspace": str(folder), "message": "What lives in this folder?", "mode": "ask"})
        assert sent.status_code == 200
        assert "event-stream" in sent.headers["content-type"]
        assert "No provider found" in sent.text
        assert "Outside the pipeline" not in sent.text
        history = client.get("/api/project-chat", params={"workspace": str(folder)}).json()
        assert history["messages"] == []
        cleared = client.delete("/api/project-chat", params={"workspace": str(folder)})
        assert cleared.status_code == 200
        assert client.get("/api/project-chat", params={"workspace": str(folder)}).json()["messages"] == []
        store = server.app.state.store
        path = str(folder)
        first = store.start_project_thread(path)
        store.append_project_message(path, "user", "Remember the oak tree", "ask", first["thread_id"])
        store.set_project_chat_id(path, "cursor-session-1", first["thread_id"])
        second = store.start_project_thread(path)
        assert second["messages"] == []
        assert second["thread_id"] != first["thread_id"]
        opened = client.post("/api/project-chat/open", json={"workspace": path, "thread_id": first["thread_id"]}).json()
        assert opened["chat_id"] == "cursor-session-1"
        assert opened["messages"][0]["content"] == "Remember the oak tree"
        listed = client.get("/api/project-chat", params={"workspace": path}).json()
        assert listed["thread_id"] == first["thread_id"]
        assert len(listed["threads"]) == 2
