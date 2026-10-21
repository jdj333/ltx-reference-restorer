from __future__ import annotations

import math
from pathlib import Path
from PIL import Image, ImageOps


def working_transform(source: dict, scale: int = 2) -> dict:
    width = max(1, round(source["width"] * source["sar"] * scale))
    height = source["height"] * scale
    padded_width = max(64, math.ceil(width / 32) * 32)
    padded_height = max(64, math.ceil(height / 32) * 32)
    return {"source_width": source["width"], "source_height": source["height"], "source_sar": source["sar"],
            "content_width": width, "content_height": height, "width": padded_width, "height": padded_height,
            "scale_x": width / source["width"], "scale_y": height / source["height"],
            "pad_x": (padded_width - width) // 2, "pad_y": (padded_height - height) // 2,
            "description": "Source pixels → square-pixel display geometry → scale → centered gray padding. No stretch."}


def transform_box(box: dict, transform: dict) -> dict:
    return {"x": box["x"] * transform["scale_x"] + transform["pad_x"],
            "y": box["y"] * transform["scale_y"] + transform["pad_y"],
            "width": box["width"] * transform["scale_x"], "height": box["height"] * transform["scale_y"]}


def inverse_box(box: dict, transform: dict) -> dict:
    return {"x": (box["x"] - transform["pad_x"]) / transform["scale_x"],
            "y": (box["y"] - transform["pad_y"]) / transform["scale_y"],
            "width": box["width"] / transform["scale_x"], "height": box["height"] / transform["scale_y"]}


def interpolate(keyframes: list[dict], frame: int, mode="linear") -> dict:
    if not keyframes:
        raise ValueError("Draw a face region first")
    keys = sorted(keyframes, key=lambda k: k["frame"])
    left = next((k for k in reversed(keys) if k["frame"] <= frame), keys[0])
    right = next((k for k in keys if k["frame"] >= frame), keys[-1])
    amount = 0 if mode == "hold" or right["frame"] == left["frame"] else (frame - left["frame"]) / (right["frame"] - left["frame"])
    return {"frame": frame, **{k: left[k] + (right[k] - left[k]) * amount for k in ("x", "y", "width", "height")}}


def validate_setup(setup: dict, source: dict, shot: dict):
    frames = set()
    for key in setup["keyframes"]:
        if key["frame"] >= shot["frame_count"] or key["frame"] in frames:
            raise ValueError("Placement frames must be unique and inside the shot")
        frames.add(key["frame"])
        if key["x"] + key["width"] > source["width"] + 0.01 or key["y"] + key["height"] > source["height"] + 0.01:
            raise ValueError("Face region extends beyond source pixels")


def static_placement(setup: dict) -> dict:
    box = interpolate(setup["keyframes"], 0, setup["interpolation"])
    if any(any(abs(k[n] - box[n]) > 0.01 for n in ("x", "y", "width", "height")) for k in setup["keyframes"]):
        raise ValueError("Moving reference conditioning is unavailable. Use a short shot with a static face region; keyframe interpolation is available for review only.")
    return box


def make_guide(reference_path: Path, output: Path, box: dict, transform: dict) -> dict:
    placed = transform_box(box, transform)
    canvas = Image.new("RGB", (transform["width"], transform["height"]), (128, 128, 128))
    with Image.open(reference_path) as ref:
        image = ImageOps.exif_transpose(ref).convert("RGB")
        # Upstream asks for native-resolution reference crops. The drawn region
        # supplies a center, not a request to warp or resize the reference face.
        fitted = image
        x = round(placed["x"] + placed["width"] / 2 - fitted.width / 2)
        y = round(placed["y"] + placed["height"] / 2 - fitted.height / 2)
        if x < 0 or y < 0 or x + fitted.width > canvas.width or y + fitted.height > canvas.height:
            raise ValueError("Native reference crop would leave the working canvas. Import a smaller source crop or adjust placement; no implicit resizing is applied.")
        canvas.paste(fitted, (x, y))
    canvas.save(output)
    return {"placement": placed, "reference_content_box": {"x": x, "y": y, "width": fitted.width, "height": fitted.height},
            "transforms": transform, "background_rgb": [128, 128, 128],
            "reference_resize": "none; native-resolution crop centered on the selected face region"}


def rank_references(references: list[dict], view="front") -> list[dict]:
    ranked = []
    for ref in references:
        approved = ref["approval_status"] == "approved"
        compatible = ref["view"] == view
        score = (100 if approved else -100 if ref["approval_status"] == "rejected" else 0) + ref["quality"] * 5 + (10 if compatible else 0)
        ranked.append({**ref, "rank_score": score, "rank_reason": f"{'Approved' if approved else ref['approval_status']}; quality {ref['quality']}/5; {'matching' if compatible else 'different'} view. Generated provenance is retained."})
    return sorted(ranked, key=lambda r: (-r["rank_score"], r["id"]))
