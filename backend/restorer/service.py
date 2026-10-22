from __future__ import annotations

import json
import math
import shutil
import subprocess
import uuid
import copy
from pathlib import Path

from PIL import Image, ImageOps

from . import __version__
from .config import Settings
from .guides import interpolate, make_guide, rank_references, static_placement, validate_setup, working_transform
from .media import extract_frame, probe, sha256, shot_mapping
from .schemas import JobInput, ReferenceInput, Setup
from .store import Store


class Service:
    def __init__(self, settings: Settings):
        self.settings = settings
        settings.initialize()
        self.store = Store(settings.data_dir)

    def asset(self, relative: str) -> Path:
        return self.settings.asset_path(relative)

    def url(self, relative: str | None) -> str | None:
        from urllib.parse import quote
        return "/api/assets/" + quote(relative) if relative else None

    def public(self, kind: str, record: dict) -> dict:
        out = dict(record)
        if kind in ("source", "reference"):
            out["media_url"] = self.url(record["asset_path"])
        if kind == "source":
            for key in ("pts", "raw_pts", "frame_durations"):
                out.pop(key, None)
        if kind == "shot":
            out["preview_url"] = self.url(record.get("preview_path"))
        if kind == "job":
            out["output_url"] = self.url(record.get("output_path"))
            out["source_preview_url"] = self.url(record.get("source_preview_path"))
            out["guide_url"] = self.url(record.get("guide_path"))
        return out

    def detail(self, project_id: str) -> dict:
        project = self.store.get("project", project_id)
        return {"project": project, **{plural: [self.public(kind, r) for r in self.store.list(kind, project_id)] for plural, kind in [("sources", "source"), ("shots", "shot"), ("actors", "actor"), ("references", "reference"), ("jobs", "job"), ("notes", "note")]}}

    def import_source(self, project_id: str, path: str) -> dict:
        self.store.get("project", project_id)
        original = self.settings.import_path(path)
        name = uuid.uuid4().hex + original.suffix.lower()
        target = self.settings.data_dir / "sources" / name
        original_hash = sha256(original)
        shutil.copy2(original, target)
        try:
            if sha256(target) != original_hash:
                raise ValueError("Source changed during import; retry after the source file is stable")
            metadata = probe(target, self.settings)
            record = self.store.create("source", {**metadata, "name": original.name, "path": str(original), "asset_path": self.settings.relative(target), "sha256": original_hash}, project_id)
            return self.public("source", record)
        except BaseException:
            target.unlink(missing_ok=True)
            raise

    def create_shot(self, project_id: str, payload: dict) -> dict:
        self.store.get("project", project_id)
        source = self.store.get("source", payload["source_id"])
        if source["project_id"] != project_id:
            raise ValueError("Source belongs to another project")
        mapping = shot_mapping(source, payload["start_time"], payload["end_time"])
        image = self.settings.data_dir / "previews" / (uuid.uuid4().hex + ".png")
        extract_frame(self.asset(source["asset_path"]), image, mapping["frame_start"], self.settings, source.get("video_stream_index", source["metadata"]["video"]["index"]))
        record = self.store.create("shot", {**payload, **mapping, "preview_path": self.settings.relative(image), "setup": Setup().model_dump()}, project_id)
        return self.public("shot", record)

    def update_shot(self, shot_id: str, changes: dict) -> dict:
        shot = self.store.get("shot", shot_id)
        if "setup" in changes:
            setup = Setup.model_validate(changes["setup"]).model_dump()
            changes = {**changes, "setup": setup}
            source = self.store.get("source", shot["source_id"])
            validate_setup(setup, source, shot)
            if setup["reference_ids"] and not setup["actor_id"]:
                raise ValueError("Assign an actor before selecting references")
            if setup["actor_id"]:
                actor = self.store.get("actor", setup["actor_id"])
                if actor["project_id"] != shot["project_id"]:
                    raise ValueError("Actor belongs to another project")
            if len(set(setup["reference_ids"])) != len(setup["reference_ids"]):
                raise ValueError("Duplicate references are not allowed")
            for ref_id in setup["reference_ids"]:
                ref = self.store.get("reference", ref_id)
                if ref["actor_id"] != setup["actor_id"]:
                    raise ValueError("Reference belongs to another actor")
        return self.public("shot", self.store.update("shot", shot_id, changes))

    def import_reference(self, actor_id: str, payload: ReferenceInput) -> dict:
        actor = self.store.get("actor", actor_id)
        data = payload.model_dump()
        stem = uuid.uuid4().hex
        target = self.settings.data_dir / "references" / (stem + ".png")
        if bool(payload.path) == bool(payload.source_id):
            raise ValueError("Provide exactly one of path or source_id")
        if payload.source_id:
            source = self.store.get("source", payload.source_id)
            if source["project_id"] != actor["project_id"]:
                raise ValueError("Reference source belongs to another project")
            if payload.timestamp is None or payload.timestamp >= source["duration"]:
                raise ValueError("Provide a timestamp inside the source")
            index = min(range(len(source["pts"])), key=lambda i: abs(source["pts"][i] - payload.timestamp))
            extract_frame(self.asset(source["asset_path"]), target, index, self.settings, source.get("video_stream_index", source["metadata"]["video"]["index"]))
            data.update(source_file=source["path"], source_hash=source["sha256"], timestamp=source["pts"][index], source_frame=index,
                        provenance="generated_reconstruction" if source.get("synthetic") or payload.provenance == "generated_reconstruction" else "original_footage")
            original_image = target.with_name(stem + "-original.png")
            shutil.copy2(target, original_image)
            data["original_asset_path"] = self.settings.relative(original_image)
            data["original_hash"] = sha256(target)
        else:
            original_image = self.settings.import_path(payload.path)
            data.update(source_file=str(original_image), original_hash=sha256(original_image))
            # Preserve exact imported bytes as evidence as well as an oriented browser PNG.
            original_copy = target.with_name(stem + "-original" + original_image.suffix.lower())
            shutil.copy2(original_image, original_copy)
            if sha256(original_copy) != data["original_hash"]:
                raise ValueError("Reference changed during import")
            data["original_asset_path"] = self.settings.relative(original_copy)
            original_image = original_copy
        with Image.open(original_image) as im:
            image = ImageOps.exif_transpose(im).convert("RGB")
            data["original_dimensions"] = list(image.size)
            if payload.crop:
                x, y, w, h = payload.crop
                if min(x, y) < 0 or min(w, h) <= 0 or x + w > image.width or y + h > image.height:
                    raise ValueError("Crop must be a positive region inside the oriented source image")
                image = image.crop((round(x), round(y), round(x + w), round(y + h)))
            image.save(target)
        data.update(actor_id=actor_id, asset_path=self.settings.relative(target), sha256=sha256(target), width=image.width, height=image.height)
        return self.public("reference", self.store.create("reference", data, actor["project_id"]))

    def ranked(self, actor_id: str, view: str) -> list[dict]:
        actor = self.store.get("actor", actor_id)
        return [self.public("reference", r) for r in rank_references([r for r in self.store.list("reference", actor["project_id"]) if r["actor_id"] == actor_id], view)]

    def backends(self) -> list[dict]:
        has_ffmpeg = bool(shutil.which(self.settings.ffmpeg) and shutil.which(self.settings.ffprobe))
        base = {"id": "baseline", "label": "Baseline upscale (FFmpeg Lanczos)", "available": has_ffmpeg,
                "operations": ["upscale", "variable_frame_timestamps", "source_audio"], "supports_references": False,
                "reason": "Conventional upscale; actor references are review aids only." if has_ffmpeg else "FFmpeg and ffprobe are required", "controls": ["scale"]}
        try:
            from .backends.comfy import ComfyBackend
            cap = ComfyBackend(self.settings).capability()
        except (ImportError, OSError, ValueError, RuntimeError) as e:
            cap = {"available": False, "reason": str(e), "blockers": [str(e)], "supports_references": False}
        comfy = []
        for mode in ("restore", "refine"):
            supported_mode = cap.get("operation", cap.get("mode"))
            available = cap.get("available", False) and (not supported_mode or supported_mode in (mode, "comfy_" + mode))
            comfy.append({**cap, "id": "comfy_" + mode, "label": f"LTX 2.5 {mode.title()} (ComfyUI)", "available": available,
                          "reason": cap.get("reason") or "; ".join(cap.get("blockers", [])) or ("Configured workflow is for " + str(supported_mode) if not available else "API graph validated; inference requires installed compatible models"),
                          "operations": ["source_video_restoration"] + (["static_spatial_reference"] if cap.get("supports_references") else []), "controls": cap.get("controls", ["scale", "prompt", "seed", "steps", "cfg"] )})
        return [base, *comfy, {"id": "mlx", "label": "MLX (unavailable for this restoration workflow)", "available": False, "supports_references": False,
                                  "operations": [], "reason": "Required LTX 2.5 source-video + negative-token spatial reference operations have not been ported and verified. Image-to-video anchors are not actor identity references.", "controls": []}]

    def guide(self, shot_id: str, *, backend="baseline", use_references=False, scale=2, output: Path | None = None) -> dict:
        shot = self.store.get("shot", shot_id)
        source = self.store.get("source", shot["source_id"])
        setup = shot["setup"]
        if not setup["reference_ids"]:
            raise ValueError("Select an approved actor reference first")
        if len(setup["reference_ids"]) != 1:
            raise ValueError("First version supports exactly one selected reference per conditioning image; keep additional actor references in the library")
        reference = self.store.get("reference", setup["reference_ids"][0])
        if reference["approval_status"] != "approved":
            raise ValueError("Only explicitly approved references may enter a guide")
        box = static_placement(setup) if use_references else interpolate(setup["keyframes"], 0, setup["interpolation"])
        target = output or self.settings.data_dir / "guides" / (uuid.uuid4().hex + ".png")
        metadata = make_guide(self.asset(reference["asset_path"]), target, box, working_transform(source, scale))
        metadata.update(reference_id=reference["id"], reference_hash=reference["sha256"], provenance=reference["provenance"],
                        guide_path=self.settings.relative(target), guide_url=self.url(self.settings.relative(target)), sha256=sha256(target),
                        conditioning=bool(use_references and backend.startswith("comfy_")),
                        description="Gray spatial reference canvas sent to the configured -1 guide node." if use_references and backend.startswith("comfy_") else "Placement preview for review. The baseline engine does not consume actor conditioning.",
                        warnings=["This reference may influence invented detail. Human identity and performance review is required."])
        metadata["artifact_path"] = self.settings.relative(target.with_suffix(".json"))
        metadata["artifact_url"] = self.url(metadata["artifact_path"])
        target.with_suffix(".json").write_text(json.dumps(metadata, indent=2))
        return metadata

    def validate_job(self, shot_id: str, payload: JobInput) -> tuple[dict, dict, dict]:
        shot = self.store.get("shot", shot_id)
        source = self.store.get("source", shot["source_id"])
        capability = next(b for b in self.backends() if b["id"] == payload.backend)
        if not capability["available"]:
            raise ValueError(f"{capability['label']} unavailable: {capability['reason']}")
        if payload.backend == "baseline":
            if payload.use_references:
                raise ValueError("Baseline upscale does not consume actor reference conditioning")
            if source["interlaced"] and (source["metadata"]["video"].get("field_order") not in ("tt", "bt", "bb", "tb") or source["height"] * payload.scale % 4):
                raise ValueError("Interlaced baseline requires a known field order and an output height divisible by 4; prepare an explicitly documented derivative for unsupported field layouts")
        else:
            if payload.steps != 8:
                raise ValueError("The configured distilled LTX recipe requires exactly 8 steps")
            if source["is_vfr"]:
                raise ValueError("This LTX workflow requires CFR; VFR sources remain available for baseline. Make a separately documented CFR derivative before LTX.")
            if source["interlaced"]:
                raise ValueError("LTX requires a progressive source. No automatic deinterlacing is applied; import an explicitly prepared progressive derivative.")
            padded = 1 + math.ceil(max(0, shot["frame_count"] - 1) / 8) * 8
            if padded < 9 or padded > 97:
                raise ValueError("Initial LTX workflow supports 2..97 source frames, padded to 8n+1 (minimum 9); select a shorter shot")
            t = working_transform(source, payload.scale)
            if t["width"] > 4096 or t["height"] > 4096:
                raise ValueError("Initial LTX working canvas is limited to 4096 pixels per dimension")
            if payload.use_references:
                if not capability.get("supports_references"):
                    raise ValueError("Configured workflow does not support verified spatial references")
                # Validate reference approval and static placement before queueing.
                setup = shot["setup"]
                if not setup.get("actor_id") or len(setup["reference_ids"]) != 1:
                    raise ValueError("Assign one actor and select exactly one approved reference")
                static_placement(setup)
                ref = self.store.get("reference", setup["reference_ids"][0])
                if ref["approval_status"] != "approved":
                    raise ValueError("Selected reference is not approved")
        return shot, source, capability

    def create_job(self, shot_id: str, payload: JobInput, *, parent_job_id=None, group_id=None) -> dict:
        shot, source, capability = self.validate_job(shot_id, payload)
        refs = [self.store.get("reference", r) for r in shot["setup"]["reference_ids"]]
        workflow = self.settings.comfy_workflow
        workflow_snapshot = json.loads(workflow.read_text()) if payload.backend.startswith("comfy_") and workflow else None
        provenance = {"application_version": __version__, "source": {k: source[k] for k in ("id", "sha256", "asset_path", "path", "width", "height", "sar", "fps", "is_vfr", "has_audio")},
                      "shot": shot, "references": refs, "actor": self.store.get("actor", shot["setup"]["actor_id"]) if shot["setup"]["actor_id"] else None,
                      "settings": payload.model_dump(), "capability": capability, "workflow_snapshot": workflow_snapshot,
                      "workflow_sha256": sha256(workflow) if workflow_snapshot else None,
                      "audio_policy": "Original source first audio stream; never generated audio", "frame_map": shot["frame_map"],
                      "timing_policy": "Baseline retains decoded PTS; LTX accepts CFR only; padded tail frames trimmed on export", "approval": "unreviewed"}
        return self.queue_snapshot(provenance, payload, parent_job_id=parent_job_id, group_id=group_id)

    def queue_snapshot(self, provenance: dict, payload: JobInput, *, parent_job_id=None, group_id=None) -> dict:
        provenance = copy.deepcopy(provenance)
        provenance["settings"] = payload.model_dump()
        shot = provenance["shot"]
        record = self.store.create("job", {"shot_id": shot["id"], "backend": payload.backend, "settings": payload.model_dump(), "state": "queued",
                                "progress": 0, "cancel_requested": False, "started_at": None, "finished_at": None, "error": None, "log": "", "output_path": None,
                                "source_preview_path": None, "review_state": "unreviewed", "reviews": [], "parent_job_id": parent_job_id, "group_id": group_id, "provenance": provenance}, shot["project_id"])
        return self.public("job", record)

    def cancel(self, job_id: str) -> dict:
        job = self.store.get("job", job_id)
        if job["state"] not in ("queued", "running"):
            raise ValueError("Only queued or running jobs can be canceled")
        from .store import now
        return self.public("job", self.store.update("job", job_id, {"cancel_requested": True, **({"state": "canceled", "finished_at": now()} if job["state"] == "queued" else {})}))

    def retry(self, job_id: str) -> dict:
        old = self.store.get("job", job_id)
        if old["state"] not in ("failed", "interrupted", "canceled"):
            raise ValueError("Retry is available for failed, canceled, or interrupted jobs; render a new version for completed outputs")
        # Reuse submission snapshots, even if current shot/reference/config settings changed.
        # The adapter still checks its frozen workflow against live nodes before inference.
        fields = ("application_version", "source", "shot", "references", "actor", "settings", "capability", "workflow_snapshot", "workflow_sha256", "audio_policy", "frame_map", "timing_policy", "approval")
        provenance = {key: copy.deepcopy(old["provenance"][key]) for key in fields}
        record = self.store.create("job", {"shot_id": old["shot_id"], "backend": old["backend"], "settings": old["settings"], "state": "queued", "progress": 0, "cancel_requested": False,
                                "started_at": None, "finished_at": None, "error": None, "log": "", "output_path": None, "source_preview_path": None,
                                "review_state": "unreviewed", "reviews": [], "parent_job_id": job_id, "group_id": None, "provenance": provenance}, old["project_id"])
        return self.public("job", record)
