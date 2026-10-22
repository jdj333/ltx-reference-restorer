"""Exact paused comparisons use decoded frames, independent of browser seeking."""
import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image, ImageChops

from restorer.api import create_app
from restorer.media import run, sha256
from restorer.worker import Worker
from test_workflow import post, setup_shot


@pytest.fixture
def colored_job(settings, tmp_path):
    colors = [(240, 20, 20), (20, 240, 20), (20, 20, 240), (230, 190, 20),
              (180, 20, 200), (20, 210, 220), (230, 110, 20), (90, 90, 90)]
    frames = tmp_path / "color-frames"
    frames.mkdir()
    for number, color in enumerate(colors):
        Image.new("RGB", (32, 24), color).save(frames / f"{number:02d}.png")
    movie = tmp_path / "lossless-colors.mkv"
    run([settings.ffmpeg, "-nostdin", "-n", "-v", "error", "-framerate", "4", "-i", str(frames / "%02d.png"),
         "-c:v", "ffv1", "-pix_fmt", "bgr0", str(movie)])
    original_hash = sha256(movie)
    client = TestClient(create_app(settings))
    project = post(client, "/api/projects", {"name": "Exact frame fixture"})
    source = post(client, f"/api/projects/{project['id']}/sources", {"path": str(movie)})
    shot = post(client, f"/api/projects/{project['id']}/shots", {"source_id": source["id"], "name": "Middle four colors", "start_time": 0.5, "end_time": 1.5})
    job = post(client, f"/api/shots/{shot['id']}/jobs", {"backend": "baseline", "scale": 1})
    worker = Worker(settings)
    worker.acquire()
    try:
        completed = worker.run_once()
        assert completed["state"] == "succeeded", completed["error"]
    finally:
        worker.close()
    return client, source, shot, completed, colors, movie, original_hash


def test_job_frames_are_exact_and_use_frozen_selection(colored_job, settings):
    client, source, shot, job, colors, movie, original_hash = colored_job
    service = client.app.state.service
    frozen_job = service.store.get("job", job["id"])
    output_hash = sha256(service.asset(job["output_path"]))
    # Later edits to current records do not redefine a submitted comparison.
    service.store.update("shot", shot["id"], {"frame_start": 0, "frame_count": 8, "frame_map": []})
    service.store.update("source", source["id"], {"asset_path": "sources/not-the-frozen-source.mp4"})
    for frame in (0, 1, 3):
        for view in ("source", "output"):
            response = client.get(f"/api/jobs/{job['id']}/frame", params={"frame": frame, "view": view})
            assert response.status_code == 200, response.text
            assert response.headers["content-type"] == "image/png"
            assert response.headers["cache-control"] == "no-store"
            with Image.open(io.BytesIO(response.content)) as image:
                expected = Image.new("RGB", (32, 24), colors[frame + 2])
                differences = ImageChops.difference(image.convert("RGB"), expected).getextrema()
                # Source is lossless RGB, while the real baseline encodes H.264.
                assert max(high for low, high in differences) <= (0 if view == "source" else 3)
    # Even though the live shot now has eight frames, the frozen shot has four.
    assert client.get(f"/api/jobs/{job['id']}/frame", params={"frame": 4}).status_code == 422
    target = settings.data_dir / "previews" / f"job-{job['id']}-source-1.png"
    correct = target.read_bytes()
    target.write_bytes(b"Modified preview cache")
    regenerated = client.get(f"/api/jobs/{job['id']}/frame", params={"frame": 1})
    assert regenerated.status_code == 200 and regenerated.content == correct
    assert service.store.get("job", job["id"]) == frozen_job
    assert sha256(movie) == original_hash
    assert sha256(service.asset(job["output_path"])) == output_hash


@pytest.mark.parametrize("view", ["source", "output"])
def test_changed_media_is_refused_even_with_cached_frame(colored_job, settings, view):
    client, source, shot, job, colors, movie, original_hash = colored_job
    service = client.app.state.service
    url = f"/api/jobs/{job['id']}/frame"
    response = client.get(url, params={"frame": 1, "view": view})
    assert response.status_code == 200
    cached = settings.data_dir / "previews" / f"job-{job['id']}-{view}-1.png"
    assert cached.is_file()
    expected_png = cached.read_bytes()
    path = service.asset(job["provenance"]["source"]["asset_path"] if view == "source" else job["output_path"])
    path.write_bytes(b"Changed media must not be hidden by an old frame")
    refused = client.get(url, params={"frame": 1, "view": view})
    assert refused.status_code == 422 and "changed" in refused.text
    assert str(settings.data_dir) not in refused.text and str(movie) not in refused.text
    assert cached.read_bytes() == expected_png and sha256(movie) == original_hash


def test_job_frame_state_range_and_view_validation(settings, movie):
    client = TestClient(create_app(settings))
    _, _, shot = setup_shot(client, movie)
    job = post(client, f"/api/shots/{shot['id']}/jobs", {})
    url = f"/api/jobs/{job['id']}/frame"
    assert client.get(url).status_code == 422
    assert client.get(url, params={"view": "other"}).status_code == 422
    assert client.get("/api/jobs/missing-job/frame").status_code == 404
    worker = Worker(settings)
    worker.acquire()
    try:
        assert worker.run_once()["state"] == "succeeded"
    finally:
        worker.close()
    for frame in (-1, shot["frame_count"], "1.5"):
        response = client.get(url, params={"frame": frame})
        assert response.status_code == 422
    assert client.get(url, params={"frame": 0, "view": "output"}).status_code == 200
