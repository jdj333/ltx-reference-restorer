"""Isolated ComfyUI tests use mocked transport; no models or inference are exercised."""

import copy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from restorer.backends.comfy import ComfyBackend, ComfyCanceled, ComfyClient, ComfyError, WorkflowBundle


WORKFLOWS = Path(__file__).resolve().parents[1] / "workflows"


@pytest.fixture
def bundle():
    return WorkflowBundle.load(WORKFLOWS / "ltx25-restore.json")


@pytest.fixture
def node_schemas():
    # This is an isolated contract fixture based on inspected Comfy core/custom
    # node source, not an assertion that these nodes are installed on this host.
    layouts = {
        "UNETLoader": ({"unet_name": ["ltx-2.5-22b-distilled-transformer-bf16.safetensors"], "weight_dtype": ["default"]}, ["MODEL"]),
        "CLIPLoader": ({"clip_name": ["gemma4-12b-with-proj-ltx-2.5-bf16.safetensors"], "type": ["ltxv"], "device": ["default", "cpu"]}, ["CLIP"]),
        "VAELoader": ({"vae_name": ["ltx-2.5-video-vae-bf16.safetensors"]}, ["VAE"]),
        "LTXICLoRALoaderModelOnly": ({"model": "MODEL", "lora_name": ["ltx-2.5-22b-ic-lora-restore-1.0.safetensors", "ltx-2.5-22b-ic-lora-refine-details-1.0.safetensors"], "strength_model": "FLOAT"}, ["MODEL", "FLOAT"]),
        "CLIPTextEncode": ({"text": "STRING", "clip": "CLIP"}, ["CONDITIONING"]),
        "LTXVConditioning": ({"positive": "CONDITIONING", "negative": "CONDITIONING", "frame_rate": "FLOAT"}, ["CONDITIONING", "CONDITIONING"]),
        "LoadVideo": ({"file": []}, ["VIDEO"]),
        "GetVideoComponents": ({"video": "VIDEO"}, ["IMAGE", "AUDIO", "FLOAT", "COMBO", "COMBO"]),
        "LTXAddVideoICLoRAGuide": ({"positive": "CONDITIONING", "negative": "CONDITIONING", "vae": "VAE", "latent": "LATENT", "image": "IMAGE", "frame_idx": "INT", "strength": "FLOAT", "latent_downscale_factor": "FLOAT", "crop": ["disabled", "center"], "use_tiled_encode": "BOOLEAN", "tile_size": "INT", "tile_overlap": "INT", "use_streaming": "BOOLEAN", "tile_frames": "INT"}, ["CONDITIONING", "CONDITIONING", "LATENT"]),
        "LoadImage": ({"image": []}, ["IMAGE", "MASK"]),
        "EmptyLTXVLatentVideo": ({"width": "INT", "height": "INT", "length": "INT", "batch_size": "INT"}, ["LATENT"]),
        "ManualSigmas": ({"sigmas": "STRING"}, ["SIGMAS"]),
        "KSamplerSelect": ({"sampler_name": ["euler"]}, ["SAMPLER"]),
        "LTXVTiledFusionSampler": ({"model": "MODEL", "positive": "CONDITIONING", "negative": "CONDITIONING", "latents": "LATENT", "sigmas": "SIGMAS", "sampler": "SAMPLER", "seed": "INT", "cfg": "FLOAT", "tile_width": "INT", "tile_height": "INT", "overlap_frac": "FLOAT", "blend_var": "FLOAT", "grid_cycle": "INT", "tile_frames": "INT", "vae": "VAE", "canvas_device": ["auto", "cpu", "gpu"]}, ["LATENT"]),
        "VAEDecodeTiled": ({"samples": "LATENT", "vae": "VAE", "tile_size": "INT", "overlap": "INT", "temporal_size": "INT", "temporal_overlap": "INT"}, ["IMAGE"]),
        "CreateVideo": ({"images": "IMAGE", "fps": "FLOAT", "bit_depth": ["auto", 8, 10], "color_space": ["sRGB", "HDR"], "codec": ["none", "auto"]}, ["VIDEO"]),
        "SaveVideo": ({"video": "VIDEO", "filename_prefix": "STRING", "format": ["auto", "mp4", "mkv", "webm"]}, ["VIDEO"]),
    }
    schemas = {kind: {"input": {"required": {name: [type_] for name, type_ in inputs.items()}}, "output": outputs} for kind, (inputs, outputs) in layouts.items()}
    schemas["SaveVideo"]["input"]["required"]["format"] = ["COMFY_DYNAMICCOMBO_V3", {"options": [{"key": "auto", "inputs": {"required": {"codec": ["COMFY_DYNAMICCOMBO_V3", {"options": [{"key": "auto", "inputs": {}}]}]}}}]}]
    return schemas


def test_shipped_api_graphs_and_reference_difference(bundle, node_schemas):
    assert bundle.validate(node_schemas) == []
    refine = WorkflowBundle.load(WORKFLOWS / "ltx25-refine.json")
    assert refine.validate(node_schemas) == []
    values = {"source_video": "actual-source.mp4", "guide_image": "actual-guide.png", "prompt": "same prompt", "seed": 883, "width": 960, "height": 544, "frame_count": 49, "fps": 24.0}
    b = bundle.mapped(values, use_references=False)
    c = bundle.mapped(values, use_references=True)
    assert set(c) - set(b) == {"11", "12"}
    assert c["12"]["inputs"]["frame_idx"] == -1
    assert b["15"]["inputs"]["positive"] == ["10", 0]
    assert c["15"]["inputs"]["positive"] == ["12", 0]
    for node in set(b) - {"15"}:
        assert b[node] == c[node]
    for field in ("seed", "cfg", "sigmas", "model", "tile_width", "tile_height"):
        assert b["15"]["inputs"][field] == c["15"]["inputs"][field]
    assert c["8"]["inputs"]["file"] == "actual-source.mp4"
    assert c["11"]["inputs"]["image"] == "actual-guide.png"
    assert c["13"]["inputs"]["length"] == 49
    assert bundle.prompt["8"]["inputs"]["file"] == "source-upload.mp4"


@pytest.mark.parametrize("change", ["streaming", "wrong_reference", "ingredients", "i2v", "wrong_binding", "fake_sampling_steps", "fake_seed_control"])
def test_reject_unverified_semantics(bundle, change):
    data = copy.deepcopy(bundle.data)
    if change == "streaming":
        data["prompt"]["12"]["inputs"]["use_streaming"] = True
    elif change == "wrong_reference":
        data["prompt"]["12"]["inputs"]["frame_idx"] = 48
    elif change == "ingredients":
        data["prompt"]["4"]["inputs"]["lora_name"] = "ltx-2.5-22b-ic-lora-ingredients-0.9.safetensors"
    elif change == "i2v":
        data["prompt"]["10"]["class_type"] = "LTXVImgToVideo"
    elif change == "wrong_binding":
        data["bindings"]["seed"] = ["absent", "fake_seed"]
    elif change == "fake_sampling_steps":
        data["prompt"]["14"]["inputs"]["sigmas"] = "1,0"
    else:
        data["bindings"]["seed"] = ["13", "length"]
    with pytest.raises(ComfyError):
        WorkflowBundle(data)


def test_missing_node_model_and_output_slot_block_submission(bundle, node_schemas):
    schemas = copy.deepcopy(node_schemas)
    schemas.pop("LTXVTiledFusionSampler")
    assert any("Missing ComfyUI node" in e for e in bundle.validate(schemas))
    schemas = copy.deepcopy(node_schemas)
    schemas["UNETLoader"]["input"]["required"]["unet_name"] = [[]]
    assert any("model file or option missing" in e for e in bundle.validate(schemas))
    graph = bundle.mapped({}, use_references=False)
    graph["17"]["inputs"]["samples"] = ["15", 8]
    assert any("invalid linked output slot" in e for e in bundle.validate(node_schemas, graph))
    graph = bundle.mapped({}, use_references=False)
    graph["19"]["inputs"].pop("format.codec")
    assert any("format.codec" in e and "required" in e for e in bundle.validate(node_schemas, graph))


class MockComfy:
    """Transport mock. Returned bytes are intentionally not a playable video."""
    def __init__(self, schemas, mode="success"):
        self.url = "http://localhost:8188"
        self.schemas = schemas
        self.mode = mode
        self.calls = []
        self.was_submitted = False
        self.remote_running = []

    def object_info(self):
        return self.schemas

    def system_stats(self):
        return {"system": {"comfyui_version": "mock-contract-only"}, "devices": []}

    def upload(self, path):
        self.calls.append(("upload", str(path)))
        return path.name

    def request(self, path, data=None, **kwargs):
        self.calls.append((path, data))
        if path == "/prompt":
            self.was_submitted = True
            if self.mode == "rejected":
                return {"error": "invalid_prompt", "node_errors": {}}
            return {"prompt_id": "owned-prompt-id", "node_errors": {}}
        if path.startswith("/history/"):
            if self.mode == "failed":
                return {"owned-prompt-id": {"status": {"status_str": "error", "messages": [["execution_error", {"exception_message": "out of memory"}]]}}}
            return {"owned-prompt-id": {"status": {"completed": True, "status_str": "success"}, "outputs": {"19": {"videos": [{"filename": "mock-only.mp4", "type": "output"}]}}}}
        if path.startswith("/view?"):
            return b"mock-only-not-inference"
        if path == "/queue":
            return {"queue_running": self.remote_running, "queue_pending": []}
        raise AssertionError(path)

    def cancel(self, prompt_id):
        self.calls.append(("cancel", prompt_id))
        return True


def render_case(tmp_path, bundle, node_schemas, mode="success"):
    settings = SimpleNamespace(comfy_url="http://localhost:8188", comfy_workflow=None, comfy_timeout=60)
    backend = ComfyBackend(settings)
    backend.client = MockComfy(node_schemas, mode)
    spec = {"workflow_snapshot": bundle.data, "workflow_sha256": "recorded-original-file-hash", "backend": "comfy_restore", "source_clip": tmp_path / "source.mp4", "guide_path": tmp_path / "guide.png", "frame_count": 49, "width": 960, "height": 544, "fps": 24, "seed": 42, "cfg": 1, "steps": 8, "prompt": "retain performance", "use_references": True}
    return backend, spec


def test_mock_render_uses_snapshot_and_saves_provenance(tmp_path, bundle, node_schemas):
    backend, spec = render_case(tmp_path, bundle, node_schemas)
    output = backend.render(spec, tmp_path / "attempt", lambda _: None, lambda: False)
    assert output.read_bytes() == b"mock-only-not-inference"
    graph = json.loads((output.parent / "workflow-api.json").read_text())
    assert graph["8"]["inputs"]["file"] == "source.mp4"
    evidence = json.loads((output.parent / "comfy-integration.json").read_text())
    assert evidence["render_executed"] is True
    assert evidence["source_bundle_file_sha256"] == "recorded-original-file-hash"
    assert evidence["api_graph_sha256"]
    assert evidence["models"][0]["hash_status"] == "not exposed by ComfyUI object_info"


@pytest.mark.parametrize("mode", ["failed", "rejected"])
def test_mock_failure_never_returns_output(tmp_path, bundle, node_schemas, mode):
    backend, spec = render_case(tmp_path, bundle, node_schemas, mode)
    with pytest.raises(ComfyError, match="execution failed|rejected"):
        backend.render(spec, tmp_path / "attempt", lambda _: None, lambda: False)
    assert not list((tmp_path / "attempt").glob("comfy-render*"))


def test_mock_cancellation_is_prompt_scoped(tmp_path, bundle, node_schemas):
    backend, spec = render_case(tmp_path, bundle, node_schemas)
    with pytest.raises(ComfyCanceled):
        backend.render(spec, tmp_path / "attempt", lambda _: None, lambda: backend.client.was_submitted)
    assert ("cancel", "owned-prompt-id") in backend.client.calls
    assert not any("/interrupt" in call[0] for call in backend.client.calls)
    integration = json.loads((tmp_path / "attempt" / "comfy-integration.json").read_text())
    assert integration["remote_cancellation_confirmed"] is True
    assert integration["prompt_id"] == "owned-prompt-id"


def test_legacy_cancel_never_global_interrupt(monkeypatch):
    client = ComfyClient("http://localhost:8188")
    calls = []
    def request(path, data=None):
        calls.append((path, data))
        if path.startswith("/api/jobs/"):
            raise ComfyError("ComfyUI HTTP 404")
        return {}
    monkeypatch.setattr(client, "request", request)
    assert client.cancel("my-owned-id") is False
    assert calls == [("/api/jobs/my-owned-id/cancel", {}), ("/queue", {"delete": ["my-owned-id"]})]


def test_targeted_cancel_route(monkeypatch):
    client = ComfyClient("http://localhost:8188")
    calls = []
    monkeypatch.setattr(client, "request", lambda path, data: calls.append((path, data)) or {"cancelled": True})
    assert client.cancel("my-owned-id") is True
    assert calls == [("/api/jobs/my-owned-id/cancel", {})]


def test_reject_constraints_before_network(tmp_path, bundle, node_schemas):
    backend, spec = render_case(tmp_path, bundle, node_schemas)
    spec["frame_count"] = 98
    with pytest.raises(ComfyError, match="8n\\+1"):
        backend.render(spec, tmp_path / "attempt", lambda _: None, lambda: False)
    assert backend.client.calls == []


def test_upload_sends_real_video_bytes_to_input_route(tmp_path, monkeypatch):
    client = ComfyClient("http://localhost:8188")
    source = tmp_path / "prepared.mp4"
    source.write_bytes(b"local-prepared-source-bytes")
    sent = []
    def opened(request, **kwargs):
        sent.append(request)
        return {"name": "stored.mp4", "subfolder": "", "type": "input"}
    monkeypatch.setattr(client, "_open", opened)
    assert client.upload(source) == "stored.mp4"
    assert sent[0].full_url == "http://localhost:8188/upload/image"
    assert b'form-data; name="image"; filename=' in sent[0].data
    assert b"Content-Type: video/mp4" in sent[0].data
    assert b"local-prepared-source-bytes" in sent[0].data
    assert b'form-data; name="type"\r\n\r\ninput' in sent[0].data


def test_missing_configuration_reports_exact_blocker():
    backend = ComfyBackend(SimpleNamespace(comfy_url="http://localhost:8188", comfy_workflow=None, comfy_timeout=60))
    capability = backend.capability()
    assert capability["available"] is False
    assert capability["inference_tested"] is False
    assert "Configure an API workflow bundle" in capability["blockers"][0]


def prior_prompt(tmp_path):
    path = tmp_path / "previous-canceled-job" / "comfy-integration.json"
    path.parent.mkdir()
    path.write_text(json.dumps({"server_url": "http://localhost:8188", "prompt_id": "old-owned-id", "remote_cancel_requested": True, "remote_cancellation_confirmed": False, "remote_terminal_confirmed": False}))
    return path


def test_remote_prior_render_blocks_duplicate_retry(tmp_path, bundle, node_schemas):
    previous = prior_prompt(tmp_path)
    backend, spec = render_case(tmp_path, bundle, node_schemas)
    backend.client.remote_running = [[0, "old-owned-id", {}, {}, []]]
    with pytest.raises(ComfyError, match="old-owned-id.*still running"):
        backend.render(spec, tmp_path / "retry", lambda _: None, lambda: False)
    assert backend.client.was_submitted is False
    assert json.loads(previous.read_text())["remote_state"] == "running"


def test_cannot_prove_prior_remote_stop_blocks_retry(tmp_path, bundle, node_schemas, monkeypatch):
    prior_prompt(tmp_path)
    backend, spec = render_case(tmp_path, bundle, node_schemas)
    def disconnected(*args, **kwargs):
        raise ComfyError("ComfyUI connection failed")
    monkeypatch.setattr(backend.client, "request", disconnected)
    with pytest.raises(ComfyError, match="old-owned-id.*no new render submitted"):
        backend.render(spec, tmp_path / "retry", lambda _: None, lambda: False)
    assert backend.client.was_submitted is False


def test_stopped_prior_remote_prompt_allows_new_version(tmp_path, bundle, node_schemas):
    previous = prior_prompt(tmp_path)
    backend, spec = render_case(tmp_path, bundle, node_schemas)
    backend.render(spec, tmp_path / "retry", lambda _: None, lambda: False)
    assert backend.client.was_submitted is True
    assert json.loads(previous.read_text())["remote_terminal_confirmed"] is True


def test_cancel_remote_still_running_records_uncertainty(tmp_path, bundle, node_schemas):
    backend, spec = render_case(tmp_path, bundle, node_schemas)
    backend.client.remote_running = [[0, "owned-prompt-id", {}, {}, []]]
    with pytest.raises(ComfyCanceled, match="remote stop confirmed: False"):
        backend.render(spec, tmp_path / "attempt", lambda _: None, lambda: backend.client.was_submitted)
    integration = json.loads((tmp_path / "attempt" / "comfy-integration.json").read_text())
    assert integration["remote_state"] == "running"
    assert integration["remote_cancellation_confirmed"] is False
