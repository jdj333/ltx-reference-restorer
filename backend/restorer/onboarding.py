"""Local onboarding, scoped media browsing and deliberately small diagnostics.

The diagnostics export is an allowlist, not a redaction of arbitrary logs or
configuration. The local setup response may show the user's own storage path.
"""
from __future__ import annotations

import fcntl
import hashlib
import io
import json
import math
import os
import platform
import re
import shutil
import time
import uuid
from dataclasses import replace
from pathlib import Path
from typing import Literal
from urllib.parse import urlencode

from PIL import Image, ImageDraw, ImageOps, UnidentifiedImageError

from . import __version__
from .config import Settings
from .doctor import report as doctor_report
from .media import run, sha256
from .schemas import JobInput, ReferenceInput, Setup
from .service import Service

VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v", ".mpg", ".mpeg"}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff", ".bmp"}
DEMO_KIND = "synthetic-onboarding-v1"
HEARTBEAT_MAX_AGE = 10


class DemoBusy(ValueError):
    pass


class DemoChanged(ValueError):
    pass


DEMO_NAME = "Synthetic demo — blink and expression"
DEMO_DESCRIPTION = "Procedurally drawn fixture and synthesized tone. No real performer, historical footage or LTX inference. Human review remains required."
DEMO_REFERENCE_NOTES = "Entirely procedural drawing. Approved automatically for synthetic fixture setup only; not an identity or historical-fidelity approval."


def _demo_changed():
    raise DemoChanged("The incomplete synthetic demo contains changed, missing or unexpected data. Open its existing project to inspect or continue manually, or use a fresh isolated demo data directory. No additional demo project was created.")


def worker_status(settings: Settings) -> dict:
    """Combine OS ownership and heartbeat age; never trust a saved PID alone."""
    locked = False
    lock_pid = None
    try:
        with (settings.data_dir / "worker.lock").open("r") as handle:
            try:
                lock_pid = int(handle.read(32).strip())
            except ValueError:
                pass
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                fcntl.flock(handle, fcntl.LOCK_UN)
            except BlockingIOError:
                locked = True
    except FileNotFoundError:
        pass
    except OSError:
        return {"state": "unknown", "active_job_id": None, "heartbeat_age_seconds": None,
                "message": "Worker ownership could not be inspected. Check data-directory permissions."}
    telemetry = {}
    try:
        candidate = json.loads((settings.data_dir / "worker-status.json").read_text())
        if isinstance(candidate, dict):
            telemetry = candidate
    except (OSError, ValueError):
        pass
    heartbeat = telemetry.get("heartbeat")
    age = None
    try:
        if isinstance(heartbeat, (int, float)) and math.isfinite(heartbeat):
            age = time.time() - heartbeat
    except OverflowError:
        pass
    valid = (age is not None and 0 <= age <= HEARTBEAT_MAX_AGE
             and telemetry.get("pid") == lock_pid and telemetry.get("state") in ("idle", "running"))
    if not locked:
        state, message = "stopped", "No render worker owns this data directory. Start the application with restorer start, or start restorer worker for the same data directory."
    elif not telemetry:
        state, message = "unknown", "A worker owns the directory but has no heartbeat. It may be an older worker; finish active work before restarting it."
    elif not valid:
        state, message = "stale", "A worker owns the directory but its heartbeat is stale or does not match. Inspect the existing worker; do not start a second one."
    else:
        state = telemetry["state"]
        message = "Worker is processing a queued render." if state == "running" else "Worker is live and waiting for queued renders."
    job_id = telemetry.get("active_job_id")
    return {"state": state, "active_job_id": job_id if valid and locked and isinstance(job_id, str) else None,
            "heartbeat_age_seconds": round(max(0, age), 2) if age is not None else None, "message": message}


def _demo_project(service: Service) -> dict | None:
    for project in service.store.list("project"):
        if (project.get("demo_kind") == DEMO_KIND and project.get("demo_initialization") == "ready"
                and project.get("demo_ids", {}).get("job_id")):
            return project
    return None


def setup_status(service: Service) -> dict:
    observation = doctor_report(service.settings)
    raw_comfy = observation["backends"]["comfy"]
    workflow = raw_comfy.get("workflow", {})
    connected = bool(raw_comfy.get("connected"))
    configured = bool(workflow.get("configured"))
    blockers = []
    instructions = []
    if not connected:
        blockers.append("ComfyUI is not reachable at the configured address.")
        instructions.append("Start your configured ComfyUI service and refresh setup status.")
    if not configured:
        blockers.append("No API workflow is configured.")
        instructions.append("Set comfy_workflow in your local configuration or RESTORER_COMFY_WORKFLOW to the matching workflows/ltx25-restore.json recipe.")
    elif workflow.get("error"):
        blockers.append("The configured workflow could not be read or validated.")
        instructions.append("Check the workflow file and use the bundled API recipe with matching ComfyUI-LTXVideo nodes.")
    missing_nodes = workflow.get("missing_nodes", []) if connected else []
    models = workflow.get("selected_models", [])
    if missing_nodes:
        blockers.append("Required workflow nodes are missing from ComfyUI.")
        instructions.append("Install the workflow's matching ComfyUI-LTXVideo custom nodes, then restart ComfyUI.")
    if any(model.get("advertised") is False for model in models):
        blockers.append("Required model filenames are not advertised by the configured nodes.")
        instructions.append("Place the compatible model files in the ComfyUI directories specified by the workflow, then refresh ComfyUI's model inventory.")
    if connected and configured and workflow.get("blockers") and not missing_nodes:
        blockers.append("The workflow has unsupported or incompatible node bindings.")
        instructions.append("Run restorer doctor locally and compare your installed nodes with docs/integration-notes.md.")
    demo = _demo_project(service)
    tools = {name: {"available": bool(value.get("available")), "version": value.get("version"),
                    "instructions": "Ready." if value.get("available") else f"Install {name} and ensure it is on PATH, or configure its executable path."}
             for name, value in observation["tools"].items()}
    return {"checked_at": observation["checked_at"], "tools": tools,
            "platform": {"os": platform.system(), "architecture": platform.machine(), "python": platform.python_version()},
            "worker": worker_status(service.settings),
            "storage": {key: observation["disk"].get(key) for key in ("data_dir", "free_bytes", "total_bytes")},
            "comfy": {"connected": connected, "ready": bool(raw_comfy.get("ready")),
                      "workflow_configured": configured, "missing_nodes": missing_nodes,
                      "models": [{"filename": item["filename"], "advertised": item.get("advertised")} for item in models],
                      "blockers": blockers, "instructions": instructions,
                      "inference_tested": False},
            "baseline_ready": all(tool["available"] for tool in tools.values()),
            "demo": {"available": all(tool["available"] for tool in tools.values()), "project_id": demo["id"] if demo else None},
            "notes": ["Setup checks connectivity and advertised inputs; it does not verify LTX inference or historical fidelity.",
                      "Synthetic demo creation queues a conventional baseline and does not download models.",
                      "The source supplies the performance. Approved references guide appearance and detail."]}


def shareable_diagnostics(status: dict) -> dict:
    """No configuration values, arbitrary errors, filenames, paths or logs."""
    def tool_version(name):
        match = re.match(rf"^{name} version n?([0-9]+(?:\.[0-9]+){{0,3}})\b", status["tools"][name].get("version") or "")
        return match[1] if match else None
    machine = status["platform"]
    safe_platform = {
        "os": machine["os"] if machine["os"] in {"Darwin", "Linux", "Windows", "FreeBSD"} else "other",
        "architecture": machine["architecture"] if machine["architecture"] in {"arm64", "aarch64", "x86_64", "AMD64", "i386", "i686"} else "other",
        "python": machine["python"] if re.fullmatch(r"[0-9]+(?:\.[0-9]+){1,2}", machine["python"]) else None,
    }
    return {"schema_version": 1, "application_version": __version__, "checked_at": status["checked_at"],
            "platform": safe_platform,
            "tools": {name: {"available": bool(status["tools"][name]["available"]), "version": tool_version(name)} for name in ("ffmpeg", "ffprobe")},
            "worker": {"state": status["worker"]["state"], "heartbeat_age_seconds": status["worker"]["heartbeat_age_seconds"]},
            "storage": {key: status["storage"][key] for key in ("free_bytes", "total_bytes")},
            "comfy": {key: status["comfy"][key] for key in ("connected", "ready", "workflow_configured", "inference_tested")}
                     | {"missing_node_count": len(status["comfy"]["missing_nodes"]),
                        "model_count": len(status["comfy"]["models"]),
                        "unadvertised_model_count": sum(item["advertised"] is False for item in status["comfy"]["models"])},
            "baseline_ready": bool(status["baseline_ready"]),
            "scope": "Local setup observations only. No project content, local paths, logs, endpoint addresses or model filenames included."}


def browse_files(settings: Settings, *, kind: Literal["video", "image"], directory: str | None = None) -> dict:
    roots = [{"path": str(root), "name": root.name or str(root)} for root in settings.import_roots if root.is_dir()]
    if directory is None:
        return {"roots": roots, "current": None, "parent": None, "entries": [], "truncated": False}
    try:
        current = Path(directory).expanduser().resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise ValueError("Choose a readable directory within configured import_roots") from exc
    containing = [root for root in settings.import_roots if current.is_relative_to(root)]
    if not containing or not current.is_dir():
        raise ValueError("Choose a directory within configured import_roots")
    allowed = VIDEO_EXTENSIONS if kind == "video" else IMAGE_EXTENSIONS
    entries = []
    count = 0
    # Bound enumeration as well as the response for very large directories.
    try:
        children = os.scandir(current)
    except OSError as exc:
        raise ValueError("Choose a readable directory within configured import_roots") from exc
    with children:
        for child in children:
            count += 1
            if count > 5000:
                break
            if child.name.startswith("."):
                continue
            try:
                target = Path(child.path).resolve(strict=True)
                if not any(target.is_relative_to(root) for root in settings.import_roots):
                    continue
                is_dir = target.is_dir()
                if not is_dir and (target.suffix.lower() not in allowed or not target.is_file()):
                    continue
                entries.append({"name": child.name, "path": str(target), "is_dir": is_dir,
                                **({} if is_dir else {"size_bytes": target.stat().st_size})})
            except (OSError, RuntimeError):
                continue
    entries.sort(key=lambda entry: (not entry["is_dir"], entry["name"].casefold()))
    parent = current.parent if any(current.parent.is_relative_to(root) for root in settings.import_roots) else None
    return {"roots": roots, "current": str(current), "parent": str(parent) if parent else None,
            "entries": entries[:1000], "truncated": count > 5000 or len(entries) > 1000}


def local_image(settings: Settings, value: str) -> Image.Image:
    try:
        path = settings.import_path(value)
    except (OSError, RuntimeError) as exc:
        raise ValueError("Choose a readable image within configured import_roots") from exc
    if path.suffix.lower() not in IMAGE_EXTENSIONS:
        raise ValueError("Choose a supported reference image")
    try:
        with Image.open(path) as image:
            if image.width * image.height > 50_000_000:
                raise ValueError("Reference preview is limited to 50 million pixels")
            return ImageOps.exif_transpose(image).convert("RGB")
    except (OSError, UnidentifiedImageError, Image.DecompressionBombError) as exc:
        raise ValueError("Image could not be safely decoded") from exc


def image_info(settings: Settings, path: str) -> dict:
    image = local_image(settings, path)
    return {"width": image.width, "height": image.height,
            "preview_url": "/api/files/preview?" + urlencode({"path": path})}


def image_preview(settings: Settings, path: str) -> tuple[bytes, tuple[int, int]]:
    image = local_image(settings, path)
    dimensions = image.size
    image.thumbnail((1600, 1600))
    output = io.BytesIO()
    # A new RGB image strips imported metadata, including EXIF/GPS.
    image.save(output, format="PNG")
    return output.getvalue(), dimensions


def _demo_result(service: Service, project: dict, *, reused: bool) -> dict:
    ids = project["demo_ids"]
    job = service.store.get("job", ids["job_id"])
    return {"project_id": project["id"], **ids, "state": job["state"],
            "review_state": job["review_state"], "reused": reused,
            "next": "The existing worker renders the queued baseline. Compare it and record your own review; no LTX inference was run."}


def _finish_demo(service: Service, project: dict, *, reused: bool) -> dict:
    ids = dict(project["demo_ids"])
    # If an API crash occurs after queueing but before saving the marker,
    # recover the same job rather than queueing a second baseline on retry.
    jobs = service.store.list("job", project["id"])
    if len(jobs) > 1 or (jobs and (jobs[0]["shot_id"] != ids["shot_id"] or jobs[0]["settings"] != JobInput().model_dump())):
        _demo_changed()
    job = jobs[0] if jobs else service.create_job(ids["shot_id"], JobInput())
    ids["job_id"] = job["id"]
    project = service.store.update("project", project["id"], {"demo_ids": ids, "demo_initialization": "ready"})
    return _demo_result(service, project, reused=reused)


def _record_checkpoint(service: Service, kind: str, record: dict) -> dict:
    digest = hashlib.sha256(json.dumps(record, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    asset_keys = {"source": ("asset_path",), "reference": ("asset_path", "original_asset_path"), "shot": ("preview_path",)}.get(kind, ())
    return {"record_sha256": digest, "assets": {record[key]: sha256(service.asset(record[key])) for key in asset_keys}}


def _resume_demo(service: Service, project: dict, *, reused: bool) -> dict:
    """Checkpoint each fixture stage and refuse to overwrite intervening edits.

    Record creation and checkpoint persistence use separate short transactions.
    An uncheckpointed record is adopted only when it is the sole record of its
    kind and still matches the known procedural fixture. Completed projects are
    returned by the caller before entering this recovery path.
    """
    fixture_info = project.get("demo_fixture", {})
    try:
        fixture = service.asset(fixture_info["path"])
        if (not fixture_info["path"].startswith("demo/") or fixture.name != "synthetic-performance.mp4"
                or sha256(fixture) != fixture_info["sha256"]):
            _demo_changed()
    except (KeyError, OSError, ValueError):
        _demo_changed()
    if project["name"] != DEMO_NAME or project.get("description") != DEMO_DESCRIPTION:
        _demo_changed()
    records = {kind: service.store.list(kind, project["id"]) for kind in ("source", "actor", "reference", "shot", "job", "note")}
    if records["note"] or any(len(items) > 1 for items in records.values()):
        _demo_changed()
    ids = dict(project.get("demo_ids", {}))
    checkpoints = dict(project.get("demo_checkpoints", {}))
    # Check every saved record before applying any later stage. Assets are
    # checked separately because metadata alone cannot detect changed bytes.
    for kind in ("source", "actor", "reference", "shot"):
        if kind + "_id" in ids:
            try:
                record = service.store.get(kind, ids[kind + "_id"])
                if (record.get("project_id") != project["id"] or len(records[kind]) != 1
                        or checkpoints.get(kind) != _record_checkpoint(service, kind, record)):
                    _demo_changed()
            except (KeyError, OSError, ValueError):
                _demo_changed()

    def stage(kind, build, valid, normalize=lambda record: record):
        nonlocal project
        if kind + "_id" in ids:
            return service.store.get(kind, ids[kind + "_id"])
        record = records[kind][0] if records[kind] else build()
        # Service methods add presentation URLs and may return Python tuples;
        # compare and fingerprint the canonical persisted record instead.
        record = service.store.get(kind, record["id"])
        try:
            matches = record.get("project_id") == project["id"] and valid(record)
        except (KeyError, OSError, ValueError):
            _demo_changed()
        if not matches:
            _demo_changed()
        record = normalize(record)
        record = service.store.get(kind, record["id"])
        ids[kind + "_id"] = record["id"]
        checkpoints[kind] = _record_checkpoint(service, kind, record)
        project = service.store.update("project", project["id"], {"demo_ids": dict(ids), "demo_checkpoints": dict(checkpoints)})
        return record

    importer = Service(replace(service.settings, import_roots=(fixture.parent,)))
    source = stage("source", lambda: importer.import_source(project["id"], str(fixture)),
        lambda item: item["path"] == str(fixture) and item["sha256"] == fixture_info["sha256"]
            and sha256(service.asset(item["asset_path"])) == fixture_info["sha256"]
            and (item["width"], item["height"], item["frame_count"]) == (320, 180, 36)
            and abs(item["fps"] - 12) < 0.001,
        lambda item: service.store.update("source", item["id"], {"synthetic": True, "synthetic_fixture_kind": DEMO_KIND}))
    actor = stage("actor", lambda: service.store.create("actor", {"name": "Synthetic drawn actor", "demo_owner": project["id"]}, project["id"]),
        lambda item: item["name"] == "Synthetic drawn actor" and item.get("demo_owner") == project["id"])
    reference = stage("reference", lambda: service.import_reference(actor["id"], ReferenceInput(source_id=source["id"], timestamp=2.5,
            crop=(125, 20, 72, 92), provenance="generated_reconstruction", approval_status="approved", quality=4, notes=DEMO_REFERENCE_NOTES)),
        lambda item: item["actor_id"] == actor["id"] and item.get("source_id") == source["id"]
            and item["source_hash"] == fixture_info["sha256"] and item["source_frame"] == 30
            and item["crop"] == [125, 20, 72, 92] and item["notes"] == DEMO_REFERENCE_NOTES
            and item["provenance"] == "generated_reconstruction" and item["approval_status"] == "approved"
            and item["quality"] == 4 and item["view"] == "front" and item["expression"] == "" and item["lighting"] == ""
            and item["timestamp"] == 2.5 and item["original_dimensions"] == [320, 180]
            and sha256(service.asset(item["asset_path"])) == item["sha256"]
            and sha256(service.asset(item["original_asset_path"])) == item["original_hash"])
    setup = Setup(actor_id=actor["id"], reference_ids=[reference["id"]],
        keyframes=[{"frame": 0, "x": 125, "y": 20, "width": 72, "height": 92}]).model_dump()
    shot = stage("shot", lambda: service.create_shot(project["id"], {"source_id": source["id"], "name": "Synthetic blink and mouth movement",
            "start_time": 0, "end_time": 2, "demo_owner": project["id"]}),
        lambda item: item.get("demo_owner") == project["id"] and item["name"] == "Synthetic blink and mouth movement"
            and item["source_id"] == source["id"] and item["frame_start"] == 0 and item["frame_end"] == 24
            and item["setup"] in (Setup().model_dump(), setup),
        lambda item: service.update_shot(item["id"], {"setup": setup}) if item["setup"] != setup else item)
    guide = project.get("demo_guide")
    if guide:
        try:
            if any(sha256(service.asset(path)) != digest for path, digest in guide["assets"].items()):
                _demo_changed()
        except (KeyError, OSError, ValueError):
            _demo_changed()
    else:
        result = service.guide(shot["id"])
        guide = {"assets": {result[key]: sha256(service.asset(result[key])) for key in ("guide_path", "artifact_path")}}
        project = service.store.update("project", project["id"], {"demo_guide": guide})
    return _finish_demo(service, project, reused=reused)


def queue_synthetic_demo(service: Service) -> dict:
    """Idempotent fixture setup; never starts, steals or waits for a worker."""
    settings = service.settings
    if not all(shutil.which(binary) for binary in (settings.ffmpeg, settings.ffprobe)):
        raise ValueError("Install FFmpeg and ffprobe before creating the synthetic demo")
    with (settings.data_dir / "demo-create.lock").open("a+") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise DemoBusy("Synthetic demo setup is already in progress. Wait a moment, then reopen the demo.") from exc
        project = None
        try:
            existing = _demo_project(service)
            if existing:
                return _demo_result(service, existing, reused=True)
            pending = [item for item in service.store.list("project") if item.get("demo_kind") == DEMO_KIND]
            if pending:
                if len(pending) > 1:
                    _demo_changed()
                project = pending[0]
                return _resume_demo(service, project, reused=True)
            fixtures = settings.data_dir / "demo" / uuid.uuid4().hex
            frames = fixtures / "frames"
            frames.mkdir(parents=True, exist_ok=False)
            for n in range(36):
                image = Image.new("RGB", (320, 180), (32, 42, 56))
                draw = ImageDraw.Draw(image)
                draw.rectangle((10, 130, 310, 170), fill=(49, 92, 107))
                draw.text((15, 140), f"SYNTHETIC PERFORMANCE | frame {n:02d}", fill="white")
                draw.ellipse((125, 25, 195, 110), fill=(218, 170, 116))
                draw.pieslice((123, 20, 197, 70), 180, 360, fill=(55, 36, 25))
                for x in (141, 171):
                    if n % 12 in (6, 7):
                        draw.line((x, 58, x + 7, 58), fill="black", width=2)
                    else:
                        draw.ellipse((x, 53, x + 7, 61), fill="black")
                draw.line((159, 61, 155, 77, 163, 77), fill=(110, 65, 45), width=2)
                draw.ellipse((149, 85, 171, 87 + (n % 5) * 2), fill=(120, 45, 50))
                image.save(frames / f"{n:03d}.png")
            fixture = fixtures / "synthetic-performance.mp4"
            run([settings.ffmpeg, "-nostdin", "-n", "-v", "error", "-framerate", "12", "-i", str(frames / "%03d.png"),
                 "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=3", "-c:v", "libx264",
                 "-pix_fmt", "yuv420p", "-c:a", "aac", "-t", "3", "-movflags", "+faststart", str(fixture)], timeout=60)
            project = service.store.create("project", {"name": DEMO_NAME, "demo_kind": DEMO_KIND,
                "demo_initialization": "initializing", "description": DEMO_DESCRIPTION,
                "demo_fixture": {"path": settings.relative(fixture), "sha256": sha256(fixture)}, "demo_ids": {}, "demo_checkpoints": {}})
            return _resume_demo(service, project, reused=False)
        except Exception as exc:
            if project:
                service.store.update("project", project["id"], {"demo_initialization": "failed"})
            # Raw FFmpeg/OS errors can contain personal paths. The local doctor
            # provides details separately; this action exposes a stable message.
            if isinstance(exc, DemoChanged):
                raise
            raise ValueError("Synthetic demo setup could not finish. Check setup status and retry; the same incomplete fixture will be resumed and existing projects and source files were preserved.") from exc
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)
