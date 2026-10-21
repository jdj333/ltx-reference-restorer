"""Geometry and artifact tests use real Pillow images, no renderer mocks."""

import pytest
from PIL import Image

from restorer.guides import (
    interpolate,
    inverse_box,
    make_guide,
    rank_references,
    static_placement,
    transform_box,
    validate_setup,
    working_transform,
)


def test_non_square_pixels_and_padding_roundtrip():
    source = {"width": 320, "height": 241, "sar": 1.2}
    transform = working_transform(source, 2)
    assert transform["content_width"] / transform["content_height"] == pytest.approx(320 * 1.2 / 241)
    assert transform["width"] % 32 == transform["height"] % 32 == 0
    assert transform["pad_y"] > 0
    region = {"x": 31.25, "y": 18.75, "width": 71.5, "height": 99.25}
    assert inverse_box(transform_box(region, transform), transform) == pytest.approx(region)


def test_guide_places_native_reference_at_transformed_center_without_resize(tmp_path):
    reference = tmp_path / "reference.png"
    output = tmp_path / "guide.png"
    Image.new("RGB", (20, 10), (230, 30, 15)).save(reference)
    transform = working_transform({"width": 101, "height": 81, "sar": 1}, 1)
    metadata = make_guide(reference, output, {"x": 20, "y": 20, "width": 40, "height": 40}, transform)
    content = metadata["reference_content_box"]
    assert content["width"] == 20 and content["height"] == 10
    assert content["x"] == transform["pad_x"] + 30
    assert content["y"] == transform["pad_y"] + 35
    assert metadata["reference_resize"].startswith("none")
    with Image.open(output) as guide:
        assert guide.size == (transform["width"], transform["height"])
        assert guide.getpixel((0, 0)) == (128, 128, 128)
        assert guide.getpixel((content["x"] + 10, content["y"] + 5)) == (230, 30, 15)
        assert guide.getpixel((content["x"], content["y"] - 1)) == (128, 128, 128)


def test_guide_rejects_native_crop_that_would_leave_canvas(tmp_path):
    reference = tmp_path / "large.png"
    Image.new("RGB", (400, 400), (230, 30, 15)).save(reference)
    transform = working_transform({"width": 100, "height": 100, "sar": 1}, 1)
    with pytest.raises(ValueError, match="Native reference crop"):
        make_guide(reference, tmp_path / "guide.png", {"x": 10, "y": 10, "width": 20, "height": 20}, transform)
    assert not (tmp_path / "guide.png").exists()


def test_placement_interpolation_bounds_and_static_backend_guard():
    keys = [
        {"frame": 10, "x": 40, "y": 20, "width": 30, "height": 40},
        {"frame": 0, "x": 20, "y": 10, "width": 20, "height": 30},
    ]
    assert interpolate(keys, 5) == {"frame": 5, "x": 30, "y": 15, "width": 25, "height": 35}
    assert interpolate(keys, 5, "hold")["x"] == 20
    assert interpolate(keys, 20)["x"] == 40
    assert interpolate(keys, 0)["x"] == 20
    setup = {"keyframes": keys, "interpolation": "linear"}
    with pytest.raises(ValueError, match="Moving reference"):
        static_placement(setup)
    assert static_placement({**setup, "keyframes": [keys[1]]})["x"] == 20
    with pytest.raises(ValueError, match="unique"):
        validate_setup({"keyframes": [keys[1], keys[1]]}, {"width": 100, "height": 100}, {"frame_count": 11})
    with pytest.raises(ValueError, match="beyond"):
        validate_setup({"keyframes": [{**keys[1], "x": 90}]}, {"width": 100, "height": 100}, {"frame_count": 11})


def test_reference_ranking_is_stable_explainable_and_retains_generated_label():
    refs = [
        {"id": "b", "approval_status": "approved", "quality": 3, "view": "front", "provenance": "original_footage"},
        {"id": "a", "approval_status": "approved", "quality": 3, "view": "front", "provenance": "generated_reconstruction"},
        {"id": "pending", "approval_status": "pending", "quality": 5, "view": "front", "provenance": "external_photograph"},
        {"id": "rejected", "approval_status": "rejected", "quality": 5, "view": "front", "provenance": "external_photograph"},
        {"id": "angle", "approval_status": "approved", "quality": 3, "view": "profile", "provenance": "original_footage"},
    ]
    ranked = rank_references(refs, "front")
    assert [r["id"] for r in ranked] == ["a", "b", "angle", "pending", "rejected"]
    assert [r["id"] for r in rank_references(list(reversed(refs)), "front")] == [r["id"] for r in ranked]
    assert ranked[0]["provenance"] == "generated_reconstruction"
    assert "Approved" in ranked[0]["rank_reason"] and "matching" in ranked[0]["rank_reason"]
