"""Run a reproducible, isolated public-film workflow with the real application worker.

This does not download media or judge restoration quality. The deliberately narrow
report can be shared; the application database and raw worker provenance contain
local import paths and should remain local.
"""
from __future__ import annotations

import json
import math
import re
import uuid
from dataclasses import replace
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from . import __version__
from .config import Settings
from .media import sha256
from .schemas import JobInput, Placement, ReferenceInput, Setup, ShotInput
from .service import Service
from .store import now
from .worker import Worker


_HASH = re.compile(r"[a-fA-F0-9]{64}\Z")
_ID = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,99}\Z")
_REVIEW_NOTE = (
    "AUTOMATED FIXTURE PERSISTENCE TEST ONLY. This record tests durable review "
    "storage; no human identity, expression, performance or historical-fidelity "
    "approval has been performed. Human comparison remains required."
)


def _public_url(value: str) -> str:
    """Keep public attribution links without credentials or incidental query data."""
    parsed = urlsplit(value)
    if parsed.scheme not in ("https", "http") or not parsed.hostname:
        raise ValueError("Fixture attribution URLs must use http or https")
    host = parsed.hostname
    query = ""
    if host in ("youtube.com", "www.youtube.com", "m.youtube.com"):
        query = urlencode([(key, val) for key, val in parse_qsl(parsed.query) if key == "v"])
    return urlunsplit((parsed.scheme, host, parsed.path, query, ""))


def _fixture_path(root: Path, value: str) -> Path:
    path = (root / value).resolve(strict=True)
    if not path.is_relative_to(root) or not path.is_file():
        raise ValueError("Fixture media must be regular files inside the manifest directory")
    return path


def _load_manifest(path: Path) -> tuple[Path, list[dict]]:
    path = Path(path).expanduser().resolve(strict=True)
    root = path.parent
    manifest = json.loads(path.read_text())
    if manifest.get("schema_version") != 1 or not isinstance(manifest.get("fixtures"), list) or not manifest["fixtures"]:
        raise ValueError("A schema_version 1 manifest with nonempty fixtures is required")
    fixtures, identifiers = [], set()
    for item in manifest["fixtures"]:
        fixture = dict(item)
        identity = fixture.get("id", "")
        if not isinstance(identity, str) or not _ID.fullmatch(identity) or identity in identifiers:
            raise ValueError("Fixture IDs must be unique simple names")
        identifiers.add(identity)
        if not isinstance(fixture.get("title"), str) or not 1 <= len(fixture["title"]) <= 200:
            raise ValueError("Each fixture needs a title of 1..200 characters")
        for key in ("source_url", "rights_url"):
            fixture[key] = _public_url(fixture[key])
        for kind in ("clip", "reference"):
            expected = fixture.get(kind + "_sha256", "")
            if not isinstance(expected, str) or not _HASH.fullmatch(expected):
                raise ValueError("Every prepared clip and reference requires its SHA-256")
            fixture[kind + "_path"] = _fixture_path(root, fixture[kind + "_path"])
            if sha256(fixture[kind + "_path"]) != expected.lower():
                raise ValueError("Fixture hash verification failed for " + identity + " " + kind)
            fixture[kind + "_sha256"] = expected.lower()
        if fixture.get("source_sha256") and not _HASH.fullmatch(fixture["source_sha256"]):
            raise ValueError("Upstream source SHA-256 must be a 64-character digest")
        fixture["placement"] = Placement(frame=0, **fixture["placement"]).model_dump()
        fixtures.append(fixture)
    return root, fixtures


def _empty(service: Service) -> bool:
    with service.store.connect() as db:
        return db.execute("SELECT COUNT(*) FROM records").fetchone()[0] == 0


def _reference_provenance(fixture: dict) -> dict:
    """Translate a held-out original-film frame into numeric reference metadata.

    The imported PNG is already cropped, so these coordinates describe its
    original film frame and must never be applied to its pixels a second time.
    """
    preparation = fixture.get("preparation")
    if preparation is None:
        return {}
    timestamp = preparation["reference_timestamp"]
    frame = preparation["reference_frame"]
    crop = preparation["reference_crop"]
    if (isinstance(timestamp, bool) or not isinstance(timestamp, (int, float))
            or not math.isfinite(timestamp) or timestamp < 0
            or isinstance(frame, bool) or not isinstance(frame, int) or frame < 0
            or not isinstance(crop, list) or len(crop) != 4
            or any(isinstance(n, bool) or not isinstance(n, (int, float)) or not math.isfinite(n) for n in crop)
            or min(crop[:2]) < 0 or min(crop[2:]) <= 0):
        raise ValueError("Prepared reference metadata must contain a valid timestamp, frame and original-pixel crop")
    source_hash = fixture.get("source_sha256")
    if not source_hash or preparation.get("source_sha256", source_hash) != source_hash:
        raise ValueError("Prepared reference metadata must match the recorded original film hash")
    return {"source_file": fixture["source_url"], "source_hash": source_hash,
            "timestamp": timestamp, "source_frame": frame, "crop": crop}


def _render_report(service: Service, job: dict, variant: str) -> dict:
    """Allowlist output facts; never export raw jobs, logs or provenance."""
    provenance = job["provenance"]
    checks = provenance.get("technical_checks", {})
    metadata = provenance.get("output_metadata", {})
    return {
        "variant": variant, "job_id": job["id"], "version": job["version"],
        "backend": job["backend"], "state": job["state"],
        "settings": {key: job["settings"][key] for key in (
            "backend", "scale", "seed", "steps", "cfg", "use_references", "prompt",
        )},
        "output_url": service.url(job.get("output_path")),
        "source_preview_url": service.url(job.get("source_preview_path")),
        "output_sha256": provenance.get("output_sha256"),
        "conditioning_consumed": provenance.get("conditioning_consumed", False),
        "technical_checks": {key: checks[key] for key in (
            "expected_frames", "actual_frames", "max_timestamp_delta", "duration_delta",
            "audio_expected", "audio_present", "timing_passed", "aspect_ratio_delta", "aspect_passed",
        ) if key in checks},
        "output_metadata": {key: metadata[key] for key in (
            "width", "height", "sar", "duration", "fps", "frame_count", "has_audio",
        ) if key in metadata},
        "runtime_seconds": provenance.get("memory_statistics", {}).get("runtime_seconds"),
        "workflow_sha256": provenance.get("workflow_sha256"),
        "review_state": job["review_state"],
        "human_fidelity_review": "not_performed",
    }


def _fixture_workflow(service: Service, worker: Worker, fixture: dict, backend: str, scale: int, capability: dict) -> dict:
    result = {
        "id": fixture["id"], "title": fixture["title"], "source_url": fixture["source_url"],
        "rights_url": fixture["rights_url"], "source_sha256": fixture.get("source_sha256"),
        "clip_sha256": fixture["clip_sha256"], "reference_sha256": fixture["reference_sha256"],
        "renders": [], "checks": {}, "status": "failed", "human_fidelity_review": "not_performed",
    }
    stage = "import_source"
    try:
        project = service.store.create("project", {"name": "Public film test: " + fixture["title"][:180]})
        result["project_id"] = project["id"]
        source = service.import_source(project["id"], str(fixture["clip_path"]))
        result["source_url_local"] = source["media_url"]
        result["checks"]["source_import_hash_matches"] = source["sha256"] == fixture["clip_sha256"]
        stage = "create_shot"
        timing = fixture.get("shot", {})
        payload = ShotInput(source_id=source["id"], name=fixture["id"],
                            start_time=timing.get("start_time", 0), end_time=timing.get("end_time", source["duration"]))
        shot = service.create_shot(project["id"], payload.model_dump())
        result.update(shot_id=shot["id"], source_frame_count=shot["frame_count"])
        stage = "reference_and_guide"
        actor = service.store.create("actor", {"name": fixture.get("actor_name", "Public fixture performer")}, project["id"])
        reference_provenance = _reference_provenance(fixture)
        reference_notes = "Public archive film fixture. Reference approval below is automated fixture setup only; no restoration result is approved."
        if reference_provenance:
            reference_notes += f" Held-out original film frame {reference_provenance['source_frame']} from {fixture['source_url']}."
        reference = service.import_reference(actor["id"], ReferenceInput(
            path=str(fixture["reference_path"]), provenance="original_footage", approval_status="pending",
            view=fixture.get("reference_view", "front"),
            expression=fixture.get("reference_expression", fixture.get("expression", "")),
            lighting=fixture.get("reference_lighting", fixture.get("lighting", "")),
            notes=reference_notes,
        ))
        if reference_provenance:
            reference = service.store.update("reference", reference["id"], reference_provenance)
        result["reference_metadata"] = {"view": reference["view"],
                                        "source_timestamp": reference.get("timestamp"),
                                        "source_frame": reference.get("source_frame"),
                                        "crop": reference.get("crop"),
                                        "source_hash": reference.get("source_hash")}
        setup = Setup(actor_id=actor["id"], reference_ids=[reference["id"]], keyframes=[fixture["placement"]], view=reference["view"])
        service.update_shot(shot["id"], {"setup": setup.model_dump()})
        rejected_pending = False
        try:
            service.guide(shot["id"], scale=scale)
        except ValueError as exc:
            rejected_pending = "approved" in str(exc)
        if not rejected_pending:
            raise RuntimeError("Pending reference approval gate did not reject guide creation")
        service.store.update("reference", reference["id"], {"approval_status": "approved"})
        guide = service.guide(shot["id"], scale=scale)
        result.update(guide_url=guide["guide_url"], guide_sha256=guide["sha256"],
                      reference_approval="automated_fixture_setup_only")
        result["checks"]["pending_reference_rejected"] = rejected_pending
        result["checks"]["guide_is_review_aid_for_baseline"] = not guide["conditioning"]
        stage = "queue_render"
        baseline = JobInput(backend="baseline", scale=scale)
        group = uuid.uuid4().hex if backend != "baseline" else None
        jobs = [("A", service.create_job(shot["id"], baseline, group_id=group))]
        if backend != "baseline" and capability.get("available"):
            with_reference = JobInput(backend=backend, scale=scale, use_references=True)
            # Validate before B/C queueing. A remains a real baseline regardless of LTX readiness.
            try:
                service.validate_job(shot["id"], with_reference)
                unconditioned = with_reference.model_copy(update={"use_references": False})
                b = service.create_job(shot["id"], unconditioned, group_id=group)
                c = service.queue_snapshot(b["provenance"], with_reference, group_id=group)
                jobs.extend([("B", b), ("C", c)])
                result["comparison_group_id"] = group
            except (ValueError, OSError, RuntimeError):
                result["ltx_blocker"] = {"code": "fixture_or_workflow_validation_failed",
                                         "reason": "The configured LTX workflow could not validate this fixture. Inspect the local application and doctor output."}
        elif backend != "baseline":
            result["ltx_blocker"] = {"code": "backend_unavailable",
                                     "reason": "The configured ComfyUI backend is unavailable. Run restorer doctor locally for details."}
        stage = "render"
        for variant, queued in jobs:
            processed = worker.run_once()
            if processed is None or processed["id"] != queued["id"]:
                raise RuntimeError("The isolated worker processed an unexpected job")
            result["renders"].append(_render_report(service, processed, variant))
        succeeded = all(row["state"] == "succeeded" for row in result["renders"])
        if not succeeded:
            result["failure"] = {"stage": stage, "type": "RenderFailed",
                                 "reason": "A real render failed. Inspect its local job log; no replacement output was substituted."}
            return result
        stage = "review_and_version_persistence"
        completed = service.store.get("job", jobs[0][1]["id"])
        output = service.asset(completed["output_path"])
        output_hash = sha256(output)
        if output_hash != completed["provenance"]["output_sha256"]:
            raise RuntimeError("Completed output hash no longer matches its render snapshot")
        review = {"state": "needs_revision", "notes": _REVIEW_NOTE,
                  "criteria": {"scope": "automated persistence test", "human_fidelity_review": "not performed"},
                  "at": now(), "output_sha256": output_hash}
        service.store.update("job", completed["id"], {"review_state": "needs_revision", "reviews": [*completed["reviews"], review]})
        note = service.store.create("note", {"text": _REVIEW_NOTE, "shot_id": shot["id"],
                                            "actor_id": actor["id"], "timestamp": 0}, project["id"])
        original_notes = reference["notes"]
        service.store.update("reference", reference["id"], {"notes": "Changed after first version: automated snapshot isolation test only."})
        canceled = service.cancel(service.create_job(shot["id"], baseline)["id"])
        retried = service.cancel(service.retry(canceled["id"])["id"])
        reopened = Service(service.settings)
        frozen = reopened.store.get("job", completed["id"])
        result["checks"].update({
            "reference_approval_persisted": reopened.store.get("reference", reference["id"])["approval_status"] == "approved",
            "review_persisted": frozen["review_state"] == "needs_revision" and frozen["reviews"][-1]["notes"] == _REVIEW_NOTE,
            "note_persisted": reopened.store.get("note", note["id"])["text"] == _REVIEW_NOTE,
            "frozen_reference_snapshot_preserved": frozen["provenance"]["references"][0]["notes"] == original_notes,
            "new_version_canceled": canceled["state"] == "canceled" and canceled["id"] != completed["id"],
            "retry_is_distinct_canceled_version": retried["state"] == "canceled" and retried["id"] != canceled["id"] and retried["parent_job_id"] == canceled["id"],
            "completed_output_unchanged": sha256(output) == output_hash,
            "fixture_bytes_unchanged": sha256(fixture["clip_path"]) == fixture["clip_sha256"] and sha256(fixture["reference_path"]) == fixture["reference_sha256"],
        })
        result["renders"][0] = _render_report(reopened, frozen, "A")
        result["canceled_version_ids"] = [canceled["id"], retried["id"]]
        result["status"] = ("blocked" if "ltx_blocker" in result else "passed") if all(result["checks"].values()) else "failed"
        return result
    except Exception as exc:
        result["failure"] = {"stage": stage, "type": type(exc).__name__,
                             "reason": "The public fixture workflow failed. Inspect the corresponding local project; raw paths and logs are deliberately excluded from this report."}
        return result


def run_public_demo(settings: Settings, manifest_path: Path, *, backend: str = "baseline", scale: int = 2,
                    report_path: Path | None = None) -> dict:
    """Exercise prepared public fixtures in a fresh data directory and write a safe report.

    ComfyUI mode runs actual A/B/C jobs when available. It records a blocker when
    unavailable and still tests the conventional baseline; it never substitutes a
    baseline for an LTX result. No model downloads or subjective approvals occur.
    """
    if backend not in ("baseline", "comfy_restore", "comfy_refine"):
        raise ValueError("Public demo backend must be baseline, comfy_restore or comfy_refine")
    JobInput(backend=backend, scale=scale)
    root, fixtures = _load_manifest(manifest_path)
    # Narrow the import boundary to this explicitly prepared public fixture set.
    settings = replace(settings, import_roots=(root,))
    service = Service(settings)
    if not _empty(service):
        raise ValueError("Public film testing requires a fresh data directory without existing records")
    worker = Worker(settings)
    worker.acquire()
    try:
        if not _empty(service):
            raise ValueError("Public film testing requires a fresh isolated data directory")
        capability = next((row for row in service.backends() if row["id"] == backend), {})
        results = [_fixture_workflow(service, worker, fixture, backend, scale, capability) for fixture in fixtures]
    finally:
        worker.close()
    status = "failed" if any(row["status"] == "failed" for row in results) else "blocked" if any(row["status"] == "blocked" for row in results) else "passed"
    report = {"schema_version": 1, "application_version": __version__, "created_at": now(),
              "status": status, "requested_backend": backend, "scale": scale,
              "human_fidelity_review": "not_performed", "automated_reference_approval": "fixture_setup_only",
              "review_policy": _REVIEW_NOTE,
              "ltx_inference": "not_requested" if backend == "baseline" else "completed" if status == "passed" else "not_completed",
              "fixtures": results}
    target = Path(report_path) if report_path else settings.data_dir / "demo" / "latest-public-demo.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, indent=2) + "\n")
    return report
