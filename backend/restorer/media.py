from __future__ import annotations

import hashlib
import json
import math
import subprocess
import tempfile
import time
from fractions import Fraction
from pathlib import Path
from typing import Callable

from .config import Settings


class Canceled(RuntimeError):
    pass


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        while block := f.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def run(args: list[str], *, canceled: Callable[[], bool] = lambda: False, log: Callable[[str], None] = lambda _: None, timeout: float = 3600):
    """No shell, bounded wait, no undrained pipe, terminate the owned child only."""
    with tempfile.TemporaryFile(mode="w+b") as output:
        process = subprocess.Popen([str(a) for a in args], stdout=output, stderr=subprocess.STDOUT)
        start = time.monotonic()
        try:
            while process.poll() is None:
                if canceled():
                    raise Canceled("Canceled by user")
                if time.monotonic() - start > timeout:
                    raise RuntimeError(f"Media command exceeded {timeout:g} seconds")
                time.sleep(0.08)
        except BaseException:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
            raise
        output.seek(0, 2)
        size = output.tell()
        output.seek(max(0, size - 24000))
        message = output.read().decode("utf8", errors="replace")
        log(message)
        if process.returncode:
            raise RuntimeError(f"Media command exited {process.returncode}: {message[-3000:]}")


def rational(value: str | None, default=1.0) -> float:
    try:
        return float(Fraction((value or "").replace(":", "/")))
    except (ValueError, ZeroDivisionError):
        return default


def probe(path: Path, settings: Settings, *, frames=True) -> dict:
    args = [settings.ffprobe, "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)]
    result = subprocess.run(args, capture_output=True, text=True, timeout=60, check=True)
    data = json.loads(result.stdout)
    video = next((s for s in data["streams"] if s["codec_type"] == "video" and not s.get("disposition", {}).get("attached_pic")), None)
    if not video:
        raise ValueError("No decodable video stream")
    rotation = float(video.get("tags", {}).get("rotate", 0) or 0)
    for side in video.get("side_data_list", []):
        if "rotation" in side:
            rotation = float(side["rotation"])
    if rotation % 360:
        raise ValueError("Display rotation metadata is unsupported in the first version. Create an explicitly rotated progressive derivative before import; no implicit geometry change is applied.")
    video_index = video["index"]
    fps = rational(video.get("avg_frame_rate"), 0)
    duration = float(video.get("duration", data.get("format", {}).get("duration", 0)))
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError("A finite positive video duration is required")
    if duration * max(fps, 1) > settings.max_frames * 1.5:
        raise ValueError(f"Source exceeds first-version limit ({settings.max_frames} frames); import a shorter clip")
    sar = rational(video.get("sample_aspect_ratio"))
    pts, durations, interlaced = [], [], set()
    if frames:
        result = subprocess.run([settings.ffprobe, "-v", "error", "-select_streams", str(video_index), "-show_frames", "-show_entries", "frame=best_effort_timestamp_time,duration_time,pkt_duration_time,interlaced_frame,top_field_first", "-of", "json", str(path)], capture_output=True, text=True, timeout=180, check=True)
        for frame in json.loads(result.stdout).get("frames", []):
            if "best_effort_timestamp_time" not in frame:
                raise ValueError("Video has a frame without a timestamp; repair timestamps explicitly before import")
            pts.append(float(frame["best_effort_timestamp_time"]))
            durations.append(float(frame.get("duration_time", frame.get("pkt_duration_time", 1 / max(fps, 1)))))
            interlaced.add(bool(frame.get("interlaced_frame", 0)))
        if not pts or len(pts) > settings.max_frames:
            raise ValueError(f"Source must contain 1..{settings.max_frames} frames")
        if any(b <= a for a, b in zip(pts, pts[1:])):
            raise ValueError("Non-increasing frame timestamps are unsupported; no implicit timestamp repair is applied")
    first = pts[0] if pts else float(video.get("start_time", 0))
    normalized = [round(p - first, 9) for p in pts]
    if pts:
        duration = normalized[-1] + (durations[-1] if durations[-1] > 0 else 1 / max(fps, 1))
    deltas = [b - a for a, b in zip(normalized, normalized[1:])]
    is_vfr = bool(deltas and max(deltas) - min(deltas) > max(0.0001, 0.01 / max(fps, 1)))
    return {"video_stream_index": video_index, "width": video["width"], "height": video["height"], "display_width": video["width"] * sar,
            "sar": sar, "duration": duration, "fps": fps, "is_vfr": is_vfr,
            "frame_count": len(pts) if frames else int(video.get("nb_frames", 0) or 0),
            "pts": normalized, "raw_pts": pts, "frame_durations": durations,
            "first_pts": first, "format_start_time": float(data.get("format", {}).get("start_time", 0)),
            "has_audio": any(s["codec_type"] == "audio" for s in data["streams"]),
            "interlaced": any(interlaced) or video.get("field_order", "unknown") not in ("progressive", "unknown"),
            "metadata": {"video": video, "audio": [s for s in data["streams"] if s["codec_type"] == "audio"], "format": data.get("format", {})}}


def shot_mapping(source: dict, start: float, end: float) -> dict:
    import bisect
    if end > source["duration"] + 0.0001:
        raise ValueError("Shot end exceeds source duration")
    pts = source["pts"]
    first = bisect.bisect_left(pts, start - 1e-8)
    stop = bisect.bisect_left(pts, end - 1e-8)
    if first >= stop:
        raise ValueError("Shot must contain at least one frame")
    actual_end = pts[stop] if stop < len(pts) else source["duration"]
    return {"frame_start": first, "frame_end": stop, "start_time": pts[first], "end_time": actual_end,
            "requested_start_time": start, "requested_end_time": end, "duration": actual_end - pts[first],
            "frame_count": stop - first, "frame_map": [{"frame": i - first, "source_frame": i,
            "source_timestamp": pts[i], "source_pts": source["raw_pts"][i],
            "output_timestamp": round(pts[i] - pts[first], 9)} for i in range(first, stop)]}


def extract_frame(source_path: Path, output: Path, frame: int, settings: Settings, stream_index: int = 0):
    run([settings.ffmpeg, "-nostdin", "-y", "-v", "error", "-i", str(source_path), "-map", f"0:{stream_index}", "-vf", f"select=eq(n\\,{frame})", "-frames:v", "1", "-update", "1", str(output)], timeout=120)
    if not output.is_file():
        raise ValueError("Frame not available")


def render_clip(source_path: Path, source: dict, shot: dict, output: Path, settings: Settings, scale=1, canceled=lambda: False, log=lambda _: None):
    w, h = source["width"] * scale, source["height"] * scale
    interlaced = source.get("interlaced", False)
    field_order = source.get("metadata", {}).get("video", {}).get("field_order", "unknown")
    field_name = "tff" if field_order in ("tt", "bt") else "bff"
    if interlaced and (field_order not in ("tt", "bt", "bb", "tb") or h % 4):
        raise ValueError("Interlaced baseline requires a known display field order and an output height divisible by four. Import an explicitly prepared derivative; no implicit deinterlacing is applied.")
    # yuv444p permits odd source dimensions; the source SAR is preserved rather than stretched.
    scaling = f"scale={w}:{h}:flags=lanczos" + (":interl=1" if interlaced else "")
    vf = f"trim=start_frame={shot['frame_start']}:end_frame={shot['frame_end']},setpts=PTS-STARTPTS,{scaling},setsar={source['sar']}"
    if interlaced:
        vf += f",setfield={field_name}"
    video_index = source.get("video_stream_index", source["metadata"]["video"]["index"])
    args = [settings.ffmpeg, "-nostdin", "-y", "-v", "warning", "-i", str(source_path), "-map", f"0:{video_index}", "-vf", vf]
    if source["has_audio"]:
        audio_start = source["first_pts"] - source["format_start_time"] + shot["start_time"]
        audio_end = audio_start + shot["duration"]
        args += ["-map", "0:a:0", "-af", f"atrim=start={audio_start:.9f}:end={audio_end:.9f},asetpts=PTS-{audio_start:.9f}/TB", "-c:a", "aac", "-b:a", "192k"]
    args += ["-c:v", "libx264", "-preset", "fast", "-crf", "17", "-pix_fmt", "yuv444p"]
    if interlaced:
        args += ["-flags", "+ilme+ildct", "-x264-params", f"{field_name}=1"]
    args += ["-fps_mode", "passthrough", "-enc_time_base", "1:90000", "-video_track_timescale", "90000", "-t", f"{shot['duration']:.9f}", "-movflags", "+faststart", str(output)]
    run(args, canceled=canceled, log=log)


def prepare_ltx(source_clip: Path, source: dict, shot: dict, output: Path, transform: dict, padded_frames: int, settings: Settings, canceled=lambda: False, log=lambda _: None):
    t = transform
    vf = f"scale={t['content_width']}:{t['content_height']}:flags=lanczos,setsar=1,pad={t['width']}:{t['height']}:{t['pad_x']}:{t['pad_y']}:color=gray,tpad=stop_mode=clone:stop={padded_frames-shot['frame_count']}"
    run([settings.ffmpeg, "-nostdin", "-y", "-v", "warning", "-i", str(source_clip), "-an", "-vf", vf, "-frames:v", str(padded_frames), "-c:v", "libx264", "-crf", "12", "-pix_fmt", "yuv444p", "-fps_mode", "passthrough", str(output)], canceled=canceled, log=log)


def export_ltx(raw: Path, source_clip: Path, output: Path, shot: dict, transform: dict, source: dict, settings: Settings, canceled=lambda: False, log=lambda _: None):
    t = transform
    vf = f"trim=end_frame={shot['frame_count']},setpts=PTS-STARTPTS,crop=w={t['content_width']}:h={t['content_height']}:x={t['pad_x']}:y={t['pad_y']}:exact=1,setsar=1"
    args = [settings.ffmpeg, "-nostdin", "-y", "-v", "warning", "-i", str(raw), "-i", str(source_clip), "-map", "0:v:0", "-map", "1:a:0?", "-vf", vf, "-c:v", "libx264", "-crf", "17", "-pix_fmt", "yuv444p", "-c:a", "copy", "-fps_mode", "passthrough", "-t", str(shot["duration"]), "-movflags", "+faststart", str(output)]
    run(args, canceled=canceled, log=log)


def integrity(output: dict, source: dict, shot: dict) -> dict:
    expected = [f["output_timestamp"] for f in shot["frame_map"]]
    actual = output["pts"]
    drift = max((abs(a - b) for a, b in zip(expected, actual)), default=0)
    duration_delta = output["duration"] - shot["duration"]
    return {"expected_frames": len(expected), "actual_frames": len(actual), "max_timestamp_delta": drift,
            "duration_delta": duration_delta, "audio_expected": source["has_audio"], "audio_present": output["has_audio"],
            "timing_passed": len(expected) == len(actual) and drift < 0.002 and abs(duration_delta) < max(0.003, 1 / max(source["fps"], 1)),
            "subjective_quality": "unreviewed", "audio_policy": "Source first audio stream retained; AAC transcode for baseline, never generated audio"}
