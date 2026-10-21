"""Prepare timestamp-mapped, non-generative fixtures from a reviewed public edition."""
from __future__ import annotations

import json
import re
import subprocess
from fractions import Fraction
from pathlib import Path

from PIL import Image, ImageOps

from .config import Settings
from .media import probe, run, sha256
from .public_acquire import _existing, _load_catalog


def _metadata(path: Path, settings: Settings) -> dict:
    result = subprocess.run([settings.ffprobe, "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)], capture_output=True, text=True, check=True, timeout=60)
    data = json.loads(result.stdout)
    video = next(v for v in data["streams"] if v["codec_type"] == "video" and not v.get("disposition", {}).get("attached_pic"))
    return {"video": video, "duration": float(data["format"]["duration"]), "has_audio": any(v["codec_type"] == "audio" for v in data["streams"])}


def _source_timestamps(path: Path, start: float, count: int, fps: float, stream_index: int, settings: Settings) -> list[float]:
    # Input seeking can land before the requested position; filter decoded PTS,
    # then retain the actual first selected frame and all source timestamps.
    result = subprocess.run([settings.ffprobe, "-v", "error", "-read_intervals", f"{max(0, start - 1):.9f}%+30", "-select_streams", str(stream_index), "-show_frames", "-show_entries", "frame=best_effort_timestamp_time", "-of", "json", str(path)], capture_output=True, text=True, check=True, timeout=120)
    timestamps = [float(f["best_effort_timestamp_time"]) for f in json.loads(result.stdout).get("frames", [])]
    selected = [t for t in timestamps if t >= start - 0.00001][:count]
    if len(selected) != count or abs(selected[0] - start) > 0.001 or any(abs((t - selected[0]) - i / fps) > 0.001 for i, t in enumerate(selected)):
        raise ValueError("Selected source frames are missing or not CFR; choose and document a supported edition")
    return selected


def prepare_fixtures(catalog_path: Path, selections_path: Path, media_dir: Path, output_dir: Path, settings: Settings) -> dict:
    catalog, films = _load_catalog(catalog_path)
    by_id = {film["id"]: film for film in films}
    selection = json.loads(Path(selections_path).read_text())
    if selection.get("schema_version") != 1 or selection.get("provider") != "youtube" or not selection.get("clips"):
        raise ValueError("Reviewed schema_version 1 YouTube clip selections are required; archive timings are not interchangeable")
    root = Path(output_dir).expanduser().resolve()
    if root.exists() and any(root.iterdir()):
        raise ValueError("Prepared output directory must be empty; existing fixture versions are never overwritten")
    root.mkdir(parents=True, exist_ok=True)
    media_root = Path(media_dir).expanduser().resolve()
    fixtures, identities = [], set()
    for item in selection["clips"]:
        identity = item["id"]
        if not isinstance(identity, str) or not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,99}", identity) or identity in identities:
            raise ValueError("Selection IDs must be unique simple names")
        identities.add(identity)
        film = by_id[item["film_id"]]
        directory = media_root / film["id"]
        if directory.is_symlink() or not directory.resolve().is_relative_to(media_root):
            raise ValueError("Source directory leaves the public acquisition root")
        ledger = _existing(directory, film, "youtube")
        if not ledger or ledger.get("youtube", {}).get("video_id") != item["youtube_video_id"]:
            raise ValueError("Download the matching official YouTube edition before preparing this selection")
        source = directory / "source.mp4"
        meta = _metadata(source, settings)
        video = meta["video"]
        fps = float(Fraction(video["avg_frame_rate"]))
        expected = item["source_geometry"]
        if (video["width"], video["height"]) != (expected["width"], expected["height"]) or abs(fps - expected["fps"]) > 0.00001:
            raise ValueError("Downloaded edition geometry or rate differs from the reviewed selection")
        if abs(meta["duration"] - item["source_duration_seconds"]) > 1:
            raise ValueError("Downloaded edition duration changed; review shot boundaries before preparing it")
        if video.get("field_order", "progressive") not in ("progressive", "unknown"):
            raise ValueError("Public model fixture preparation requires a progressive source; no implicit deinterlacing")
        first, count, reference_frame = item["start_frame"], item["frame_count"], item["reference_frame"]
        if any(isinstance(n, bool) or not isinstance(n, int) or n < 0 for n in (first, count, reference_frame)) or not 2 <= count <= 97:
            raise ValueError("Choose 2..97 source frames and a nonnegative held-out reference frame")
        if first <= reference_frame < first + count:
            raise ValueError("Reference frame must lie outside the evaluated source shot")
        start, ref_time = first / fps, reference_frame / fps
        if max(start + count / fps, ref_time) >= meta["duration"]:
            raise ValueError("Selection exceeds the source edition")
        timestamps = _source_timestamps(source, start, count, fps, video["index"], settings)
        ref_pts = _source_timestamps(source, ref_time, 1, fps, video["index"], settings)[0]
        folder = root / identity
        folder.mkdir()
        divisor = item.get("downscale_divisor", 2)
        if divisor not in (1, 2, 4) or video["width"] % divisor or video["height"] % divisor:
            raise ValueError("Downscale divisor must preserve integer frame dimensions")
        width, height = video["width"] // divisor, video["height"] // divisor
        clip = folder / "clip.mp4"
        args = [settings.ffmpeg, "-nostdin", "-y", "-v", "error", "-ss", f"{start:.9f}", "-i", str(source), "-map", f"0:{video['index']}", "-map", "0:a:0?",
                "-vf", f"scale={width}:{height}:flags=lanczos", "-frames:v", str(count), "-t", f"{count/fps:.9f}", "-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv444p", "-c:a", "aac", "-b:a", "192k", "-fps_mode", "passthrough", "-enc_time_base", "1:90000", "-video_track_timescale", "90000", "-movflags", "+faststart", str(clip)]
        run(args, timeout=180)
        prepared = probe(clip, settings)
        if prepared["frame_count"] != count or prepared["is_vfr"] or any(abs(t - (timestamps[i] - timestamps[0])) > 0.001 for i, t in enumerate(prepared["pts"])):
            raise ValueError("Prepared clip failed frame/timestamp integrity checks")
        full_reference = folder / "reference-source-frame.png"
        run([settings.ffmpeg, "-nostdin", "-y", "-v", "error", "-ss", f"{ref_time:.9f}", "-i", str(source), "-map", f"0:{video['index']}", "-frames:v", "1", str(full_reference)], timeout=120)
        x, y, w, h = item["reference_crop"]
        if any(isinstance(v, bool) or not isinstance(v, int) for v in (x, y, w, h)) or min(x, y) < 0 or min(w, h) <= 0 or x + w > video["width"] or y + h > video["height"]:
            raise ValueError("Reference crop must be inside source pixels")
        reference = folder / "reference.png"
        with Image.open(full_reference) as im:
            ImageOps.exif_transpose(im).convert("RGB").crop((x, y, x + w, y + h)).save(reference)
        provenance = {"provider": "youtube", "source_url": ledger["source_url"], "edition": ledger["edition"], "source_sha256": ledger["sha256"],
                      "source_geometry": {"width": video["width"], "height": video["height"], "fps": fps, "sar": video.get("sample_aspect_ratio")},
                      "start_frame": first, "frame_count": count, "reference_frame": reference_frame, "reference_timestamp": ref_pts,
                      "reference_crop": [x, y, w, h], "downscale_divisor": divisor, "preprocessing": "Lanczos downscale only; H.264 CRF18; source soundtrack AAC192k; no denoise/sharpen/deinterlace/interpolation",
                      "source_frame_map": [{"frame": i, "source_frame": first + i, "source_timestamp": t, "output_timestamp": prepared["pts"][i]} for i, t in enumerate(timestamps)],
                      "clip_sha256": sha256(clip), "reference_sha256": sha256(reference), "reference_source_frame_sha256": sha256(full_reference)}
        (folder / "preparation.json").write_text(json.dumps(provenance, indent=2) + "\n")
        fixtures.append({"id": identity, "film_id": film["id"], "title": item["title"], "actor_name": item.get("actor_name", "Public fixture performer"),
                         "reference_view": item.get("reference_view", "front"), "reference_expression": item.get("reference_expression", ""), "reference_lighting": item.get("reference_lighting", ""),
                         "source_url": ledger["source_url"], "rights_url": ledger["rights_url"], "source_sha256": ledger["sha256"],
                         "clip_path": str(clip.relative_to(root)), "clip_sha256": provenance["clip_sha256"],
                         "reference_path": str(reference.relative_to(root)), "reference_sha256": provenance["reference_sha256"],
                         "shot": {"start_time": 0, "end_time": prepared["duration"]}, "placement": item["placement"],
                         "preparation": provenance})
    manifest = {"schema_version": 1, "provider": "youtube", "description": "Reviewed public-film fixtures; source evidence retained in per-clip preparation.json", "fixtures": fixtures}
    (root / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest
