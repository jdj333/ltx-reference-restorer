from __future__ import annotations

import json
import subprocess
import uuid
from pathlib import Path
from typing import Literal

from fastapi import Body, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.middleware.cors import CORSMiddleware

from .config import Settings, load_settings
from .media import extract_frame, probe, sha256
from .schemas import ActorInput, GuideInput, JobInput, NoteInput, ProjectInput, ReferenceInput, ReferencePatch, ReviewInput, ShotInput, ShotPatch, SourceInput
from .service import Service
from .store import now
from . import onboarding


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or load_settings()
    service = Service(settings)
    app = FastAPI(title="LTX Reference Restorer", version="0.1.0")
    app.state.service = service
    origins = [f"http://{host}:{port}" for host in ("localhost", "127.0.0.1") for port in (settings.port, 5173)]
    app.add_middleware(CORSMiddleware, allow_origins=origins, allow_methods=["GET", "POST", "PATCH"], allow_headers=["Content-Type"])

    @app.middleware("http")
    async def local_access(request: Request, call_next):
        # Block drive-by websites and DNS rebinding against a file-importing localhost service.
        host = request.url.hostname
        if settings.host in ("127.0.0.1", "localhost", "::1") and host not in ("127.0.0.1", "localhost", "::1", "testserver"):
            return JSONResponse({"detail": "Localhost Host required"}, status_code=403)
        origin = request.headers.get("origin")
        if origin and origin not in origins:
            return JSONResponse({"detail": "Untrusted browser origin"}, status_code=403)
        return await call_next(request)

    @app.exception_handler(KeyError)
    async def missing(_, exc):
        return JSONResponse({"detail": str(exc)}, status_code=404)

    @app.exception_handler(ValueError)
    async def invalid(_, exc):
        return JSONResponse({"detail": str(exc)}, status_code=422)

    @app.exception_handler(FileNotFoundError)
    async def not_found(_, exc):
        return JSONResponse({"detail": "File or executable not found: " + str(exc)}, status_code=422)

    @app.exception_handler(subprocess.SubprocessError)
    async def media_error(_, exc):
        return JSONResponse({"detail": "Media inspection failed: " + str(exc)}, status_code=422)

    @app.get("/api/health")
    def health():
        return {"status": "ok", "version": "0.1.0", "data_dir": str(settings.data_dir)}

    @app.get("/api/doctor")
    def doctor():
        from .doctor import report
        return report(settings)

    @app.get("/api/backends")
    def backends():
        return service.backends()

    @app.get("/api/system/status")
    def setup_status():
        return onboarding.setup_status(service)

    @app.get("/api/system/diagnostics")
    def diagnostics():
        return JSONResponse(onboarding.shareable_diagnostics(onboarding.setup_status(service)),
                            headers={"Content-Disposition": 'attachment; filename="ltx-restorer-diagnostics.json"'})

    @app.get("/api/files")
    def local_files(kind: Literal["video", "image"] = "video", directory: str | None = None):
        return onboarding.browse_files(settings, kind=kind, directory=directory)

    @app.get("/api/files/image-info")
    def image_info(path: str):
        return onboarding.image_info(settings, path)

    @app.get("/api/files/preview")
    def image_preview(path: str):
        content, (width, height) = onboarding.image_preview(settings, path)
        return Response(content, media_type="image/png", headers={"X-Image-Width": str(width),
                        "X-Image-Height": str(height), "X-Content-Type-Options": "nosniff", "Cache-Control": "no-store"})

    @app.post("/api/demo")
    def synthetic_demo():
        try:
            return onboarding.queue_synthetic_demo(service)
        except onboarding.DemoBusy as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.get("/api/presets")
    def presets():
        return [{"id": key, "label": preset.get("label", key), "settings": JobInput(**{k: v for k, v in preset.items() if k != "label"}).model_dump()} for key, preset in settings.presets.items()]

    @app.get("/api/projects")
    def projects():
        return service.store.list("project")

    @app.post("/api/projects", status_code=201)
    def create_project(payload: ProjectInput):
        return service.store.create("project", payload.model_dump())

    @app.get("/api/projects/{project_id}")
    def project_detail(project_id: str):
        return service.detail(project_id)

    @app.post("/api/projects/{project_id}/sources", status_code=201)
    def source(project_id: str, payload: SourceInput):
        return service.import_source(project_id, payload.path)

    @app.post("/api/projects/{project_id}/shots", status_code=201)
    def shot(project_id: str, payload: ShotInput):
        return service.create_shot(project_id, payload.model_dump())

    @app.patch("/api/shots/{shot_id}")
    def update_shot(shot_id: str, payload: ShotPatch):
        # Ignore absent top-level updates while preserving actor_id=None inside
        # a complete setup: it means an intentional actor assignment clear.
        changes = {key: value for key, value in payload.model_dump().items() if value is not None}
        return service.update_shot(shot_id, changes)

    @app.post("/api/projects/{project_id}/actors", status_code=201)
    def actor(project_id: str, payload: ActorInput):
        service.store.get("project", project_id)
        return service.store.create("actor", payload.model_dump(), project_id)

    @app.post("/api/actors/{actor_id}/references", status_code=201)
    def reference(actor_id: str, payload: ReferenceInput):
        return service.import_reference(actor_id, payload)

    @app.get("/api/actors/{actor_id}/references")
    def references(actor_id: str, view: str = "front"):
        if view not in ("front", "three_quarter", "profile"):
            raise ValueError("Unknown reference view")
        return service.ranked(actor_id, view)

    @app.patch("/api/references/{reference_id}")
    def update_reference(reference_id: str, payload: ReferencePatch):
        return service.public("reference", service.store.update("reference", reference_id, payload.model_dump(exclude_none=True)))

    @app.get("/api/sources/{source_id}/frame")
    def source_frame(source_id: str, timestamp: float = 0):
        source = service.store.get("source", source_id)
        if not 0 <= timestamp < source["duration"]:
            raise ValueError("Timestamp outside source")
        index = min(range(len(source["pts"])), key=lambda i: abs(source["pts"][i] - timestamp))
        target = settings.data_dir / "previews" / f"{source_id}-{index}.png"
        if not target.exists():
            extract_frame(service.asset(source["asset_path"]), target, index, settings, source.get("video_stream_index", source["metadata"]["video"]["index"]))
        return FileResponse(target)

    @app.get("/api/shots/{shot_id}/frame")
    def shot_frame(shot_id: str, frame: int = 0):
        shot = service.store.get("shot", shot_id)
        if not 0 <= frame < shot["frame_count"]:
            raise ValueError("Frame outside shot")
        source = service.store.get("source", shot["source_id"])
        target = settings.data_dir / "previews" / f"{shot_id}-{frame}.png"
        if not target.exists():
            extract_frame(service.asset(source["asset_path"]), target, shot["frame_start"] + frame, settings, source.get("video_stream_index", source["metadata"]["video"]["index"]))
        return FileResponse(target)

    @app.post("/api/shots/{shot_id}/guide")
    def guide(shot_id: str, payload: GuideInput = GuideInput()):
        return service.guide(shot_id, **payload.model_dump())

    @app.post("/api/shots/{shot_id}/jobs", status_code=201)
    def create_job(shot_id: str, payload: JobInput):
        return service.create_job(shot_id, payload)

    @app.post("/api/shots/{shot_id}/comparison", status_code=201)
    def comparison(shot_id: str, payload: JobInput):
        if payload.backend not in ("comfy_restore", "comfy_refine"):
            raise ValueError("Choose a configured LTX backend for the controlled A/B/C comparison")
        baseline = payload.model_copy(update={"backend": "baseline", "use_references": False})
        without = payload.model_copy(update={"use_references": False})
        with_ref = payload.model_copy(update={"use_references": True})
        for spec in (baseline, without, with_ref):
            service.validate_job(shot_id, spec)
        group = uuid.uuid4().hex
        # Freeze B/C once so another browser's edits cannot change conditioning inputs.
        a = service.create_job(shot_id, baseline, group_id=group)
        b = service.create_job(shot_id, without, group_id=group)
        c = service.queue_snapshot(b["provenance"], with_ref, group_id=group)
        return {"group_id": group, "jobs": [a, b, c],
                "controlled_difference": "B/C differ only in spatial reference conditioning; same snapshot, prompt, seed, dimensions, sampler settings and source guide. Generative results still require human review."}

    @app.get("/api/jobs/{job_id}")
    def job(job_id: str):
        return service.public("job", service.store.get("job", job_id))

    @app.get("/api/jobs/{job_id}/frame")
    def job_frame(job_id: str, frame: int = 0, view: Literal["source", "output"] = "source"):
        record = service.store.get("job", job_id)
        if record["state"] != "succeeded":
            raise HTTPException(422, "Only a completed output has comparison frames")
        try:
            provenance = record["provenance"]
            shot = provenance["shot"]
            if not 0 <= frame < shot["frame_count"]:
                raise HTTPException(422, "Frame outside completed job")
            if view == "source":
                media_path = service.asset(provenance["source"]["asset_path"])
                expected_hash = provenance["source"]["sha256"]
                mapping = shot.get("frame_map")
                index = mapping[frame]["source_frame"] if mapping else shot["frame_start"] + frame
            else:
                media_path = service.asset(record["output_path"])
                expected_hash = provenance["output_sha256"]
                index = frame
            if type(index) is not int or index < 0:
                raise ValueError("Invalid frozen frame mapping")
            # Validate even when a PNG is already cached. A stale browser or
            # preview cache must not hide changed source/output evidence.
            if sha256(media_path) != expected_hash:
                raise HTTPException(422, "Comparison media changed since this job completed; frame preview refused")
            target = service.asset(f"previews/job-{record['id']}-{view}-{frame}.png")
            metadata_path = service.asset(f"previews/job-{record['id']}-{view}-{frame}.json")
            cached = False
            try:
                metadata = json.loads(metadata_path.read_text())
                cached = (metadata.get("media_sha256") == expected_hash and metadata.get("decoded_frame") == index
                          and metadata.get("png_sha256") == sha256(target))
            except (OSError, ValueError, AttributeError):
                pass
            if not cached:
                temporary = service.asset(f"previews/.job-{record['id']}-{uuid.uuid4().hex}.png")
                temporary_metadata = temporary.with_suffix(".json")
                try:
                    # Inspect the hash-verified file itself, including sources
                    # whose first stream is audio or an attached cover picture.
                    stream = probe(media_path, settings, frames=False)["video_stream_index"]
                    extract_frame(media_path, temporary, index, settings, stream)
                    if sha256(media_path) != expected_hash:
                        raise HTTPException(422, "Comparison media changed during frame extraction; frame preview refused")
                    temporary_metadata.write_text(json.dumps({"media_sha256": expected_hash, "decoded_frame": index,
                                                               "png_sha256": sha256(temporary)}))
                    temporary.replace(target)
                    temporary_metadata.replace(metadata_path)
                finally:
                    temporary.unlink(missing_ok=True)
                    temporary_metadata.unlink(missing_ok=True)
            return FileResponse(target, media_type="image/png", headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})
        except (KeyError, IndexError, TypeError, ValueError, OSError, subprocess.SubprocessError, RuntimeError) as exc:
            raise HTTPException(422, "Comparison frame could not be verified or decoded") from exc

    @app.post("/api/jobs/{job_id}/cancel")
    def cancel(job_id: str):
        return service.cancel(job_id)

    @app.post("/api/jobs/{job_id}/retry", status_code=201)
    def retry(job_id: str):
        return service.retry(job_id)

    @app.post("/api/jobs/{job_id}/review")
    def review(job_id: str, payload: ReviewInput):
        record = service.store.get("job", job_id)
        if record["state"] != "succeeded":
            raise ValueError("Only a completed output can be reviewed")
        output = service.asset(record["output_path"])
        if sha256(output) != record["provenance"]["output_sha256"]:
            raise ValueError("Output hash changed; review refused")
        event = {**payload.model_dump(), "at": now(), "output_sha256": record["provenance"]["output_sha256"]}
        return service.public("job", service.store.update("job", job_id, {"review_state": payload.state, "reviews": [*record["reviews"], event]}))

    @app.post("/api/projects/{project_id}/notes", status_code=201)
    def note(project_id: str, payload: NoteInput):
        service.store.get("project", project_id)
        for kind in ("shot", "actor"):
            identity = getattr(payload, kind + "_id")
            if identity and service.store.get(kind, identity)["project_id"] != project_id:
                raise ValueError("Note target belongs to another project")
        return service.store.create("note", payload.model_dump(), project_id)

    @app.get("/api/assets/{asset_path:path}")
    def asset(asset_path: str):
        target = service.asset(asset_path)
        relative = Path(asset_path)
        if not relative.parts or relative.parts[0] not in ("sources", "references", "previews", "guides", "jobs", "demo") or target.suffix.lower() not in (".png", ".jpg", ".jpeg", ".webp", ".mp4", ".mov", ".mkv", ".webm", ".avi", ".json") or not target.is_file():
            raise HTTPException(404, "Media asset not found")
        return FileResponse(target, headers={"X-Content-Type-Options": "nosniff"})

    # Source checkout layout (the supported first-version installation).
    dist = Path(__file__).resolve().parents[2] / "frontend" / "dist"

    @app.get("/{route:path}")
    def frontend(route: str):
        if route.startswith("api/"):
            raise HTTPException(404, "Unknown API endpoint")
        requested = (dist / route).resolve()
        if requested.is_relative_to(dist.resolve()) and requested.is_file():
            return FileResponse(requested)
        if (dist / "index.html").is_file():
            return FileResponse(dist / "index.html")
        return JSONResponse({"message": "API running. Build browser UI with: cd frontend && npm ci && npm run build", "docs": "/docs"})

    return app
