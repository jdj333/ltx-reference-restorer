"""Read-only local preflight. Discovery is evidence, never an inference benchmark."""

from __future__ import annotations

import importlib.metadata
import json
import platform
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx
import psutil

from .backends.comfy import ComfyError, WorkflowBundle


MLX_LIMITATION = (
    "Unavailable in this application: the inspected MLX IC-LoRA implementation "
    "does not port stage_2_ic_lora=True restoration plans. Its --image anchors "
    "are timeline keyframes, not verified spatial actor references. No MLX "
    "restoration/reference inference has been verified here."
)


def _tool(binary: str) -> dict[str, Any]:
    executable = shutil.which(binary)
    if not executable:
        return {"available": False, "configured": binary, "error": "Executable not found on PATH"}
    try:
        result = subprocess.run(
            [executable, "-version"], capture_output=True, text=True, timeout=5, check=False
        )
        first_line = (result.stdout or result.stderr).splitlines()
        return {
            "available": result.returncode == 0,
            "path": executable,
            "version": first_line[0] if first_line else "Version not reported",
        }
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"available": False, "path": executable, "error": str(exc)}


def _nearest_existing(path: Path) -> Path:
    path = path.expanduser().resolve()
    while not path.exists() and path != path.parent:
        path = path.parent
    return path


def _installed(name: str) -> str | None:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return None


def _get_json(client: httpx.Client, url: str) -> Any:
    response = client.get(url)
    response.raise_for_status()
    return response.json()


def _workflow(path: Path | None, nodes: dict[str, Any]) -> dict[str, Any]:
    if not path:
        return {"configured": False, "available": False, "error": "Set comfy_workflow to an API-format workflow."}
    path = Path(path).expanduser()
    try:
        payload = json.loads(path.read_text())
        if not isinstance(payload, dict):
            raise ValueError("Expected a workflow object")
        graph = payload.get("prompt", payload)
        if not isinstance(graph, dict):
            raise ValueError("Expected an API-format node mapping")
        required = sorted(
            {node["class_type"] for node in graph.values() if isinstance(node, dict) and "class_type" in node}
        )
        if not required:
            raise ValueError("No class_type nodes found; export workflow in API format")
        missing = [name for name in required if name not in nodes]
        selected_models: list[dict[str, Any]] = []
        for node_id, node in graph.items():
            if not isinstance(node, dict):
                continue
            spec = nodes.get(node.get("class_type"), {})
            if not isinstance(spec, dict):
                spec = {}
            declarations = {}
            for group in spec.get("input", {}).values():
                if isinstance(group, dict):
                    declarations.update(group)
            inputs = node.get("inputs", {})
            if not isinstance(inputs, dict):
                raise ValueError(f"Node {node_id} inputs must be a mapping")
            for input_name, value in inputs.items():
                if not isinstance(value, str) or not value.lower().endswith((".safetensors", ".ckpt", ".gguf", ".pt", ".pth", ".bin")):
                    continue
                declaration = declarations.get(input_name)
                choices = declaration[0] if isinstance(declaration, list) and declaration and isinstance(declaration[0], list) else None
                selected_models.append({
                    "node": str(node_id), "input": input_name, "filename": value,
                    "advertised": value in choices if choices is not None else None,
                })
        blockers: list[str] = []
        bundle = None
        try:
            bundle = WorkflowBundle.load(path)
            blockers = bundle.validate(nodes) if nodes else ["ComfyUI node inventory is unavailable"]
        except ComfyError as exc:
            blockers = [str(exc)]
        return {
            "configured": True,
            "path": str(path),
            "required_nodes": required,
            "missing_nodes": missing,
            "selected_models": selected_models,
            "blockers": blockers,
            "operation": bundle.data["operation"] if bundle else None,
            "supports_references": bundle.supports_references if bundle else False,
            "available": bool(nodes) and not missing and not blockers and all(item["advertised"] is not False for item in selected_models),
            "meaning": "Node names present only; model compatibility and inference require separate validation.",
        }
    except (OSError, ValueError, TypeError) as exc:
        return {"configured": True, "path": str(path), "available": False, "error": str(exc)}


def _comfy(settings: Any) -> dict[str, Any]:
    url = str(settings.comfy_url).rstrip("/")
    try:
        parsed = urlsplit(url)
        parsed.port
    except ValueError:
        return {"connected": False, "ready": False, "operations": [], "error": "Invalid ComfyUI base URL"}
    result: dict[str, Any] = {
        "url": url if not any((parsed.username, parsed.password, parsed.query, parsed.fragment)) else "<invalid URL with credentials, query or fragment>",
        "connected": False,
        "operations": [],
        "inference_tested": False,
        "node_versions": "Per-node versions are not reliably exposed by ComfyUI object_info.",
        "model_files": [],
        "model_availability_scope": "Filenames advertised in node input choices; files were not loaded or hashed.",
    }
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        result["error"] = "ComfyUI URL must be an http(s) address without embedded credentials"
        return result
    nodes: dict[str, Any] = {}
    try:
        with httpx.Client(timeout=3, follow_redirects=False, trust_env=False) as client:
            stats = _get_json(client, f"{url}/system_stats")
            result["system_stats"] = stats
            result["connected"] = True
            try:
                raw = _get_json(client, f"{url}/object_info")
                if not isinstance(raw, dict):
                    raise ValueError("object_info was not a node mapping")
                nodes = raw
                result["node_count"] = len(nodes)
                result["ltx_nodes"] = sorted(name for name in nodes if "ltx" in name.lower())
                discovered: set[str] = set()
                module_names: set[str] = set()
                for spec in nodes.values():
                    if not isinstance(spec, dict):
                        continue
                    module = spec.get("python_module")
                    if module and "ltx" in str(module).lower():
                        module_names.add(str(module))
                    for group in spec.get("input", {}).values():
                        if not isinstance(group, dict):
                            continue
                        for input_name, declaration in group.items():
                            if not any(term in input_name.lower() for term in ("ckpt", "model", "lora", "vae", "encoder", "upscale")):
                                continue
                            if isinstance(declaration, list) and declaration and isinstance(declaration[0], list):
                                for item in declaration[0]:
                                    if isinstance(item, str) and item.lower().endswith((".safetensors", ".ckpt", ".gguf", ".pt", ".pth", ".bin")):
                                        discovered.add(item)
                result["ltx_modules"] = sorted(module_names)
                result["model_files"] = sorted(discovered)
            except (httpx.HTTPError, ValueError, TypeError) as exc:
                result["object_info_error"] = str(exc)
    except (httpx.HTTPError, ValueError, TypeError) as exc:
        result["error"] = str(exc)
    result["workflow"] = _workflow(getattr(settings, "comfy_workflow", None), nodes)
    result["ready"] = result["connected"] and result["workflow"]["available"]
    if result["ready"]:
        result["operations"] = [result["workflow"]["operation"]]
    result["readiness_meaning"] = "Connectivity and node presence only; submission preflight validates operation constraints."
    return result


def report(settings: Any) -> dict[str, Any]:
    """Return JSON-serializable observations without creating files or loading weights."""
    data_dir = Path(settings.data_dir).expanduser().resolve()
    disk_path = _nearest_existing(data_dir)
    try:
        memory = psutil.virtual_memory()
        memory_stats = {"total_bytes": memory.total, "available_bytes": memory.available}
    except (psutil.Error, OSError) as exc:
        memory_stats = {"error": str(exc), "available_bytes": None, "total_bytes": None}
    disk_stats: dict[str, Any] = {"data_dir": str(data_dir), "checked_path": str(disk_path)}
    try:
        disk = shutil.disk_usage(disk_path)
        disk_stats.update(free_bytes=disk.free, total_bytes=disk.total)
    except OSError as exc:
        disk_stats.update(error=str(exc), free_bytes=None, total_bytes=None)
    ffmpeg = _tool(getattr(settings, "ffmpeg", "ffmpeg"))
    ffprobe = _tool(getattr(settings, "ffprobe", "ffprobe"))
    return {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "platform": {
            "os": platform.system(),
            "release": platform.release(),
            "architecture": platform.machine(),
            "python": platform.python_version(),
            "apple_silicon": platform.system() == "Darwin" and platform.machine() == "arm64",
        },
        "memory": memory_stats,
        "disk": disk_stats,
        "tools": {"ffmpeg": ffmpeg, "ffprobe": ffprobe},
        "backends": {
            "baseline": {
                "available": ffmpeg["available"] and ffprobe["available"],
                "label": "baseline upscale",
                "operations": ["upscale"],
                "actor_reference_conditioning": False,
            },
            "comfy": _comfy(settings),
            "mlx": {
                "available": False,
                "installed_packages": {name: _installed(name) for name in ("mlx", "ltx-pipelines-mlx", "ltx-core-mlx")},
                "operations": [],
                "reason": MLX_LIMITATION,
            },
        },
        "presets": {
            "configured_job_presets": getattr(settings, "presets", {}),
            "first_probe": {"duration_seconds": 2, "baseline_scale": 2, "actors": 1},
            "apple_32_36_gb": "Start with a short baseline; LTX feasibility requires an actual measured backend probe.",
            "apple_128_gb": "Capacity does not establish inference speed, model support, or fidelity; measure a short backend probe.",
        },
        "notes": [
            "No model download, inference, or subjective quality assessment was performed by doctor.",
            "The source film supplies the performance. Approved references guide appearance and detail.",
        ],
    }
