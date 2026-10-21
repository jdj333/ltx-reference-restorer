"""Real timestamp, SAR and VFR behavior, not mock video processing."""
import pytest

from restorer.media import export_ltx, integrity, prepare_ltx, probe, render_clip, run, shot_mapping
from restorer.guides import working_transform


def test_frame_mapping_snaps_explicitly(settings, movie):
    source = probe(movie, settings)
    shot = shot_mapping(source, 0.26, 0.99)
    assert shot["frame_start"] == 4 and shot["frame_end"] == 12
    assert shot["requested_start_time"] == 0.26
    assert shot["start_time"] == pytest.approx(4 / 12)
    assert shot["frame_map"][0]["output_timestamp"] == 0
    assert shot["frame_map"][0]["source_frame"] == 4
    with pytest.raises(ValueError):
        shot_mapping(source, 0, source["duration"] + 1)


def test_real_vfr_pts_and_anamorphic_aspect(settings, movie, tmp_path):
    vfr = tmp_path / "vfr.mp4"
    run([settings.ffmpeg, "-nostdin", "-y", "-v", "error", "-i", str(movie), "-vf", "select=not(eq(mod(n\\,3)\\,1)),setsar=4/3", "-c:v", "libx264", "-fps_mode", "vfr", "-c:a", "copy", str(vfr)])
    source = probe(vfr, settings)
    assert source["is_vfr"] and source["sar"] == pytest.approx(4 / 3)
    shot = shot_mapping(source, 0, source["duration"])
    output = tmp_path / "scaled.mp4"
    render_clip(vfr, source, shot, output, settings, scale=2)
    metadata = probe(output, settings)
    result = integrity(metadata, source, shot)
    assert result["timing_passed"], result
    assert metadata["sar"] == pytest.approx(source["sar"])
    assert metadata["width"] / metadata["height"] == pytest.approx(source["width"] / source["height"])


def test_real_ltx_media_padding_and_trimming_without_model_inference(settings, movie, tmp_path):
    source = probe(movie, settings)
    shot = shot_mapping(source, 0.25, 1.25)
    source_clip = tmp_path / "source-shot.mp4"
    render_clip(movie, source, shot, source_clip, settings)
    transform = working_transform(source, 2)
    prepared = tmp_path / "prepared.mp4"
    prepare_ltx(source_clip, source, shot, prepared, transform, 17, settings)
    metadata = probe(prepared, settings)
    assert (metadata["width"], metadata["height"], metadata["frame_count"]) == (320, 192, 17)
    assert not metadata["has_audio"]
    # Identity passthrough of prepared video tests only FFmpeg geometry/export,
    # and is deliberately not a model render or an application render backend.
    exported = tmp_path / "exported.mp4"
    export_ltx(prepared, source_clip, exported, shot, transform, source, settings)
    result = probe(exported, settings)
    assert (result["width"], result["height"], result["frame_count"]) == (320, 180, 12)
    assert integrity(result, source, shot)["timing_passed"]
    assert result["has_audio"]
