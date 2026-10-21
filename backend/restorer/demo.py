"""Entirely generated fixtures: no photographs or private film, no model weights."""
from __future__ import annotations

import json
from pathlib import Path
from PIL import Image, ImageDraw

from .config import Settings
from .media import run, sha256
from .schemas import JobInput, ReferenceInput
from .service import Service
from .worker import Worker


def create_demo(settings: Settings) -> dict:
    service = Service(settings)
    if any(j["state"] in ("queued", "running") for j in service.store.list("job")):
        raise RuntimeError("Demo requires a data directory without pending jobs. Use RESTORER_DATA_DIR=.data/demo and stop its worker first.")
    fixtures = settings.data_dir / "demo"
    frames = fixtures / "frames"
    frames.mkdir(exist_ok=True)
    for n in range(36):
        im = Image.new("RGB", (320, 180), (32, 42, 56))
        draw = ImageDraw.Draw(im)
        draw.rectangle((10, 130, 310, 170), fill=(49, 92, 107))
        draw.text((15, 140), f"SYNTHETIC PERFORMANCE | frame {n:02d}", fill="white")
        draw.ellipse((125, 25, 195, 110), fill=(218, 170, 116))
        draw.pieslice((123, 20, 197, 70), 180, 360, fill=(55, 36, 25))
        if n % 12 in (6, 7):
            draw.line((140, 58, 150, 58), fill="black", width=2)
            draw.line((170, 58, 180, 58), fill="black", width=2)
        else:
            draw.ellipse((141, 53, 148, 61), fill="black")
            draw.ellipse((171, 53, 178, 61), fill="black")
        draw.line((159, 61, 155, 77, 163, 77), fill=(110, 65, 45), width=2)
        draw.ellipse((149, 85, 171, 87 + (n % 5) * 2), fill=(120, 45, 50))
        im.save(frames / f"{n:03d}.png")
    fixture = fixtures / "synthetic-performance.mp4"
    run([settings.ffmpeg, "-nostdin", "-y", "-v", "error", "-framerate", "12", "-i", str(frames / "%03d.png"), "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=3", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-t", "3", "-movflags", "+faststart", str(fixture)])
    project = service.store.create("project", {"name": "Synthetic restoration demonstration"})
    # Demo inputs live in the configured data directory; explicit scope remains restricted.
    original_roots = settings.import_roots
    settings.import_roots = (*original_roots, settings.data_dir)
    try:
        source = service.import_source(project["id"], str(fixture))
        shot = service.create_shot(project["id"], {"source_id": source["id"], "name": "Blink and mouth movement", "start_time": 0, "end_time": 2})
        actor = service.store.create("actor", {"name": "Synthetic actor"}, project["id"])
        reference = service.import_reference(actor["id"], ReferenceInput(source_id=source["id"], timestamp=0, crop=(125, 20, 72, 92), provenance="original_footage", approval_status="pending", quality=4, notes="Procedurally drawn fixture, not historical evidence. Approval is a demo test action."))
        # Deliberate demo-only approval to exercise persistence; real imports always default pending.
        service.store.update("reference", reference["id"], {"approval_status": "approved", "provenance": "generated_reconstruction"})
        service.update_shot(shot["id"], {"setup": {"actor_id": actor["id"], "reference_ids": [reference["id"]], "keyframes": [{"frame": 0, "x": 125, "y": 20, "width": 72, "height": 92}], "interpolation": "linear", "view": "front"}})
        guide = service.guide(shot["id"])
        job = service.create_job(shot["id"], JobInput())
    finally:
        settings.import_roots = original_roots
    worker = Worker(settings)
    worker.acquire()
    try:
        # The demo processes queued jobs in order, respecting the single worker contract.
        while service.store.get("job", job["id"])["state"] == "queued":
            worker.run_once()
    finally:
        worker.close()
    final = service.store.get("job", job["id"])
    if final["state"] != "succeeded":
        raise RuntimeError("Demo render failed: " + str(final["error"]))
    # No automated subjective acceptance. Browser/API provides the explicit approval step.
    result = {"project_id": project["id"], "shot_id": shot["id"], "job_id": job["id"], "state": final["state"],
              "output_url": service.public("job", final)["output_url"], "guide_url": guide["guide_url"],
              "review_state": "unreviewed", "next": "Open the project, compare original/output, record a review, and reopen. No LTX inference was run.",
              "fixture_sha256": sha256(fixture)}
    (fixtures / "latest-demo.json").write_text(json.dumps(result, indent=2))
    return result
