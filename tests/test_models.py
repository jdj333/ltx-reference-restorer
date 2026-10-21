"""Metadata, scoped filesystem access and explicitly isolated doctor mocks."""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from restorer import doctor
from restorer.config import Settings
from restorer.schemas import JobInput, ReferenceInput, ReferencePatch
from restorer.store import Store


def test_reference_approval_and_provenance_persist_across_reopen(tmp_path):
    store = Store(tmp_path)
    project = store.create("project", {"name": "Synthetic restoration"})
    actor = store.create("actor", {"name": "Synthetic actor"}, project["id"])
    ref = store.create("reference", {
        **ReferenceInput(path="fixture.png", provenance="generated_reconstruction", view="three_quarter", quality=4.5,
                         expression="neutral", lighting="soft front light").model_dump(),
        "actor_id": actor["id"], "sha256": "b" * 64, "crop": [4, 8, 20, 30],
        "source_file": "synthetic.mp4", "timestamp": 0.25,
    }, project["id"])
    store.update("reference", ref["id"], ReferencePatch(approval_status="approved", notes="Manually checked").model_dump(exclude_none=True))
    reopened = Store(tmp_path).get("reference", ref["id"])
    assert reopened["approval_status"] == "approved"
    assert reopened["provenance"] == "generated_reconstruction"
    assert reopened["sha256"] == "b" * 64 and reopened["crop"] == [4, 8, 20, 30]
    assert reopened["expression"] == "neutral" and reopened["lighting"] == "soft front light"
    assert Store(tmp_path).list("reference", project["id"])[0]["id"] == ref["id"]


@pytest.mark.parametrize("value", [
    {"quality": 5.1}, {"quality": float("nan")}, {"quality": float("inf")},
    {"approval_status": "automatically_authoritative"}, {"provenance": "unknown"},
    {"view": "identity_lock"}, {"unknown_setting": True},
])
def test_reference_rejects_invalid_metadata(value):
    with pytest.raises(ValidationError):
        ReferenceInput(**value)


def test_request_controls_cannot_invent_identity_lock_or_backend():
    with pytest.raises(ValidationError):
        JobInput(identity_lock=100)
    with pytest.raises(ValidationError):
        JobInput(backend="ingredients")


def test_scoped_paths_reject_traversal_and_symlink_escape(tmp_path):
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("private")
    inside = allowed / "inside.txt"
    inside.write_text("approved import")
    alias = allowed / "alias.txt"
    alias.symlink_to(outside)
    data_dir = tmp_path / "data"
    settings = Settings(data_dir=data_dir, import_roots=(allowed,))
    settings.initialize()
    assert settings.import_path(str(inside)) == inside
    for path in (outside, alias, allowed / ".." / "outside.txt"):
        with pytest.raises(ValueError, match="import_roots"):
            settings.import_path(str(path))
    with pytest.raises(ValueError, match="leaves"):
        settings.asset_path("../outside.txt")
    (data_dir / "escape").symlink_to(allowed, target_is_directory=True)
    with pytest.raises(ValueError, match="leaves"):
        settings.asset_path("escape/inside.txt")


def test_doctor_does_not_enable_mlx_from_installation_or_memory(tmp_path, monkeypatch):
    # Isolated preflight mocks; this does not exercise model inference or ComfyUI.
    monkeypatch.setattr(doctor, "_tool", lambda _: {"available": True, "version": "test fixture"})
    monkeypatch.setattr(doctor, "_comfy", lambda _: {"connected": False, "ready": False})
    monkeypatch.setattr(doctor, "_installed", lambda _: "0.17.0")
    result = doctor.report(Settings(data_dir=tmp_path / "not-created"))
    assert result["backends"]["baseline"]["label"] == "baseline upscale"
    assert result["backends"]["mlx"]["available"] is False
    assert result["backends"]["mlx"]["operations"] == []
    assert "stage_2_ic_lora" in result["backends"]["mlx"]["reason"]
    assert result["memory"]["available_bytes"] > 0 and result["disk"]["free_bytes"] > 0
    assert not (tmp_path / "not-created").exists()
    json.dumps(result)


def test_doctor_checks_workflow_node_and_model_inventory(tmp_path):
    # object_info fixture isolates discovery; no running ComfyUI is claimed.
    path = tmp_path / "workflow.json"
    path.write_text(json.dumps({"prompt": {"1": {"class_type": "ModelLoader", "inputs": {"ckpt_name": "missing.safetensors"}}}}))
    nodes = {"ModelLoader": {"input": {"required": {"ckpt_name": [["installed.safetensors"]]}}}}
    result = doctor._workflow(path, nodes)
    assert not result["available"]
    assert result["selected_models"][0]["advertised"] is False
    assert doctor._workflow(path, {})["missing_nodes"] == ["ModelLoader"]


@pytest.mark.parametrize("contents", ["[]", "{\"prompt\": []}", "not json"])
def test_doctor_reports_malformed_workflow_without_crashing(tmp_path, contents):
    path = tmp_path / "bad.json"
    path.write_text(contents)
    result = doctor._workflow(path, {})
    assert not result["available"]
    assert result["error"]


@pytest.mark.parametrize("url", ["http://[invalid", "http://localhost:invalid", "http://user:secret@localhost", "http://localhost/?token=secret"])
def test_doctor_reports_invalid_backend_without_exposing_credentials(tmp_path, url):
    result = doctor._comfy(Settings(data_dir=tmp_path, comfy_url=url))
    assert not result["connected"]
    assert result["error"]
    assert "secret" not in json.dumps(result)
