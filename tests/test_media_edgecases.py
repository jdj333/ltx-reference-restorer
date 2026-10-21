"""Real FFmpeg edge cases for geometry and soundtrack alignment."""

from array import array
import json
import subprocess

import pytest

from restorer.media import probe, render_clip, run, shot_mapping


def test_rotated_video_is_refused_before_implicit_autorotation(settings, movie, tmp_path):
    help_text = subprocess.run([settings.ffmpeg, "-hide_banner", "-h", "full"], capture_output=True, text=True, check=True).stdout
    if "-display_rotation" not in help_text:
        pytest.skip("FFmpeg build cannot construct a display-matrix fixture")
    rotated = tmp_path / "rotated.mp4"
    run([settings.ffmpeg, "-nostdin", "-y", "-v", "error", "-display_rotation:v:0", "90", "-i", str(movie), "-c", "copy", str(rotated)])
    inspection = subprocess.run([settings.ffprobe, "-v", "error", "-show_streams", "-of", "json", str(rotated)], capture_output=True, text=True, check=True)
    video = next(s for s in json.loads(inspection.stdout)["streams"] if s["codec_type"] == "video")
    assert any(abs(s.get("rotation", 0)) == 90 for s in video.get("side_data_list", []))
    with pytest.raises(ValueError, match="[Rr]otat"):
        probe(rotated, settings)


def _tone_onset(path, settings):
    # Decode the stream's real timestamp offset into initial silence, then inspect
    # audible tone onset. Packet start_time alone includes AAC encoder priming.
    result = subprocess.run([
        settings.ffmpeg, "-v", "error", "-i", str(path), "-vn", "-af", "aresample=async=1:first_pts=0",
        "-ac", "1", "-ar", "48000", "-f", "f32le", "-",
    ], capture_output=True, check=True)
    samples = array("f")
    samples.frombytes(result.stdout)
    return next(i / 48000 for i, sample in enumerate(samples) if abs(sample) > 0.02)


def test_baseline_retains_source_audio_gap_and_shot_alignment(settings, tmp_path):
    source_path = tmp_path / "delayed-audio.mp4"
    run([
        settings.ffmpeg, "-nostdin", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=160x90:rate=12:duration=2",
        "-itsoffset", "0.5", "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=1.5",
        "-map", "0:v:0", "-map", "1:a:0", "-c:v", "libx264", "-c:a", "aac", "-t", "2", str(source_path),
    ])
    source = probe(source_path, settings)
    onset = _tone_onset(source_path, settings)
    assert 0.49 < onset < 0.51
    shot = shot_mapping(source, 0.25, 1.25)
    output = tmp_path / "baseline.mp4"
    render_clip(source_path, source, shot, output, settings, scale=2)
    assert _tone_onset(output, settings) + shot["start_time"] == pytest.approx(onset, abs=0.005)


@pytest.mark.parametrize("field", ["top", "bottom"])
def test_baseline_preserves_interlaced_field_order_without_deinterlacing(settings, tmp_path, field):
    source_path = tmp_path / f"interlaced-{field}.mp4"
    order = "tff" if field == "top" else "bff"
    run([
        settings.ffmpeg, "-nostdin", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=160x96:rate=24:duration=2",
        "-vf", f"tinterlace=interleave_{field}", "-c:v", "libx264", "-flags", "+ilme+ildct", "-x264-params", f"{order}=1",
        "-pix_fmt", "yuv420p", str(source_path),
    ])
    source = probe(source_path, settings)
    assert source["interlaced"]
    shot = shot_mapping(source, 0, 2)
    output = tmp_path / f"baseline-{field}.mp4"
    render_clip(source_path, source, shot, output, settings, scale=2)
    produced = probe(output, settings)
    assert produced["interlaced"]
    assert produced["metadata"]["video"]["field_order"] == source["metadata"]["video"]["field_order"]
    assert produced["frame_count"] == source["frame_count"] == 24
    assert produced["fps"] == source["fps"] == 12
    assert produced["pts"] == pytest.approx(source["pts"])
    assert (produced["width"], produced["height"]) == (320, 192)
