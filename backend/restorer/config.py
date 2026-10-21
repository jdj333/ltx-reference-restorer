from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Settings:
    data_dir: Path = field(default_factory=lambda: Path.home() / "Library/Application Support/LTX Reference Restorer")
    host: str = "127.0.0.1"
    port: int = 8787
    comfy_url: str = "http://127.0.0.1:8188"
    comfy_workflow: Path | None = None
    comfy_timeout: float = 3600
    import_roots: tuple[Path, ...] = field(default_factory=lambda: (Path.home(), Path("/tmp")))
    ffmpeg: str = "ffmpeg"
    ffprobe: str = "ffprobe"
    max_frames: int = 20000
    presets: dict[str, dict] = field(default_factory=lambda: {
        "baseline_1x": {"label": "Baseline · source dimensions", "backend": "baseline", "scale": 1},
        "baseline_2x": {"label": "Baseline · 2× upscale", "backend": "baseline", "scale": 2},
        "ltx_short_probe": {"label": "LTX Restore · short static probe, 1×", "backend": "comfy_restore", "scale": 1, "seed": 42, "steps": 8, "cfg": 1, "use_references": False},
    })

    def __post_init__(self):
        self.data_dir = Path(self.data_dir).expanduser().resolve()
        self.import_roots = tuple(Path(p).expanduser().resolve() for p in self.import_roots)
        if self.comfy_workflow:
            self.comfy_workflow = Path(self.comfy_workflow).expanduser().resolve()
        from .schemas import JobInput
        for key, preset in self.presets.items():
            if not key or not isinstance(preset, dict):
                raise ValueError("Presets must be named job-setting tables")
            JobInput(**{k: v for k, v in preset.items() if k != "label"})

    def initialize(self):
        self.data_dir.mkdir(parents=True, exist_ok=True)
        for name in ("sources", "references", "previews", "guides", "jobs", "demo"):
            (self.data_dir / name).mkdir(exist_ok=True)

    def import_path(self, value: str) -> Path:
        path = Path(value).expanduser().resolve(strict=True)
        if not path.is_file() or not any(path.is_relative_to(root) for root in self.import_roots):
            raise ValueError("Import must be a regular file within configured import_roots")
        return path

    def asset_path(self, value: str) -> Path:
        path = (self.data_dir / value).resolve()
        if not path.is_relative_to(self.data_dir):
            raise ValueError("Asset path leaves the data directory")
        return path

    def relative(self, path: Path) -> str:
        return str(path.resolve().relative_to(self.data_dir))


def load_settings() -> Settings:
    config = os.environ.get("RESTORER_CONFIG")
    values = {}
    if config:
        with open(Path(config).expanduser(), "rb") as f:
            values = tomllib.load(f).get("restorer", {})
    for key in ("data_dir", "host", "port", "comfy_url", "comfy_workflow", "ffmpeg", "ffprobe"):
        value = os.environ.get("RESTORER_" + key.upper())
        if value is not None:
            values[key] = int(value) if key == "port" else value
    return Settings(**values)
