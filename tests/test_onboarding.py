"""Onboarding covers real media and worker ownership without model downloads."""
import fcntl
import io
import json
import threading
import time

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from restorer.api import create_app
from restorer import onboarding
from restorer.media import sha256
from restorer.schemas import JobInput
from restorer.worker import Worker


def observation(settings, **comfy):
    return {"checked_at": "2026-10-21T00:00:00Z", "tools": {
        name: {"available": True, "version": f"{name} version 8"} for name in ("ffmpeg", "ffprobe")},
        "disk": {"data_dir": str(settings.data_dir), "free_bytes": 1234, "total_bytes": 5678},
        "backends": {"comfy": {"connected": False, "ready": False, "workflow": {}, **comfy}}}


def test_scoped_browse_filters_and_rejects_symlink_escapes(settings, tmp_path):
    allowed = tmp_path / "allowed"
    outside = tmp_path / "outside"
    allowed.mkdir()
    outside.mkdir()
    settings.import_roots = (allowed,)
    (allowed / "clip.mp4").write_bytes(b"video")
    (allowed / "face.jpg").write_bytes(b"image")
    (allowed / "secret.txt").write_text("private")
    (allowed / "subdir").mkdir()
    (outside / "outside.mp4").write_bytes(b"outside")
    (allowed / "escape.mp4").symlink_to(outside / "outside.mp4")
    (allowed / "escape-directory").symlink_to(outside, target_is_directory=True)
    (allowed / "inside.mp4").symlink_to(allowed / "clip.mp4")
    client = TestClient(create_app(settings))
    roots = client.get("/api/files").json()
    assert roots["current"] is None and roots["roots"][0]["path"] == str(allowed)
    videos = client.get("/api/files", params={"kind": "video", "directory": str(allowed)}).json()
    assert [item["name"] for item in videos["entries"]] == ["subdir", "clip.mp4", "inside.mp4"]
    assert videos["parent"] is None
    images = client.get("/api/files", params={"kind": "image", "directory": str(allowed)}).json()
    assert [item["name"] for item in images["entries"]] == ["subdir", "face.jpg"]
    for path in (outside, allowed / "escape-directory", allowed / ".."):
        assert client.get("/api/files", params={"directory": str(path)}).status_code == 422
    assert client.get("/api/files", params={"kind": "all"}).status_code == 422
    assert client.get("/api/files/image-info", params={"path": str(allowed / "escape.mp4")}).status_code == 422


def test_image_preview_and_info_use_native_oriented_coordinates(settings, tmp_path):
    image = Image.new("RGB", (2400, 1200), "red")
    exif = image.getexif()
    exif[274] = 6
    exif[270] = "PRIVATE METADATA"
    path = tmp_path / "rotated.jpg"
    image.save(path, exif=exif)
    client = TestClient(create_app(settings))
    original_hash = sha256(path)
    info = client.get("/api/files/image-info", params={"path": str(path)})
    assert info.status_code == 200
    assert (info.json()["width"], info.json()["height"]) == (1200, 2400)
    preview = client.get(info.json()["preview_url"])
    assert preview.status_code == 200 and preview.headers["x-image-height"] == "2400"
    with Image.open(io.BytesIO(preview.content)) as decoded:
        assert decoded.size == (800, 1600)
        assert not decoded.getexif()
    assert sha256(path) == original_hash
    path.write_bytes(b"invalid image")
    assert client.get("/api/files/preview", params={"path": str(path)}).status_code == 422


def test_worker_status_uses_lock_and_heartbeat_not_pid(settings):
    client = TestClient(create_app(settings))
    assert onboarding.worker_status(settings)["state"] == "stopped"
    worker = Worker(settings)
    worker.acquire()
    try:
        assert onboarding.worker_status(settings)["state"] == "idle"
        worker._active_job_id = "fake-job"
        worker._heartbeat()
        assert onboarding.worker_status(settings)["active_job_id"] == "fake-job"
        path = settings.data_dir / "worker-status.json"
        heartbeat = json.loads(path.read_text())
        heartbeat["heartbeat"] = time.time() - 20
        path.write_text(json.dumps(heartbeat))
        assert onboarding.worker_status(settings)["state"] == "stale"
        path.unlink()
        assert onboarding.worker_status(settings)["state"] == "unknown"
        worker._heartbeat()
        assert onboarding.worker_status(settings)["state"] == "running"
    finally:
        worker.close()
    # A fresh saved heartbeat and an existing PID are not enough after unlock.
    assert onboarding.worker_status(settings)["state"] == "stopped"
    other = Worker(settings)
    other.acquire()
    other.close()


def test_heartbeat_refreshes_during_blocking_work(settings, movie, monkeypatch):
    client = TestClient(create_app(settings))
    service = client.app.state.service
    project = service.store.create("project", {"name": "Heartbeat fixture"})
    source = service.import_source(project["id"], str(movie))
    shot = service.create_shot(project["id"], {"name": "Fixture", "source_id": source["id"], "start_time": 0, "end_time": 1})
    service.create_job(shot["id"], JobInput())
    blocked = threading.Event()
    finish = threading.Event()
    def long_processing(job):
        blocked.set()
        finish.wait(6)
    worker = Worker(settings)
    monkeypatch.setattr(worker, "process", long_processing)
    worker.acquire()
    thread = threading.Thread(target=worker.run_once)
    try:
        thread.start()
        assert blocked.wait(2)
        path = settings.data_dir / "worker-status.json"
        first = json.loads(path.read_text())["heartbeat"]
        deadline = time.monotonic() + 4
        while time.monotonic() < deadline and json.loads(path.read_text())["heartbeat"] <= first:
            time.sleep(0.05)
        assert json.loads(path.read_text())["heartbeat"] > first
        assert onboarding.worker_status(settings)["state"] == "running"
    finally:
        finish.set()
        thread.join(3)
        worker.close()


def test_setup_and_shareable_diagnostics_strip_personal_configuration(settings, monkeypatch):
    client = TestClient(create_app(settings))
    raw = observation(settings, connected=True, workflow={"configured": True, "available": False,
        "missing_nodes": ["MissingNode"], "selected_models": [{"filename": "/private/name/TOKEN.safetensors", "advertised": False}],
        "blockers": ["secret from http://user:password@host/?token=SECRET"], "path": "/Users/private/workflow.json"},
        error="PRIVATE ERROR", url="http://user:password@host")
    monkeypatch.setattr(onboarding, "doctor_report", lambda _: raw)
    local = client.get("/api/system/status").json()
    assert local["storage"]["data_dir"] == str(settings.data_dir)
    assert local["comfy"]["missing_nodes"] == ["MissingNode"]
    assert local["comfy"]["models"][0]["advertised"] is False
    assert local["comfy"]["blockers"] and not local["comfy"]["ready"]
    result = client.get("/api/system/diagnostics")
    assert result.status_code == 200 and "attachment" in result.headers["content-disposition"]
    exported = result.text
    for private in ("/Users/", "/private/", "TOKEN", "SECRET", "password", "MissingNode", str(settings.data_dir)):
        assert private not in exported
    assert result.json()["comfy"]["missing_node_count"] == 1
    assert result.json()["comfy"]["unadvertised_model_count"] == 1


def test_unreachable_comfy_does_not_claim_models_or_nodes_are_missing(settings, monkeypatch):
    client = TestClient(create_app(settings))
    raw = observation(settings, workflow={"configured": True, "missing_nodes": ["UnavailableInventory"],
        "selected_models": [{"filename": "model.safetensors", "advertised": None}]})
    monkeypatch.setattr(onboarding, "doctor_report", lambda _: raw)
    status = client.get("/api/system/status").json()
    assert status["comfy"]["missing_nodes"] == []
    assert status["comfy"]["models"][0]["advertised"] is None
    assert not status["comfy"]["inference_tested"]
    assert "not reachable" in status["comfy"]["blockers"][0]


def test_demo_queues_for_existing_worker_and_preserves_ordinary_projects(settings, movie):
    client = TestClient(create_app(settings))
    service = client.app.state.service
    existing = service.store.create("project", {"name": "Ordinary project", "user_field": "preserve"})
    original_roots = settings.import_roots
    source = service.import_source(existing["id"], str(movie))
    shot = service.create_shot(existing["id"], {"name": "User shot", "source_id": source["id"], "start_time": 0, "end_time": 1})
    ordinary_job = service.create_job(shot["id"], JobInput())
    before = service.detail(existing["id"])
    original_hash = sha256(movie)
    worker = Worker(settings)
    worker.acquire()
    try:
        response = client.post("/api/demo")
        assert response.status_code == 200, response.text
        created = response.json()
        assert created["state"] == "queued" and created["review_state"] == "unreviewed" and not created["reused"]
        assert settings.import_roots == original_roots
        assert service.detail(existing["id"]) == before
        assert sha256(movie) == original_hash
        again = client.post("/api/demo").json()
        assert again["reused"] and again["project_id"] == created["project_id"]
        assert len(service.store.list("project")) == 2
        assert len(service.store.list("job")) == 2
        # Existing queued work retains priority. HTTP demo setup never renders it.
        assert worker.run_once()["id"] == ordinary_job["id"]
        result = worker.run_once()
        assert result["id"] == created["job_id"] and result["state"] == "succeeded"
        assert result["review_state"] == "unreviewed"
        assert result["provenance"]["conditioning_consumed"] is False
        fixture = service.detail(created["project_id"])
        assert fixture["references"][0]["provenance"] == "generated_reconstruction"
        assert "automatically" in fixture["references"][0]["notes"]
    finally:
        worker.close()
    review = client.post(f"/api/jobs/{created['job_id']}/review", json={"state": "accepted", "notes": "Synthetic test review only"})
    assert review.status_code == 200
    reference = service.store.get("reference", created["reference_id"])
    client.patch(f"/api/references/{reference['id']}", json={"notes": "User notes on completed demo"})
    reopened = TestClient(create_app(settings)).post("/api/demo").json()
    assert reopened["job_id"] == created["job_id"] and reopened["state"] == "succeeded"
    assert reopened["review_state"] == "accepted"
    assert service.store.get("reference", reference["id"])["notes"] == "User notes on completed demo"


def test_demo_busy_and_missing_tools_fail_without_altering_projects(settings, monkeypatch):
    client = TestClient(create_app(settings))
    with (settings.data_dir / "demo-create.lock").open("a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        response = client.post("/api/demo")
        assert response.status_code == 409
        assert client.get("/api/projects").json() == []
    monkeypatch.setattr(onboarding.shutil, "which", lambda _: None)
    assert client.post("/api/demo").status_code == 422
    assert client.get("/api/projects").json() == []


def test_diagnostics_versions_are_parsed_not_copied(settings, monkeypatch):
    client = TestClient(create_app(settings))
    raw = observation(settings)
    raw["tools"]["ffmpeg"]["version"] = "ffmpeg version 8.0.1 custom PRIVATE /Users/secret"
    raw["tools"]["ffprobe"]["version"] = "PRIVATE ffprobe version 8.0"
    monkeypatch.setattr(onboarding, "doctor_report", lambda _: raw)
    monkeypatch.setattr(onboarding.platform, "machine", lambda: "secret-hostname")
    monkeypatch.setattr(onboarding.platform, "system", lambda: "secret-operating-system")
    monkeypatch.setattr(onboarding.platform, "python_version", lambda: "3.13.3 secret")
    result = client.get("/api/system/diagnostics").json()
    assert result["tools"]["ffmpeg"]["version"] == "8.0.1"
    assert result["tools"]["ffprobe"]["version"] is None
    assert result["platform"] == {"os": "other", "architecture": "other", "python": None}
    assert "secret" not in json.dumps(result) and "PRIVATE" not in json.dumps(result)


def test_demo_retry_after_queue_marker_failure_reuses_same_job(settings, monkeypatch):
    client = TestClient(create_app(settings))
    service = client.app.state.service
    original_update = service.store.update
    failed_once = False
    def fail_after_queue(kind, identity, changes):
        nonlocal failed_once
        if kind == "project" and changes.get("demo_initialization") == "ready" and not failed_once:
            failed_once = True
            raise RuntimeError("PRIVATE disk path")
        return original_update(kind, identity, changes)
    monkeypatch.setattr(service.store, "update", fail_after_queue)
    response = client.post("/api/demo")
    assert response.status_code == 422 and "PRIVATE" not in response.text
    assert len(service.store.list("project")) == 1 and len(service.store.list("job")) == 1
    assert service.store.list("project")[0]["demo_initialization"] == "failed"
    queued = service.store.list("job")[0]
    result = client.post("/api/demo").json()
    assert result["job_id"] == queued["id"] and result["reused"]
    assert len(service.store.list("job")) == 1
    source = service.store.get("source", result["source_id"])
    assert source["synthetic"]
    response = client.post(f"/api/actors/{result['actor_id']}/references", json={
        "source_id": source["id"], "timestamp": 0, "provenance": "original_footage"})
    assert response.status_code == 201
    assert response.json()["provenance"] == "generated_reconstruction"


@pytest.mark.parametrize("failure_stage", ["before_import", "after_import", "guide"])
def test_demo_retries_early_stages_in_same_project(settings, monkeypatch, failure_stage):
    from restorer.service import Service
    client = TestClient(create_app(settings))
    service = client.app.state.service
    original_import = Service.import_source
    original_guide = Service.guide
    failed_once = False
    def import_with_failure(self, *args, **kwargs):
        nonlocal failed_once
        if not failed_once and failure_stage == "before_import":
            failed_once = True
            raise RuntimeError("PRIVATE import failure")
        result = original_import(self, *args, **kwargs)
        if not failed_once and failure_stage == "after_import":
            failed_once = True
            raise RuntimeError("PRIVATE post-import failure")
        return result
    def guide_with_failure(self, *args, **kwargs):
        nonlocal failed_once
        if not failed_once and failure_stage == "guide":
            failed_once = True
            raise RuntimeError("PRIVATE guide failure")
        return original_guide(self, *args, **kwargs)
    monkeypatch.setattr(Service, "import_source", import_with_failure)
    monkeypatch.setattr(Service, "guide", guide_with_failure)
    failed = client.post("/api/demo")
    assert failed.status_code == 422 and "PRIVATE" not in failed.text
    projects = service.store.list("project")
    assert len(projects) == 1 and projects[0]["demo_initialization"] == "failed"
    project = projects[0]
    fixture_hash = project["demo_fixture"]["sha256"]
    existing_ids = {kind: [item["id"] for item in service.store.list(kind, project["id"])]
                    for kind in ("source", "actor", "reference", "shot")}
    assert not service.store.list("job")
    retry = client.post("/api/demo")
    assert retry.status_code == 200, retry.text
    result = retry.json()
    assert result["reused"] and result["project_id"] == project["id"]
    assert len(service.store.list("project")) == 1 and len(service.store.list("job")) == 1
    for kind, saved_ids in existing_ids.items():
        records = service.store.list(kind, project["id"])
        assert len(records) == 1
        if saved_ids:
            assert [record["id"] for record in records] == saved_ids
    assert service.store.get("project", project["id"])["demo_fixture"]["sha256"] == fixture_hash
    assert len(list((settings.data_dir / "demo").iterdir())) == 1
    assert client.post("/api/demo").json()["job_id"] == result["job_id"]


@pytest.mark.parametrize("change", ["reference_notes", "source_bytes", "additional_actor"])
def test_incomplete_demo_changes_are_preserved_and_refused(settings, monkeypatch, change):
    from restorer.service import Service
    client = TestClient(create_app(settings))
    service = client.app.state.service
    original_guide = Service.guide
    def fail_guide(*args, **kwargs):
        raise RuntimeError("Injected guide failure")
    monkeypatch.setattr(Service, "guide", fail_guide)
    assert client.post("/api/demo").status_code == 422
    monkeypatch.setattr(Service, "guide", original_guide)
    project = service.store.list("project")[0]
    if change == "reference_notes":
        reference = service.store.list("reference", project["id"])[0]
        response = client.patch(f"/api/references/{reference['id']}", json={"notes": "User edit after incomplete setup"})
        assert response.status_code == 200
    elif change == "source_bytes":
        source = service.store.list("source", project["id"])[0]
        service.asset(source["asset_path"]).write_bytes(b"User replaced these source bytes")
    else:
        assert client.post(f"/api/projects/{project['id']}/actors", json={"name": "User-added actor"}).status_code == 201
    before = service.detail(project["id"])
    result = client.post("/api/demo")
    assert result.status_code == 422
    assert "Open its existing project" in result.text and "No additional demo project" in result.text
    assert len(service.store.list("project")) == 1 and not service.store.list("job")
    assert service.detail(project["id"]) == before
    if change == "source_bytes":
        assert service.asset(source["asset_path"]).read_bytes() == b"User replaced these source bytes"
