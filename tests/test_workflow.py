"""Real FFmpeg baseline processing. LTX inference is explicitly not exercised."""
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image

from restorer.api import create_app
from restorer.media import probe, sha256
from restorer.worker import Worker


def post(client, url, data=None):
    response = client.post(url, json=data or {})
    assert response.status_code < 300, response.text
    return response.json()


def setup_shot(client, movie):
    project = post(client, "/api/projects", {"name": "Restoration test"})
    source = post(client, f"/api/projects/{project['id']}/sources", {"path": str(movie)})
    shot = post(client, f"/api/projects/{project['id']}/shots", {"source_id": source["id"], "name": "Performance", "start_time": 0.25, "end_time": 1.25})
    return project, source, shot


def test_baseline_import_guide_render_compare_approve_reopen(settings, movie):
    original_hash = sha256(movie)
    client = TestClient(create_app(settings))
    project, source, shot = setup_shot(client, movie)
    assert source["frame_count"] == 24 and source["has_audio"]
    assert shot["frame_start"] == 3 and shot["frame_end"] == 15
    actor = post(client, f"/api/projects/{project['id']}/actors", {"name": "Fixture actor"})
    ref = post(client, f"/api/actors/{actor['id']}/references", {"source_id": source["id"], "timestamp": 0.25, "crop": [40, 10, 30, 30], "quality": 4, "provenance": "original_footage", "expression": "fixture", "lighting": "flat"})
    assert ref["approval_status"] == "pending"
    assert ref["source_hash"] == original_hash
    assert client.patch(f"/api/references/{ref['id']}", json={"approval_status": "approved"}).status_code == 200
    setup = {"actor_id": actor["id"], "reference_ids": [ref["id"]], "keyframes": [{"frame": 0, "x": 40, "y": 10, "width": 30, "height": 30}], "interpolation": "linear", "view": "front"}
    assert client.patch(f"/api/shots/{shot['id']}", json={"setup": setup}).status_code == 200
    guide = post(client, f"/api/shots/{shot['id']}/guide")
    assert not guide["conditioning"]
    assert client.get(guide["guide_url"]).status_code == 200
    job = post(client, f"/api/shots/{shot['id']}/jobs", {"backend": "baseline", "scale": 2})
    worker = Worker(settings)
    worker.acquire()
    try:
        result = worker.run_once()
        assert result["state"] == "succeeded", result["error"]
    finally:
        worker.close()
    rendered = client.get(f"/api/jobs/{job['id']}").json()
    assert rendered["review_state"] == "unreviewed"
    assert rendered["provenance"]["technical_checks"]["timing_passed"]
    assert rendered["provenance"]["output_metadata"]["width"] == 320
    assert rendered["provenance"]["source"]["sha256"] == original_hash
    assert rendered["provenance"]["references"][0]["sha256"] == ref["sha256"]
    assert client.get(rendered["source_preview_url"]).status_code == 200
    assert client.get(rendered["output_url"], headers={"Range": "bytes=0-63"}).status_code == 206
    accepted = post(client, f"/api/jobs/{job['id']}/review", {"state": "accepted", "notes": "Test approval only, no historical quality claim", "criteria": {"identity": "test fixture", "mouth": "reviewed"}})
    assert accepted["review_state"] == "accepted"
    post(client, f"/api/projects/{project['id']}/notes", {"shot_id": shot["id"], "actor_id": actor["id"], "timestamp": 0.5, "text": "Check blinking"})
    reopened = TestClient(create_app(settings)).get(f"/api/projects/{project['id']}").json()
    assert reopened["references"][0]["approval_status"] == "approved"
    assert reopened["jobs"][0]["review_state"] == "accepted"
    assert reopened["notes"][0]["timestamp"] == 0.5
    output = settings.data_dir / rendered["output_path"]
    saved_hash = sha256(output)
    # New references/settings produce another output version; acceptance/output bytes remain intact.
    client.patch(f"/api/references/{ref['id']}", json={"notes": "Changed after acceptance"})
    second = post(client, f"/api/shots/{shot['id']}/jobs", {"backend": "baseline", "scale": 1})
    assert second["id"] != job["id"] and second["version"] == 2
    assert sha256(output) == saved_hash and sha256(movie) == original_hash
    frozen = client.get(f"/api/jobs/{job['id']}").json()
    assert frozen["provenance"]["references"][0]["notes"] == ""
    assert frozen["review_state"] == "accepted"


def test_reference_generated_provenance_and_approval_persist(settings, movie, tmp_path):
    client = TestClient(create_app(settings))
    project, _, _ = setup_shot(client, movie)
    actor = post(client, f"/api/projects/{project['id']}/actors", {"name": "Actor"})
    picture = tmp_path / "generated.png"
    Image.new("RGB", (20, 30), "red").save(picture)
    ref = post(client, f"/api/actors/{actor['id']}/references", {"path": str(picture), "provenance": "generated_reconstruction", "view": "profile", "quality": 5})
    assert ref["approval_status"] == "pending"
    assert sha256(settings.data_dir / ref["original_asset_path"]) == sha256(picture)
    rank = client.get(f"/api/actors/{actor['id']}/references?view=profile").json()[0]
    assert rank["provenance"] == "generated_reconstruction"
    assert "pending" in rank["rank_reason"]


def test_scoped_paths_and_browser_origin(settings, movie, tmp_path):
    client = TestClient(create_app(settings))
    project = post(client, "/api/projects", {"name": "Scope"})
    response = client.post(f"/api/projects/{project['id']}/sources", json={"path": "/etc/passwd"})
    assert response.status_code == 422
    assert client.get("/api/assets/../restorer.sqlite3").status_code in (404, 422)
    assert client.get("/api/projects", headers={"Origin": "https://untrusted.example"}).status_code == 403
    assert client.get("/api/projects", headers={"Host": "untrusted.example"}).status_code == 403


def test_unavailable_never_silently_substitutes(settings, movie):
    client = TestClient(create_app(settings))
    _, _, shot = setup_shot(client, movie)
    for backend in ("comfy_restore", "comfy_refine", "mlx"):
        response = client.post(f"/api/shots/{shot['id']}/jobs", json={"backend": backend})
        assert response.status_code == 422 and "unavailable" in response.json()["detail"]
    assert client.post(f"/api/shots/{shot['id']}/jobs", json={"backend": "baseline", "use_references": True}).status_code == 422


def test_frame_previews_reopen_older_source_metadata(settings, movie):
    client = TestClient(create_app(settings))
    _, source, shot = setup_shot(client, movie)
    service = client.app.state.service
    old = service.store.get("source", source["id"])
    old.pop("video_stream_index")
    # Simulate a persisted source imported before the convenience index field was added.
    import json
    with service.store.connect() as db:
        db.execute("UPDATE records SET body=? WHERE id=?", (json.dumps(old), source["id"]))
    assert client.get(f"/api/sources/{source['id']}/frame?timestamp=0.5").status_code == 200
    assert client.get(f"/api/shots/{shot['id']}/frame?frame=2").status_code == 200
