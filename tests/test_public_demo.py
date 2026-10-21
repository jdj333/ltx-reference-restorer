"""Public-kit workflow tests use generated fixtures, never private or network media.

The successful baseline test uses the real worker and FFmpeg. Availability stubs
only exercise blocked paths; they are not evidence of LTX model inference.
"""
import json

import pytest
from PIL import Image

from restorer.media import sha256
from restorer.public_demo import run_public_demo
from restorer.service import Service
from restorer.worker import Worker


@pytest.fixture
def public_manifest(tmp_path, movie):
    reference = tmp_path / "reference.png"
    Image.new("RGB", (30, 30), "gray").save(reference)
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"schema_version": 1, "fixtures": [{
        "id": "public-test-fixture", "title": "Generated public-kit test fixture",
        "source_url": "https://www.youtube.com/watch?v=example&tracking=discard#fragment",
        "rights_url": "https://example.org/public-film-rights",
        "source_sha256": "a" * 64,
        "clip_path": movie.name, "clip_sha256": sha256(movie),
        "reference_path": reference.name, "reference_sha256": sha256(reference),
        "shot": {"start_time": 0.25, "end_time": 1.25},
        "placement": {"x": 40, "y": 10, "width": 30, "height": 30},
    }]}))
    return manifest


def test_public_demo_real_baseline_and_safe_report(settings, public_manifest):
    report = run_public_demo(settings, public_manifest)
    assert report["status"] == "passed", report
    assert report["ltx_inference"] == "not_requested"
    assert report["human_fidelity_review"] == "not_performed"
    row = report["fixtures"][0]
    assert row["status"] == "passed" and all(row["checks"].values())
    assert row["source_url"] == "https://www.youtube.com/watch?v=example"
    assert row["reference_approval"] == "automated_fixture_setup_only"
    render = row["renders"][0]
    assert render["state"] == "succeeded" and render["backend"] == "baseline"
    assert render["settings"]["seed"] == 42 and render["settings"]["scale"] == 2
    assert not render["conditioning_consumed"]
    assert render["technical_checks"]["timing_passed"]
    assert render["technical_checks"]["aspect_passed"]
    assert render["technical_checks"]["audio_expected"] and render["technical_checks"]["audio_present"]
    assert render["review_state"] == "needs_revision"
    assert render["output_metadata"]["frame_count"] == 12
    assert render["output_metadata"]["width"] == 320
    assert render["source_preview_url"].startswith("/api/assets/jobs/")
    assert row["source_url_local"].startswith("/api/assets/sources/")
    assert row["guide_url"].startswith("/api/assets/guides/")
    assert json.loads((settings.data_dir / "demo/latest-public-demo.json").read_text()) == report
    encoded = json.dumps(report)
    assert str(public_manifest.parent) not in encoded
    assert "import_roots" not in encoded and "source_file" not in encoded and '"provenance"' not in encoded
    service = Service(settings)
    jobs = service.store.list("job")
    assert [job["state"] for job in jobs] == ["succeeded", "canceled", "canceled"]
    assert jobs[0]["reviews"][0]["notes"].startswith("AUTOMATED FIXTURE PERSISTENCE TEST ONLY")
    assert jobs[0]["provenance"]["references"][0]["provenance"] == "original_footage"


def test_unavailable_ltx_records_blocker_and_real_baseline(settings, public_manifest, monkeypatch):
    baseline = {"id": "baseline", "available": True, "label": "FFmpeg", "supports_references": False}
    unavailable = {"id": "comfy_restore", "available": False,
                   "reason": "private endpoint /Users/private/path https://user:secret@local.invalid/?token=secret"}
    monkeypatch.setattr(Service, "backends", lambda _: [baseline, unavailable])
    report = run_public_demo(settings, public_manifest, backend="comfy_restore")
    assert report["status"] == "blocked" and report["ltx_inference"] == "not_completed"
    fixture = report["fixtures"][0]
    assert fixture["ltx_blocker"]["code"] == "backend_unavailable"
    assert [(render["variant"], render["backend"], render["state"]) for render in fixture["renders"]] == [("A", "baseline", "succeeded")]
    assert all(fixture["checks"].values())
    encoded = json.dumps(report)
    assert "secret" not in encoded and "/Users/" not in encoded and "local.invalid" not in encoded


def test_prepared_reference_source_metadata_persists_without_recropping(settings, public_manifest):
    manifest = json.loads(public_manifest.read_text())
    fixture = manifest["fixtures"][0]
    fixture.update(reference_view="three_quarter", reference_expression="neutral", reference_lighting="frontal")
    fixture["preparation"] = {"reference_timestamp": 20 / 12, "reference_frame": 20,
                              "reference_crop": [40, 10, 30, 30], "source_sha256": fixture["source_sha256"]}
    public_manifest.write_text(json.dumps(manifest))
    report = run_public_demo(settings, public_manifest)
    assert report["status"] == "passed", report
    expected = {"view": "three_quarter", "source_timestamp": 20 / 12, "source_frame": 20,
                "crop": [40, 10, 30, 30], "source_hash": "a" * 64}
    assert report["fixtures"][0]["reference_metadata"] == expected
    reopened = Service(settings)
    reference = reopened.store.list("reference")[0]
    assert reference["source_file"] == "https://www.youtube.com/watch?v=example"
    assert reference["source_hash"] == "a" * 64
    assert reference["timestamp"] == 20 / 12 and reference["source_frame"] == 20
    assert reference["crop"] == [40, 10, 30, 30]
    assert reference["view"] == "three_quarter" and reference["expression"] == "neutral" and reference["lighting"] == "frontal"
    assert (reference["width"], reference["height"]) == (30, 30)
    assert sha256(reopened.asset(reference["asset_path"])) == fixture["reference_sha256"]
    first_job = reopened.store.list("job")[0]
    frozen_reference = first_job["provenance"]["references"][0]
    assert frozen_reference["source_file"] == reference["source_file"]
    assert frozen_reference["source_frame"] == 20 and frozen_reference["crop"] == [40, 10, 30, 30]
    assert str(public_manifest.parent) not in json.dumps(report)


def test_available_backend_without_reference_support_remains_blocked(settings, public_manifest, monkeypatch):
    # Availability is stubbed only to prove preflight cannot claim inference.
    monkeypatch.setattr(Service, "backends", lambda _: [
        {"id": "baseline", "available": True, "label": "FFmpeg"},
        {"id": "comfy_restore", "available": True, "supports_references": False, "label": "LTX"},
    ])
    report = run_public_demo(settings, public_manifest, backend="comfy_restore")
    fixture = report["fixtures"][0]
    assert report["status"] == "blocked" and report["ltx_inference"] == "not_completed"
    assert fixture["ltx_blocker"]["code"] == "fixture_or_workflow_validation_failed"
    assert len(fixture["renders"]) == 1 and fixture["renders"][0]["state"] == "succeeded"


def test_corrupt_fixture_rejected_before_import(settings, public_manifest):
    manifest = json.loads(public_manifest.read_text())
    manifest["fixtures"][0]["clip_sha256"] = "0" * 64
    public_manifest.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="hash verification failed"):
        run_public_demo(settings, public_manifest)
    assert not settings.data_dir.exists()


def test_manifest_path_escape_rejected_even_with_matching_hash(settings, public_manifest, tmp_path):
    nested = tmp_path / "prepared"
    nested.mkdir()
    manifest = json.loads(public_manifest.read_text())
    manifest["fixtures"][0]["clip_path"] = "../input.mp4"
    escaped_manifest = nested / "manifest.json"
    escaped_manifest.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="inside the manifest directory"):
        run_public_demo(settings, escaped_manifest)
    assert not settings.data_dir.exists()


def test_symlink_fixture_escape_rejected(settings, public_manifest, tmp_path):
    nested = tmp_path / "prepared"
    nested.mkdir()
    (nested / "input.mp4").symlink_to(tmp_path / "input.mp4")
    escaped_manifest = nested / "manifest.json"
    escaped_manifest.write_text(public_manifest.read_text())
    with pytest.raises(ValueError, match="inside the manifest directory"):
        run_public_demo(settings, escaped_manifest)


def test_existing_application_records_are_never_modified(settings, public_manifest):
    service = Service(settings)
    original = service.store.create("project", {"name": "Unrelated project"})
    with pytest.raises(ValueError, match="fresh data directory"):
        run_public_demo(settings, public_manifest)
    assert service.store.list("project") == [original]
    assert not service.store.list("job")


def test_existing_worker_lock_prevents_any_public_records(settings, public_manifest):
    worker = Worker(settings)
    worker.acquire()
    try:
        with pytest.raises(RuntimeError, match="Another worker"):
            run_public_demo(settings, public_manifest)
        assert not worker.store.list("project")
    finally:
        worker.close()


def test_worker_failure_is_not_success_or_ltx_evidence(settings, public_manifest, monkeypatch):
    def fail(worker, job):
        worker.store.update("job", job["id"], {"state": "failed", "error": "private /Users/example/path"})
    monkeypatch.setattr(Worker, "process", fail)
    report = run_public_demo(settings, public_manifest)
    assert report["status"] == "failed" and report["ltx_inference"] == "not_requested"
    fixture = report["fixtures"][0]
    assert fixture["failure"]["type"] == "RenderFailed"
    assert fixture["renders"][0]["state"] == "failed"
    assert fixture["renders"][0]["output_url"] is None
    assert "/Users/" not in json.dumps(report)
