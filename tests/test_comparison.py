"""Control-group snapshot tests with mocked availability, never LTX inference."""
import json
from pathlib import Path

from fastapi.testclient import TestClient

from restorer.api import create_app
from test_workflow import post, setup_shot


def test_controlled_pair_frozen_except_reference_conditioning(settings, movie, monkeypatch):
    settings.comfy_workflow = Path(__file__).resolve().parents[1] / "workflows/ltx25-restore.json"
    client = TestClient(create_app(settings))
    service = client.app.state.service
    project, source, shot = setup_shot(client, movie)
    actor = post(client, f"/api/projects/{project['id']}/actors", {"name": "Fixture"})
    ref = post(client, f"/api/actors/{actor['id']}/references", {"source_id": source["id"], "timestamp": 0, "crop": [40, 10, 25, 30], "approval_status": "approved"})
    setup = {"actor_id": actor["id"], "reference_ids": [ref["id"]], "keyframes": [{"frame": 0, "x": 40, "y": 10, "width": 25, "height": 30}], "interpolation": "linear", "view": "front"}
    service.update_shot(shot["id"], {"setup": setup})
    # Availability is mocked only so snapshot construction can be tested without a server.
    monkeypatch.setattr(service, "backends", lambda: [{"id": backend, "label": backend, "available": True, "supports_references": backend != "baseline"} for backend in ("baseline", "comfy_restore", "comfy_refine", "mlx")])
    result = post(client, f"/api/shots/{shot['id']}/comparison", {"backend": "comfy_restore", "seed": 998, "cfg": 1, "steps": 8})
    a, b, c = result["jobs"]
    assert a["backend"] == "baseline"
    assert a["state"] == b["state"] == c["state"] == "queued"
    assert b["group_id"] == c["group_id"] == a["group_id"]
    assert not b["settings"]["use_references"] and c["settings"]["use_references"]
    left, right = b["provenance"], c["provenance"]
    left["settings"].pop("use_references")
    right["settings"].pop("use_references")
    assert left == right
    assert left["workflow_sha256"] and left["source"]["sha256"]
    # Retry still uses that submitted setup after the project is edited.
    post(client, f"/api/jobs/{c['id']}/cancel")
    service.update_shot(shot["id"], {"name": "Changed", "setup": {"actor_id": None, "reference_ids": [], "keyframes": [], "interpolation": "hold", "view": "profile"}})
    retried = post(client, f"/api/jobs/{c['id']}/retry")
    assert retried["provenance"]["shot"]["name"] == "Performance"
    assert retried["provenance"]["shot"]["setup"]["reference_ids"] == [ref["id"]]


def test_model_constraints_before_submission_and_typed_guides(settings, movie, monkeypatch):
    client = TestClient(create_app(settings))
    service = client.app.state.service
    _, source, shot = setup_shot(client, movie)
    monkeypatch.setattr(service, "backends", lambda: [{"id": backend, "label": backend, "available": True, "supports_references": True} for backend in ("baseline", "comfy_restore", "comfy_refine", "mlx")])
    for body in ({"backend": "comfy_restore", "steps": 20}, {"backend": "comfy_restore", "use_references": True}):
        assert client.post(f"/api/shots/{shot['id']}/jobs", json=body).status_code == 422
    service.store.update("source", source["id"], {"is_vfr": True})
    response = client.post(f"/api/shots/{shot['id']}/jobs", json={"backend": "comfy_restore"})
    assert response.status_code == 422 and "CFR" in response.json()["detail"]
    for body in ({"backend": 1}, {"scale": 2.5}, {"scale": 0}, {"unsupported_slider": 0.5}):
        assert client.post(f"/api/shots/{shot['id']}/guide", json=body).status_code == 422
    assert service.store.list("job") == []


def test_presets_populate_real_controls_without_queueing(settings):
    client = TestClient(create_app(settings))
    presets = client.get("/api/presets").json()
    assert any(p["settings"]["backend"] == "baseline" and p["settings"]["scale"] == 2 for p in presets)
    assert all(p["settings"]["steps"] == 8 for p in presets)
    assert client.app.state.service.store.list("job") == []
