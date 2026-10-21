"""ComfyUI transport and explicitly mapped, source-conditioned LTX workflows.

No weights are downloaded and no conventional upscale is substituted here.
The supplied graphs are source-reviewed recipes, not locally inference-tested models.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import mimetypes
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from typing import Any, Callable


class ComfyError(RuntimeError):
    pass


class ComfyCanceled(ComfyError):
    pass


class ComfyClient:
    def __init__(self, url: str, timeout: float = 30):
        parsed = urllib.parse.urlsplit(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ComfyError("ComfyUI address must be an http(s) URL")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ComfyError("Use a ComfyUI base URL without credentials, query, or fragment")
        self.url = url.rstrip("/")
        self.timeout = min(float(timeout), 30.0)

    def request(self, path: str, data: Any = None, *, raw: bool = False, headers=None):
        payload = json.dumps(data).encode() if data is not None else None
        request_headers = {"Content-Type": "application/json"} if payload else {}
        request_headers.update(headers or {})
        request = urllib.request.Request(self.url + path, data=payload, headers=request_headers)
        return self._open(request, raw=raw)

    def _open(self, request, *, raw=False):
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                result = response.read()
        except urllib.error.HTTPError as exc:
            detail = exc.read(6000).decode("utf-8", "replace")
            raise ComfyError(f"ComfyUI HTTP {exc.code} at {request.selector}: {detail}") from exc
        except (OSError, urllib.error.URLError) as exc:
            raise ComfyError(f"ComfyUI connection failed: {exc}") from exc
        if raw:
            return result
        try:
            return json.loads(result) if result else {}
        except ValueError as exc:
            raise ComfyError("ComfyUI returned an invalid JSON response") from exc

    def object_info(self):
        return self.request("/object_info")

    def system_stats(self):
        return self.request("/system_stats")

    def upload(self, path: Path) -> str:
        """The core /upload/image route stores video bytes too (see integration notes)."""
        boundary = "restorer-" + uuid.uuid4().hex
        filename = uuid.uuid4().hex + path.suffix.lower()
        media_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
        body = (
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"type\"\r\n\r\ninput\r\n"
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"overwrite\"\r\n\r\nfalse\r\n"
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"image\"; filename=\"{filename}\"\r\n"
            f"Content-Type: {media_type}\r\n\r\n"
        ).encode() + path.read_bytes() + f"\r\n--{boundary}--\r\n".encode()
        request = urllib.request.Request(
            self.url + "/upload/image", data=body,
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        )
        result = self._open(request)
        if not result.get("name"):
            raise ComfyError("ComfyUI upload response did not contain a filename")
        return "/".join(x for x in [result.get("subfolder", ""), result["name"]] if x)

    def cancel(self, prompt_id: str) -> bool:
        # This new endpoint interrupts atomically by ID. Older /interrupt endpoints
        # ignore the ID and interrupt strangers' work, so they are never used.
        encoded = urllib.parse.quote(prompt_id, safe="")
        try:
            return bool(self.request(f"/api/jobs/{encoded}/cancel", {}).get("cancelled"))
        except ComfyError as exc:
            if "HTTP 404" not in str(exc) and "HTTP 405" not in str(exc):
                raise
            self.request("/queue", {"delete": [prompt_id]})
            return False


CONSTRAINTS = {
    "max_frames": 97, "frame_multiple": 8, "frame_offset": 1,
    "width_multiple": 32, "height_multiple": 32, "reference_static_only": True,
    "max_actors": 1, "streaming": False, "steps": [8],
}


class WorkflowBundle:
    def __init__(self, data: dict, digest: str = ""):
        if data.get("schema_version") != 1 or data.get("operation") not in {"restore", "refine"}:
            raise ComfyError("Expected restoration workflow bundle schema_version 1 and operation restore/refine")
        self.data = data
        self.prompt = data.get("prompt", {})
        self.bindings = data.get("bindings", {})
        self.digest = digest or hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()
        if not isinstance(self.prompt, dict) or not self.prompt or "nodes" in self.prompt:
            raise ComfyError("Workflow must contain a ComfyUI API graph; UI/subgraph JSON is not an API graph")
        for node_id, node in self.prompt.items():
            if not isinstance(node, dict) or not node.get("class_type") or not isinstance(node.get("inputs"), dict):
                raise ComfyError(f"Invalid API workflow node {node_id}")
        for key in ["source_video", "prompt", "seed", "width", "height", "frame_count", "fps"]:
            if key not in self.bindings:
                raise ComfyError(f"Workflow is missing the {key} binding")
        for key, binding in self.bindings.items():
            if not isinstance(binding, list) or len(binding) != 2:
                raise ComfyError(f"Invalid binding for {key}")
            node_id, field = binding
            if str(node_id) not in self.prompt or field not in self.prompt[str(node_id)]["inputs"]:
                raise ComfyError(f"Binding {key} does not target a real node input")
        if str(data.get("output_node")) not in self.prompt:
            raise ComfyError("Workflow output_node is missing")
        self._validate_semantics()

    @classmethod
    def load(cls, path: Path | str):
        try:
            raw = Path(path).read_bytes()
            return cls(json.loads(raw), hashlib.sha256(raw).hexdigest())
        except (OSError, ValueError) as exc:
            raise ComfyError(f"Cannot read workflow bundle: {exc}") from exc

    @property
    def supports_references(self):
        return bool(self.data.get("reference_guide_node") and "guide_image" in self.bindings)

    def _validate_semantics(self):
        guide_id = str(self.data.get("source_guide_node"))
        guide = self.prompt.get(guide_id, {})
        inputs = guide.get("inputs", {})
        if guide.get("class_type") != "LTXAddVideoICLoRAGuide" or inputs.get("frame_idx") != 0:
            raise ComfyError("Source conditioning requires LTXAddVideoICLoRAGuide at frame_idx 0")
        source_id, source_field = self.bindings["source_video"]
        if self.prompt[str(source_id)]["class_type"] != "LoadVideo" or source_field != "file":
            raise ComfyError("Source video must map to the verified core LoadVideo.file operation")
        image_link = inputs.get("image", [])
        components = self.prompt.get(str(image_link[0]), {}) if isinstance(image_link, list) and len(image_link) == 2 else {}
        if components.get("class_type") != "GetVideoComponents" or components["inputs"].get("video") != [str(source_id), 0] or image_link[1] != 0:
            raise ComfyError("Source guide must consume the source video's actual decoded image frames")
        if inputs.get("use_streaming", False) or inputs.get("latent_downscale_factor") != 1:
            raise ComfyError("First-version source guide requires whole-clip conditioning at downscale factor 1")
        sampler = self.prompt.get(str(self.data.get("sampler_node")), {})
        if sampler.get("class_type") != "LTXVTiledFusionSampler":
            raise ComfyError("Restoration recipe requires the per-step tiled fusion sampler")
        sampler_id = str(self.data["sampler_node"])
        if self.bindings["seed"] != [sampler_id, "seed"] or ("cfg" in self.bindings and self.bindings["cfg"] != [sampler_id, "cfg"]):
            raise ComfyError("Seed and CFG controls must bind the actual fusion sampler inputs")
        def linked_node(field):
            link = sampler["inputs"].get(field)
            return self.prompt.get(str(link[0]), {}) if isinstance(link, list) and len(link) == 2 and link[1] == 0 else {}
        method = linked_node("sampler")
        if method.get("class_type") != "KSamplerSelect" or method["inputs"].get("sampler_name") != "euler":
            raise ComfyError("Verified distilled recipe requires the actual Euler sampler operation")
        schedule = linked_node("sigmas")
        try:
            actual_sigmas = [float(value.strip()) for value in schedule.get("inputs", {}).get("sigmas", "").split(",")]
        except (ValueError, TypeError):
            actual_sigmas = []
        if schedule.get("class_type") != "ManualSigmas" or actual_sigmas != [1.0, .99375, .9875, .98125, .975, .909375, .725, .421875, 0.0]:
            raise ComfyError("Verified distilled recipe requires the exact eight-step upstream sigma schedule")
        latent_link = inputs.get("latent", [])
        latent_id = str(latent_link[0]) if isinstance(latent_link, list) and len(latent_link) == 2 and latent_link[1] == 0 else ""
        if self.prompt.get(latent_id, {}).get("class_type") != "EmptyLTXVLatentVideo" or any(self.bindings[key] != [latent_id, field] for key, field in [("width", "width"), ("height", "height"), ("frame_count", "length")]):
            raise ComfyError("Dimensions and frame count must map to the source guide's actual target video latent")
        if sampler["inputs"].get("tile_frames", 0) != 0:
            raise ComfyError("First-version recipe requires whole-clip sampling (tile_frames 0)")
        tile = (960, 544) if self.data["operation"] == "restore" else (1024, 576)
        actual = (sampler["inputs"].get("tile_width"), sampler["inputs"].get("tile_height"))
        if actual not in {tile, tile[::-1]} or sampler["inputs"].get("overlap_frac", 0) < .5:
            raise ComfyError(f"Wrong trained tile geometry or overlap; expected {tile} with overlap >= 0.5")
        adapters = [n for n in self.prompt.values() if n["class_type"] == "LTXICLoRALoaderModelOnly"]
        filename = f"ltx-2.5-22b-ic-lora-{'restore' if self.data['operation']=='restore' else 'refine-details'}-1.0.safetensors"
        if len(adapters) != 1 or Path(adapters[0]["inputs"].get("lora_name", "")).name != filename:
            raise ComfyError(f"Recipe must explicitly load {filename}; Ingredients is not a restoration adapter")
        if adapters[0]["inputs"].get("strength_model") != 1 or inputs.get("strength") != 1:
            raise ComfyError("Verified recipe requires adapter and source-guide strength 1")
        if self.supports_references:
            ref = self.prompt.get(str(self.data["reference_guide_node"]), {})
            ri = ref.get("inputs", {})
            if ref.get("class_type") != "LTXAddVideoICLoRAGuide" or ri.get("frame_idx") != -1:
                raise ComfyError("Actor reference must use the verified IC-LoRA -1 RoPE guide operation")
            if ri.get("use_streaming", False) or ri.get("latent_downscale_factor") != 1:
                raise ComfyError("Actor reference must use whole-clip conditioning with downscale factor 1")
            if ri.get("image") != [str(self.data.get("reference_image_node")), 0]:
                raise ComfyError("Actor reference binding does not feed the actual reference guide")
            if ri.get("strength") != 1 or any(ri.get(field) != [guide_id, slot] for field, slot in [("positive", 0), ("negative", 1), ("latent", 2)]):
                raise ComfyError("Actor reference must chain after the source guide at strength 1")
            reference_image_id = str(self.data["reference_image_node"])
            if self.prompt.get(reference_image_id, {}).get("class_type") != "LoadImage" or self.bindings["guide_image"] != [reference_image_id, "image"]:
                raise ComfyError("Reference artifact must map to the actual LoadImage.image input")
        final_guide_id = str(self.data["reference_guide_node"]) if self.supports_references else guide_id
        if any(sampler["inputs"].get(field) != [final_guide_id, slot] for field, slot in [("positive", 0), ("negative", 1), ("latents", 2)]):
            raise ComfyError("Fusion sampler must consume the final guide's conditioning and latent")

    def mapped(self, values: dict, *, use_references: bool) -> dict:
        graph = copy.deepcopy(self.prompt)
        for key, value in values.items():
            if key in self.bindings:
                node, field = self.bindings[key]
                graph[str(node)]["inputs"][field] = value
        if not use_references and self.supports_references:
            ref_id = str(self.data["reference_guide_node"])
            source_id = str(self.data["source_guide_node"])
            image_id = str(self.data["reference_image_node"])
            for node in graph.values():
                for field, value in node["inputs"].items():
                    if isinstance(value, list) and len(value) == 2 and str(value[0]) == ref_id:
                        node["inputs"][field] = [source_id, value[1]]
            graph.pop(ref_id)
            graph.pop(image_id)
        return graph

    def validate(self, object_info: dict, graph: dict | None = None) -> list[str]:
        errors = []
        graph = graph or self.prompt
        upload_bindings = {tuple(v) for k, v in self.bindings.items() if k in {"source_video", "guide_image"}}
        for node_id, node in graph.items():
            class_type = node["class_type"]
            schema = object_info.get(class_type)
            if not schema:
                errors.append(f"Missing ComfyUI node: {class_type}")
                continue
            required = dict(schema.get("input", {}).get("required", {}))
            definitions = {**required, **schema.get("input", {}).get("optional", {})}
            # Core SaveVideo now uses nested dynamic-combo inputs. API prompts
            # flatten them as format.codec, not nested JSON or a top-level codec.
            pending = list(definitions)
            while pending:
                field = pending.pop()
                definition = definitions[field]
                if not definition or definition[0] != "COMFY_DYNAMICCOMBO_V3":
                    continue
                options = definition[1].get("options", []) if len(definition) > 1 else []
                selected = next((option for option in options if option.get("key") == node["inputs"].get(field)), None)
                if selected is None:
                    if field in node["inputs"]:
                        errors.append(f"{class_type}.{field}: unsupported dynamic option")
                    continue
                for category, fields in selected.get("inputs", {}).items():
                    if category not in {"required", "optional"}:
                        continue
                    for child, child_definition in fields.items():
                        expanded = field + "." + child
                        definitions[expanded] = child_definition
                        if category == "required":
                            required[expanded] = child_definition
                        pending.append(expanded)
            for field in required:
                if field not in node["inputs"]:
                    errors.append(f"{class_type}.{field}: required workflow input is absent")
            for field, value in node["inputs"].items():
                if field not in definitions:
                    errors.append(f"{class_type}.{field}: input absent from installed node schema")
                    continue
                if isinstance(value, list) and len(value) == 2 and isinstance(value[0], str) and isinstance(value[1], int):
                    if value[0] not in graph:
                        errors.append(f"{class_type}.{field}: linked node does not exist")
                        continue
                    origin_schema = object_info.get(graph[value[0]]["class_type"], {})
                    outputs = origin_schema.get("output", [])
                    if value[1] < 0 or value[1] >= len(outputs):
                        errors.append(f"{class_type}.{field}: invalid linked output slot")
                    elif definitions[field][0] not in (outputs[value[1]], "*") and outputs[value[1]] != "*":
                        errors.append(f"{class_type}.{field}: linked output type does not match input type")
                    continue
                definition = definitions[field]
                if not definition:
                    continue
                kind = definition[0]
                if isinstance(kind, list) and (node_id, field) not in upload_bindings and value not in kind:
                    errors.append(f"{class_type}.{field}: {value!r} not available (model file or option missing)")
                options = definition[1] if len(definition) > 1 and isinstance(definition[1], dict) else {}
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    if not math.isfinite(value) or value < options.get("min", -math.inf) or value > options.get("max", math.inf):
                        errors.append(f"{class_type}.{field}: value exceeds installed node bounds")
        return list(dict.fromkeys(errors))


class ComfyBackend:
    def __init__(self, settings):
        self.settings = settings
        self.client = ComfyClient(settings.comfy_url, getattr(settings, "comfy_timeout", 30))

    def _guard_prior_prompts(self, work_dir: Path):
        """Do not duplicate app-owned inference left running after cancel/restart."""
        outstanding = []
        for path in work_dir.parent.glob("*/comfy-integration.json"):
            if path.parent == work_dir:
                continue
            try:
                record = json.loads(path.read_text())
            except (OSError, ValueError) as exc:
                raise ComfyError(f"Cannot verify previous application render state at {path}: {exc}") from exc
            if record.get("server_url") != self.client.url or not record.get("prompt_id"):
                continue
            if record.get("render_executed") or record.get("remote_terminal_confirmed"):
                continue
            outstanding.append((path, record))
        if not outstanding:
            return
        ids = ", ".join(record["prompt_id"] for _, record in outstanding)
        try:
            queue = self.client.request("/queue")
        except ComfyError as exc:
            raise ComfyError(f"Cannot verify previous app-owned ComfyUI prompts {ids} at {self.client.url}; no new render submitted: {exc}") from exc
        running = {item[1] for item in queue.get("queue_running", []) if len(item) > 1}
        pending = {item[1] for item in queue.get("queue_pending", []) if len(item) > 1}
        for path, record in outstanding:
            prompt_id = record["prompt_id"]
            state = "running" if prompt_id in running else "pending" if prompt_id in pending else "not_in_remote_queue"
            record["remote_state"] = state
            if prompt_id in running | pending:
                path.write_text(json.dumps(record, indent=2))
                raise ComfyError(f"Previous application prompt {prompt_id} is still {state} at {self.client.url} ({path.parent.name}). Wait for it to finish or cancel it in that ComfyUI instance before retrying. No new render submitted.")
            try:
                history = self.client.request("/history/" + urllib.parse.quote(prompt_id, safe="")).get(prompt_id, {})
            except ComfyError as exc:
                raise ComfyError(f"Cannot verify previous app-owned prompt {prompt_id} history; no new render submitted: {exc}") from exc
            record["remote_terminal_confirmed"] = True
            record["remote_history_status"] = history.get("status", {"status_str": "not_retained"})
            path.write_text(json.dumps(record, indent=2))

    def _cancel_prompt(self, prompt_id: str, integration: dict, work_dir: Path, log: Callable):
        integration["remote_cancel_requested"] = True
        integration["remote_cancellation_confirmed"] = False
        try:
            dispatched = self.client.cancel(prompt_id)
            integration["targeted_cancellation_supported"] = dispatched
            queue = self.client.request("/queue")
            running = {item[1] for item in queue.get("queue_running", []) if len(item) > 1}
            pending = {item[1] for item in queue.get("queue_pending", []) if len(item) > 1}
            state = "running" if prompt_id in running else "pending" if prompt_id in pending else "not_in_remote_queue"
            integration["remote_state"] = state
            integration["remote_cancellation_confirmed"] = prompt_id not in running | pending
            integration["remote_terminal_confirmed"] = prompt_id not in running | pending
            if not integration["remote_terminal_confirmed"]:
                log(f"ComfyUI prompt {prompt_id} remains {state} at {self.client.url}; stopping remotely is unconfirmed. New app submissions will be blocked until this prompt leaves the remote queue.")
            else:
                log(f"ComfyUI prompt {prompt_id} is no longer running or pending. Its generated result is not accepted by this canceled job.")
        except ComfyError as exc:
            integration["remote_state"] = "unknown"
            integration["remote_cancel_error"] = str(exc)
            log(f"ComfyUI prompt {prompt_id} at {self.client.url}: remote cancellation unconfirmed ({exc}). A render may continue; the next submission must verify this owned prompt first.")
        (work_dir / "comfy-integration.json").write_text(json.dumps(integration, indent=2))

    def capability(self) -> dict:
        result = {"available": False, "configured": bool(self.settings.comfy_workflow),
                  "supports_references": False, "constraints": dict(CONSTRAINTS),
                  "inference_tested": False, "blockers": []}
        if not self.settings.comfy_workflow:
            result["blockers"] = ["Configure an API workflow bundle (workflows/ltx25-restore.json or ltx25-refine.json); install its nodes and approved model files explicitly."]
            return result
        try:
            bundle = WorkflowBundle.load(self.settings.comfy_workflow)
            info = self.client.object_info()
            result.update(operation=bundle.data["operation"], workflow_sha256=bundle.digest,
                          supports_references=bundle.supports_references,
                          controls=["scale", *[key for key in ("prompt", "seed", "cfg", "negative_prompt") if key in bundle.bindings]],
                          required_nodes=sorted({n["class_type"] for n in bundle.prompt.values()}))
            result["blockers"] = bundle.validate(info)
            result["available"] = not result["blockers"]
        except ComfyError as exc:
            result["blockers"] = [str(exc)]
        return result

    def render(self, spec: dict, work_dir: Path, log: Callable, canceled: Callable) -> Path:
        if not self.settings.comfy_workflow and not spec.get("workflow_snapshot"):
            raise ComfyError("ComfyUI workflow bundle is not configured")
        # Jobs own their snapshot. Editing config after queueing cannot alter the render.
        bundle = WorkflowBundle(spec["workflow_snapshot"]) if spec.get("workflow_snapshot") else WorkflowBundle.load(self.settings.comfy_workflow)
        expected = "refine" if spec.get("backend") == "comfy_refine" else "restore"
        if bundle.data["operation"] != expected:
            raise ComfyError(f"Configured workflow is {bundle.data['operation']}, requested operation is {expected}")
        frames, width, height = (int(spec[k]) for k in ("frame_count", "width", "height"))
        if frames < 9 or frames > 97 or (frames - 1) % 8 or width < 64 or height < 64 or width % 32 or height % 32:
            raise ComfyError("LTX initial recipe requires 9..97 frames in 8n+1 and a canvas of multiples of 32 (minimum 64)")
        if int(spec.get("steps", 8)) != 8:
            raise ComfyError("This verified distilled recipe exposes exactly 8 steps")
        if "cfg" in spec and "cfg" not in bundle.bindings:
            raise ComfyError("Configured workflow has no CFG input binding")
        if float(spec.get("fps", 0)) <= 0:
            raise ComfyError("Render frame rate must be positive")
        use_references = bool(spec.get("use_references"))
        if use_references and (not bundle.supports_references or not spec.get("guide_path")):
            raise ComfyError("Selected workflow has no verified spatial reference guide, or the guide artifact is missing")
        if canceled():
            raise ComfyCanceled("Canceled before upload")
        self._guard_prior_prompts(work_dir)
        info = self.client.object_info()
        errors = bundle.validate(info, bundle.mapped({}, use_references=use_references))
        if errors:
            raise ComfyError("ComfyUI preflight: " + "; ".join(errors))
        values = {k: spec[k] for k in bundle.bindings if k in spec}
        values["source_video"] = self.client.upload(Path(spec["source_clip"]))
        if use_references:
            values["guide_image"] = self.client.upload(Path(spec["guide_path"]))
        values["output_prefix"] = "ltx_reference_restorer/" + uuid.uuid4().hex
        graph = bundle.mapped(values, use_references=use_references)
        # Refresh after upload: LoadVideo and LoadImage filename enums are dynamic.
        errors = bundle.validate(self.client.object_info(), graph)
        if errors:
            raise ComfyError("Mapped ComfyUI workflow is incompatible: " + "; ".join(errors))
        work_dir.mkdir(parents=True, exist_ok=True)
        graph_bytes = json.dumps(graph, indent=2).encode()
        (work_dir / "workflow-api.json").write_bytes(graph_bytes)
        try:
            system_stats = self.client.system_stats()
        except ComfyError as exc:
            system_stats = {"unavailable": str(exc)}
        integration = {
            "server_url": self.client.url,
            "bundle_sha256": bundle.digest, "operation": bundle.data["operation"],
            "source_bundle_file_sha256": spec.get("workflow_sha256"),
            "api_graph_sha256": hashlib.sha256(graph_bytes).hexdigest(),
            "upstream": bundle.data.get("upstream"), "render_executed": False,
            "use_references": use_references, "constraints": CONSTRAINTS,
            "system_stats_before": system_stats,
            "node_versions": {kind: {key: info[kind].get(key) for key in ("python_module", "version", "module_version") if info[kind].get(key) is not None} for kind in {n["class_type"] for n in graph.values()} if kind in info},
            "models": [{"node": key, "class_type": node["class_type"], "input": field, "filename": value, "sha256": None, "hash_status": "not exposed by ComfyUI object_info"} for key, node in graph.items() for field, value in node["inputs"].items() if field in {"unet_name", "clip_name", "vae_name", "lora_name"}],
        }
        (work_dir / "comfy-integration.json").write_text(json.dumps(integration, indent=2))
        if canceled():
            raise ComfyCanceled("Canceled before submission")
        self._guard_prior_prompts(work_dir)
        submitted = self.client.request("/prompt", {"prompt": graph, "client_id": uuid.uuid4().hex})
        if submitted.get("error") or submitted.get("node_errors") or not submitted.get("prompt_id"):
            raise ComfyError("ComfyUI rejected workflow: " + json.dumps(submitted)[:6000])
        prompt_id = submitted["prompt_id"]
        integration["prompt_id"] = prompt_id
        integration["remote_terminal_confirmed"] = False
        integration["remote_state"] = "submitted"
        (work_dir / "comfy-integration.json").write_text(json.dumps(integration, indent=2))
        (work_dir / "comfy-prompt-id.txt").write_text(prompt_id)
        log(f"ComfyUI prompt {prompt_id} submitted; progress reports queue state, not invented completion percentages.")
        deadline = time.monotonic() + float(getattr(self.settings, "comfy_timeout", 7200))
        last_state = None
        while True:
            if canceled():
                self._cancel_prompt(prompt_id, integration, work_dir, log)
                raise ComfyCanceled(f"Canceled by user; ComfyUI prompt {prompt_id}, remote stop confirmed: {integration['remote_cancellation_confirmed']}")
            if time.monotonic() > deadline:
                self._cancel_prompt(prompt_id, integration, work_dir, log)
                raise ComfyError(f"ComfyUI prompt {prompt_id} timed out; remote stop confirmed: {integration['remote_cancellation_confirmed']}")
            record = self.client.request("/history/" + urllib.parse.quote(prompt_id, safe="")).get(prompt_id)
            if record:
                status = record.get("status", {})
                if status.get("status_str") == "error":
                    integration.update(remote_terminal_confirmed=True, remote_state="error", remote_status=status)
                    (work_dir / "comfy-integration.json").write_text(json.dumps(integration, indent=2))
                    raise ComfyError("ComfyUI execution failed: " + json.dumps(status.get("messages", status))[:6000])
                if status.get("completed") or status.get("status_str") == "success":
                    outputs = record.get("outputs", {}).get(str(bundle.data["output_node"]), {})
                    candidates = []
                    for entries in outputs.values():
                        if isinstance(entries, list):
                            candidates.extend(x for x in entries if isinstance(x, dict) and x.get("filename") and Path(x["filename"]).suffix.lower() in {".mp4", ".mkv", ".webm", ".mov"})
                    if not candidates:
                        raise ComfyError("ComfyUI completed without a video from the configured output node")
                    output = candidates[0]
                    query = urllib.parse.urlencode({"filename": output["filename"], "subfolder": output.get("subfolder", ""), "type": output.get("type", "output")})
                    destination = work_dir / ("comfy-render" + Path(output["filename"]).suffix.lower())
                    payload = self.client.request("/view?" + query, raw=True)
                    if not payload:
                        raise ComfyError("ComfyUI returned an empty output video")
                    with destination.open("xb") as handle:
                        handle.write(payload)
                    integration.update(render_executed=True, remote_terminal_confirmed=True, remote_state="completed", remote_status=status, output_bytes=len(payload), output_sha256=hashlib.sha256(payload).hexdigest())
                    (work_dir / "comfy-integration.json").write_text(json.dumps(integration, indent=2))
                    log(f"Retrieved {len(payload)} bytes from ComfyUI; worker must verify media and restore original audio before success.")
                    return destination
            queue = self.client.request("/queue")
            state = "running" if any(x[1] == prompt_id for x in queue.get("queue_running", [])) else "queued" if any(x[1] == prompt_id for x in queue.get("queue_pending", [])) else "waiting_for_history"
            if state != last_state:
                log("ComfyUI state: " + state)
                last_state = state
            time.sleep(.5)
