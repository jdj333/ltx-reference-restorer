"""State machine tests; failure injection is isolated from real FFmpeg baseline test."""
import pytest
from fastapi.testclient import TestClient

from restorer.api import create_app
from restorer.media import Canceled
from restorer.worker import Worker
from test_workflow import post, setup_shot


def test_cancel_retry_failure_restart_and_single_worker(settings, movie, monkeypatch):
    client = TestClient(create_app(settings))
    _, _, shot = setup_shot(client, movie)
    service = client.app.state.service
    job = post(client, f"/api/shots/{shot['id']}/jobs", {"backend": "baseline"})
    assert post(client, f"/api/jobs/{job['id']}/cancel")["state"] == "canceled"
    retry = post(client, f"/api/jobs/{job['id']}/retry")
    assert retry["id"] != job["id"] and retry["parent_job_id"] == job["id"]
    service.update_shot(shot["id"], {"name": "Edited after original submission"})
    assert retry["provenance"]["shot"]["name"] == "Performance"
    worker = Worker(settings)
    worker.acquire()
    try:
        other = Worker(settings)
        with pytest.raises(RuntimeError, match="Another worker"):
            other.acquire()
        def fail(*args, **kwargs):
            raise RuntimeError("Injected processing error")
        monkeypatch.setattr("restorer.worker.render_clip", fail)
        failed = worker.run_once()
        assert failed["state"] == "failed" and "Injected" in failed["error"]
    finally:
        worker.close()
    retry2 = post(client, f"/api/jobs/{retry['id']}/retry")
    service.store.update("job", retry2["id"], {"state": "running"})
    recovered = Worker(settings)
    recovered.acquire()
    try:
        assert service.store.get("job", retry2["id"])["state"] == "interrupted"
        assert service.store.get("job", job["id"])["state"] == "canceled"
    finally:
        recovered.close()


def test_running_cancel_and_review_refused(settings, movie, monkeypatch):
    client = TestClient(create_app(settings))
    _, _, shot = setup_shot(client, movie)
    job = post(client, f"/api/shots/{shot['id']}/jobs", {})
    assert client.post(f"/api/jobs/{job['id']}/review", json={"state": "accepted"}).status_code == 422
    def cancel_during_processing(*args, **kwargs):
        response = post(client, f"/api/jobs/{job['id']}/cancel")
        assert response["state"] == "running" and response["cancel_requested"]
        assert kwargs["canceled"]()
        raise Canceled("Injected cancellation boundary")
    monkeypatch.setattr("restorer.worker.render_clip", cancel_during_processing)
    worker = Worker(settings)
    worker.acquire()
    try:
        result = worker.run_once()
        assert result["state"] == "canceled" and result["output_path"] is None
    finally:
        worker.close()


def test_hash_changes_fail_instead_of_render(settings, movie):
    client = TestClient(create_app(settings))
    _, source, shot = setup_shot(client, movie)
    post(client, f"/api/shots/{shot['id']}/jobs", {})
    (settings.data_dir / source["asset_path"]).write_bytes(b"changed")
    worker = Worker(settings)
    worker.acquire()
    try:
        result = worker.run_once()
        assert result["state"] == "failed" and "hash changed" in result["error"]
        assert result["output_path"] is None
    finally:
        worker.close()


def test_placement_without_actor_saves_queues_and_assignment_can_be_cleared(settings, movie):
    client = TestClient(create_app(settings))
    project, _, shot = setup_shot(client, movie)
    placement = {"frame": 0, "x": 20, "y": 10, "width": 30, "height": 40}
    # Users may set a face region before assigning an actor or reference.
    response = client.patch(f"/api/shots/{shot['id']}", json={"setup": {"keyframes": [placement]}})
    assert response.status_code == 200, response.text
    saved = response.json()["setup"]
    assert saved["actor_id"] is None and saved["reference_ids"] == []
    assert saved["keyframes"] == [placement]
    first = post(client, f"/api/shots/{shot['id']}/jobs", {"backend": "baseline"})
    assert first["provenance"]["actor"] is None
    assert first["provenance"]["shot"]["setup"]["actor_id"] is None
    actor = post(client, f"/api/projects/{project['id']}/actors", {"name": "Unassigned fixture actor"})
    saved["actor_id"] = actor["id"]
    assigned = client.patch(f"/api/shots/{shot['id']}", json={"setup": saved})
    assert assigned.status_code == 200 and assigned.json()["setup"]["actor_id"] == actor["id"]
    saved["actor_id"] = None
    cleared = client.patch(f"/api/shots/{shot['id']}", json={"setup": saved, "name": None})
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["setup"]["actor_id"] is None
    assert cleared.json()["name"] == shot["name"]
    second = post(client, f"/api/shots/{shot['id']}/jobs", {"backend": "baseline"})
    assert second["provenance"]["actor"] is None and second["version"] == 2
    # Non-HTTP callers receive the same normalized setup contract.
    direct = client.app.state.service.update_shot(shot["id"], {"setup": {"keyframes": [placement]}})
    assert direct["setup"]["actor_id"] is None and direct["setup"]["view"] == "front"
