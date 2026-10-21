"""Real FFmpeg preparation on synthetic fixtures; no network film in CI."""
import json
import shutil
from pathlib import Path

import pytest

from restorer.media import probe, sha256
from restorer.public_prepare import prepare_fixtures


@pytest.fixture
def acquisition(tmp_path, movie):
    catalog_path = Path(__file__).resolve().parents[1] / "fixtures/public-films/catalog.json"
    catalog = json.loads(catalog_path.read_text())
    film = catalog["films"][0]
    media_dir = tmp_path / "media"
    directory = media_dir / film["id"]
    directory.mkdir(parents=True)
    source = directory / "source.mp4"
    shutil.copy2(movie, source)
    ledger = {"schema_version": 1, "status": "complete", "film_id": film["id"], "provider": "youtube",
              "source_url": film["youtube"]["url"], "edition": "YouTube upload " + film["youtube"]["video_id"],
              "file": "source.mp4", "sha256": sha256(source), "size_bytes": source.stat().st_size,
              "youtube": film["youtube"], "rights_url": catalog["rights"]["curated_source_url"]}
    (directory / "acquisition.json").write_text(json.dumps(ledger))
    selections = {"schema_version": 1, "provider": "youtube", "clips": [{"id": "generated-preparation-test",
                  "film_id": film["id"], "title": "Generated preparation fixture", "youtube_video_id": film["youtube"]["video_id"],
                  "source_geometry": {"width": 160, "height": 90, "fps": 12}, "source_duration_seconds": 2,
                  "start_frame": 2, "frame_count": 9, "reference_frame": 15, "reference_crop": [40, 10, 20, 30],
                  "downscale_divisor": 2, "placement": {"x": 20, "y": 5, "width": 10, "height": 15}}]}
    selection_path = tmp_path / "selections.json"
    selection_path.write_text(json.dumps(selections))
    return catalog_path, selection_path, media_dir, source


def test_preparation_retains_actual_source_frame_mapping(settings, acquisition, tmp_path):
    catalog, selections, media_dir, source = acquisition
    before = sha256(source)
    root = tmp_path / "prepared"
    manifest = prepare_fixtures(catalog, selections, media_dir, root, settings)
    fixture = manifest["fixtures"][0]
    media = probe(root / fixture["clip_path"], settings)
    assert (media["width"], media["height"], media["frame_count"]) == (80, 45, 9)
    assert media["has_audio"] and not media["is_vfr"]
    mapping = fixture["preparation"]["source_frame_map"]
    assert mapping[0]["source_frame"] == 2
    assert mapping[0]["source_timestamp"] == pytest.approx(2 / 12, abs=0.00001)
    assert mapping[-1]["output_timestamp"] == pytest.approx(8 / 12, abs=0.00001)
    assert fixture["preparation"]["reference_frame"] == 15
    assert sha256(source) == before == fixture["source_sha256"]
    assert json.loads((root / "manifest.json").read_text()) == manifest
    assert str(tmp_path) not in json.dumps(manifest)
    with pytest.raises(ValueError, match="empty"):
        prepare_fixtures(catalog, selections, media_dir, root, settings)


@pytest.mark.parametrize("change", ["overlap", "geometry", "duration", "provider", "changed_source"])
def test_preparation_refuses_changed_editions_or_target_reference_leakage(settings, acquisition, tmp_path, change):
    catalog, selections, media_dir, source = acquisition
    spec = json.loads(selections.read_text())
    item = spec["clips"][0]
    if change == "overlap": item["reference_frame"] = 4
    if change == "geometry": item["source_geometry"]["width"] = 320
    if change == "duration": item["source_duration_seconds"] = 60
    if change == "provider": spec["provider"] = "archive"
    if change == "changed_source": source.write_bytes(b"changed")
    selections.write_text(json.dumps(spec))
    with pytest.raises(ValueError):
        prepare_fixtures(catalog, selections, media_dir, tmp_path / "prepared", settings)
