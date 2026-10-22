from __future__ import annotations

import fcntl
import json
import math
import os
import subprocess
import threading
import time
import uuid
from pathlib import Path

import psutil

from .config import Settings
from .guides import make_guide, static_placement, working_transform
from .media import Canceled, export_ltx, integrity, prepare_ltx, probe, render_clip, sha256
from .service import Service
from .store import now


class Worker:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.service = Service(settings)
        self.store = self.service.store
        self.lock = None
        self._heartbeat_stop = threading.Event()
        self._heartbeat_thread = None
        self._active_job_id = None
        self._owner = uuid.uuid4().hex

    def _heartbeat(self, *, stopped=False):
        """A small atomic status file, including during blocking model/FFmpeg work.

        The flock remains the authority for ownership. A fresh heartbeat alone
        never establishes a live worker after a crash or PID reuse.
        """
        target = self.settings.data_dir / "worker-status.json"
        temporary = target.with_name(f".worker-status-{self._owner}-{uuid.uuid4().hex}.tmp")
        active_job_id = self._active_job_id
        try:
            temporary.write_text(json.dumps({"owner": self._owner, "pid": os.getpid(),
                "heartbeat": time.time(), "active_job_id": active_job_id,
                "state": "stopped" if stopped else "running" if active_job_id else "idle"}))
            temporary.replace(target)
        except OSError:
            # Monitoring must not interrupt a render. The UI then reports stale
            # telemetry rather than falsely promising that a worker is healthy.
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass

    def _heartbeat_loop(self):
        while not self._heartbeat_stop.wait(2):
            self._heartbeat()

    def acquire(self):
        self.lock = (self.settings.data_dir / "worker.lock").open("a+")
        try:
            fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            self.lock.close()
            self.lock = None
            raise RuntimeError("Another worker owns this data directory. Only one render worker is supported.")
        self.lock.seek(0)
        self.lock.truncate()
        self.lock.write(str(os.getpid()))
        self.lock.flush()
        # Only the lock owner may recover jobs: API restarts must not interrupt live renders.
        for job in self.store.list("job"):
            if job["state"] == "running":
                self.store.update("job", job["id"], {"state": "interrupted", "finished_at": now(), "error": "Worker stopped before completion. Retry creates a new version; no mid-render resume is claimed."})
        self._heartbeat_stop.clear()
        self._heartbeat()
        self._heartbeat_thread = threading.Thread(target=self._heartbeat_loop, name="restorer-worker-heartbeat", daemon=True)
        self._heartbeat_thread.start()

    def close(self):
        if self.lock:
            self._heartbeat_stop.set()
            if self._heartbeat_thread:
                self._heartbeat_thread.join(timeout=3)
            self._active_job_id = None
            self._heartbeat(stopped=True)
            fcntl.flock(self.lock, fcntl.LOCK_UN)
            self.lock.close()
            self.lock = None

    def run_once(self) -> dict | None:
        if not self.lock:
            raise RuntimeError("Worker lock must be acquired before processing")
        job = self.store.claim_job()
        if job:
            self._active_job_id = job["id"]
            self._heartbeat()
            try:
                self.process(job)
            finally:
                self._active_job_id = None
                self._heartbeat()
            return self.store.get("job", job["id"])
        return None

    def loop(self):
        self.acquire()
        try:
            while True:
                if self.run_once() is None:
                    time.sleep(0.4)
        finally:
            self.close()

    def process(self, job: dict):
        work = self.settings.data_dir / "jobs" / job["id"]
        provenance = dict(job["provenance"])
        stats = {"peak_process_tree_rss_bytes": 0, "minimum_system_available_bytes": None,
                 "scope": "Worker and local child CPU RSS; not ComfyUI/Metal/CUDA model memory"}
        start = time.monotonic()

        def log(message: str):
            line = f"[{now()}] {message}\n"
            with (work / "render.log").open("a") as handle:
                handle.write(line)
            current = self.store.get("job", job["id"])
            self.store.update("job", job["id"], {"log": (current.get("log", "") + line)[-30000:]})

        def canceled():
            try:
                process = psutil.Process()
                rss = process.memory_info().rss
                for child in process.children(recursive=True):
                    try:
                        rss += child.memory_info().rss
                    except (psutil.Error, OSError):
                        pass
                stats["peak_process_tree_rss_bytes"] = max(stats["peak_process_tree_rss_bytes"], rss)
                available = psutil.virtual_memory().available
                previous_available = stats["minimum_system_available_bytes"]
                stats["minimum_system_available_bytes"] = min(previous_available, available) if previous_available is not None else available
            except (psutil.Error, OSError) as exc:
                stats["observation_error"] = str(exc)
            return self.store.get("job", job["id"])["cancel_requested"]

        try:
            work.mkdir(exist_ok=False)
            (work / "submission.json").write_text(json.dumps(provenance, indent=2))
            shot = provenance["shot"]
            source = self.store.get("source", shot["source_id"])
            source_path = self.service.asset(provenance["source"]["asset_path"])
            if sha256(source_path) != provenance["source"]["sha256"]:
                raise ValueError("Source content hash changed after submission")
            for ref in provenance["references"]:
                if sha256(self.service.asset(ref["asset_path"])) != ref["sha256"]:
                    raise ValueError("Reference content hash changed after submission")
            if canceled():
                raise Canceled("Canceled before preparation")
            provenance["ffmpeg_version"] = subprocess.run([self.settings.ffmpeg, "-version"], capture_output=True, text=True, check=True, timeout=10).stdout.splitlines()[0]
            source_clip = work / "source-shot.mp4"
            log("Extracting source shot with decoded frame PTS and original soundtrack. No denoise, sharpening, deinterlacing or frame interpolation.")
            render_clip(source_path, source, shot, source_clip, self.settings, canceled=canceled, log=log)
            self.store.update("job", job["id"], {"source_preview_path": self.settings.relative(source_clip), "progress_stage": "rendering_baseline" if job["backend"] == "baseline" else "rendering_ltx"})
            output = work / "output.mp4"
            settings = job["settings"]
            if job["backend"] == "baseline":
                log("Conventional FFmpeg Lanczos baseline upscale. No LTX or actor conditioning is used.")
                render_clip(source_path, source, shot, output, self.settings, scale=settings["scale"], canceled=canceled, log=log)
                provenance["backend_label"] = "baseline upscale"
                provenance["conditioning_consumed"] = False
            elif job["backend"].startswith("comfy_"):
                from .backends.comfy import ComfyBackend
                transform = working_transform(source, settings["scale"])
                frames = 1 + math.ceil((shot["frame_count"] - 1) / 8) * 8
                prepared = work / "ltx-source.mp4"
                prepare_ltx(source_clip, source, shot, prepared, transform, frames, self.settings, canceled=canceled, log=log)
                prepared_info = probe(prepared, self.settings)
                if (prepared_info["width"], prepared_info["height"], prepared_info["frame_count"]) != (transform["width"], transform["height"], frames):
                    raise ValueError("Prepared LTX source has unexpected geometry or frame count")
                provenance["prepared_source"] = {"sha256": sha256(prepared), "width": prepared_info["width"], "height": prepared_info["height"],
                                                 "frame_count": prepared_info["frame_count"], "fps": prepared_info["fps"], "pts": prepared_info["pts"]}
                guide = None
                if settings["use_references"]:
                    reference = provenance["references"][0]
                    guide = work / "conditioning.png"
                    guide_metadata = make_guide(self.service.asset(reference["asset_path"]), guide, static_placement(shot["setup"]), transform)
                    guide_metadata.update(sha256=sha256(guide), reference_sha256=reference["sha256"], reference_provenance=reference["provenance"])
                    (work / "conditioning.json").write_text(json.dumps(guide_metadata, indent=2))
                    provenance["guide"] = guide_metadata
                    self.store.update("job", job["id"], {"guide_path": self.settings.relative(guide)})
                spec = {**settings, "source_clip": str(prepared), "guide_path": str(guide) if guide else None,
                        "width": transform["width"], "height": transform["height"], "frame_count": frames, "fps": source["fps"],
                        "workflow_snapshot": provenance["workflow_snapshot"], "workflow_sha256": provenance["workflow_sha256"]}
                provenance.update(working_dimensions=transform, working_frame_count=frames, padded_tail_frames=frames - shot["frame_count"], conditioning_consumed=settings["use_references"])
                log(f"Prepared {frames} frames, {transform['width']}×{transform['height']} canvas. Padding and tail clones are removed after inference.")
                raw = ComfyBackend(self.settings).render(spec, work, log, canceled)
                generated = probe(raw, self.settings)
                if (generated["width"], generated["height"], generated["frame_count"]) != (transform["width"], transform["height"], frames):
                    raise ValueError("LTX returned unexpected dimensions or frame count; refusing implicit repair")
                if abs(generated["fps"] - source["fps"]) > 0.001:
                    raise ValueError("LTX returned a different frame rate; refusing playback-speed change")
                export_ltx(raw, source_clip, output, shot, transform, source, self.settings, canceled=canceled, log=log)
                provenance["backend_label"] = job["backend"]
                for name in ("comfy-integration.json", "workflow-api.json"):
                    path = work / name
                    if path.exists():
                        provenance[name] = json.loads(path.read_text())
            else:
                raise ValueError("Requested backend has no verified rendering implementation")
            if canceled():
                raise Canceled("Canceled before output validation")
            self.store.update("job", job["id"], {"progress_stage": "validating_output"})
            metadata = probe(output, self.settings)
            checks = integrity(metadata, source, shot)
            source_dar = source["width"] * source["sar"] / source["height"]
            output_dar = metadata["width"] * metadata["sar"] / metadata["height"]
            checks["aspect_ratio_delta"] = output_dar - source_dar
            checks["aspect_passed"] = abs(output_dar / source_dar - 1) < 0.005
            provenance.update(output_sha256=sha256(output), output_metadata={k: metadata[k] for k in ("width", "height", "sar", "duration", "fps", "frame_count", "pts", "has_audio")},
                              technical_checks=checks)
            if not checks["timing_passed"] or not checks["aspect_passed"] or checks["audio_expected"] != checks["audio_present"]:
                raise ValueError("Output failed technical integrity checks: " + json.dumps(checks))
            log("Technical timing, frame count, aspect and audio-presence checks passed. Subjective identity/performance quality remains unreviewed.")
            stats["runtime_seconds"] = time.monotonic() - start
            provenance["memory_statistics"] = stats
            (work / "provenance.json").write_text(json.dumps(provenance, indent=2))
            self.store.update("job", job["id"], {"state": "succeeded", "finished_at": now(), "progress": 1,
                             "progress_stage": "completed",
                             "output_path": self.settings.relative(output), "provenance": provenance, "memory_statistics": stats})
        except BaseException as exc:
            from .backends.comfy import ComfyCanceled
            state = "canceled" if isinstance(exc, (Canceled, ComfyCanceled)) else "interrupted" if isinstance(exc, (KeyboardInterrupt, SystemExit)) else "failed"
            stats["runtime_seconds"] = time.monotonic() - start
            provenance["memory_statistics"] = stats
            if work.is_dir():
                for name in ("comfy-integration.json", "workflow-api.json"):
                    path = work / name
                    if path.is_file():
                        try:
                            provenance[name] = json.loads(path.read_text())
                        except (OSError, ValueError):
                            pass
                (work / "provenance.json").write_text(json.dumps(provenance, indent=2))
                log(f"{state}: {exc}")
            self.store.update("job", job["id"], {"state": state, "finished_at": now(), "error": str(exc), "provenance": provenance, "memory_statistics": stats})
            if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                raise
