from __future__ import annotations

from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class ProjectInput(Input):
    name: str = Field(min_length=1, max_length=200)


class SourceInput(Input):
    path: str


class ShotInput(Input):
    source_id: str
    name: str = Field(default="Shot", min_length=1, max_length=200)
    start_time: float = Field(ge=0)
    end_time: float = Field(gt=0)

    @model_validator(mode="after")
    def valid_range(self):
        if self.end_time <= self.start_time:
            raise ValueError("end_time must be after start_time")
        return self


class ActorInput(Input):
    name: str = Field(min_length=1, max_length=200)


class ReferenceInput(Input):
    path: str | None = None
    source_id: str | None = None
    timestamp: float | None = Field(default=None, ge=0)
    crop: tuple[float, float, float, float] | None = None  # x,y,width,height in source pixels
    view: Literal["front", "three_quarter", "profile"] = "front"
    quality: float = Field(default=3, ge=0, le=5)
    approval_status: Literal["pending", "approved", "rejected"] = "pending"
    provenance: Literal["original_footage", "external_photograph", "generated_reconstruction"] = "external_photograph"
    notes: str = Field(default="", max_length=10000)
    expression: str = ""
    lighting: str = ""


class ReferencePatch(Input):
    view: Literal["front", "three_quarter", "profile"] | None = None
    quality: float | None = Field(default=None, ge=0, le=5)
    approval_status: Literal["pending", "approved", "rejected"] | None = None
    notes: str | None = None
    expression: str | None = None
    lighting: str | None = None


class Placement(Input):
    frame: int = Field(ge=0)
    x: float = Field(ge=0)
    y: float = Field(ge=0)
    width: float = Field(gt=0)
    height: float = Field(gt=0)


class Setup(Input):
    actor_id: str | None = None
    reference_ids: list[str] = Field(default_factory=list, max_length=8)
    keyframes: list[Placement] = Field(default_factory=list, max_length=100)
    interpolation: Literal["linear", "hold"] = "linear"
    view: Literal["front", "three_quarter", "profile"] = "front"


class ShotPatch(Input):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    setup: Setup | None = None


class JobInput(Input):
    backend: Literal["baseline", "comfy_restore", "comfy_refine", "mlx"] = "baseline"
    scale: int = Field(default=2, ge=1, le=4)
    prompt: str = Field(default="Preserve the source performance, expression, gaze and motion. Restore natural detail.", max_length=10000)
    seed: int = Field(default=42, ge=0, le=2**63-1)
    use_references: bool = False
    steps: int = Field(default=8, ge=1, le=100)
    cfg: float = Field(default=1.0, ge=0, le=20)


class GuideInput(Input):
    backend: Literal["baseline", "comfy_restore", "comfy_refine", "mlx"] = "baseline"
    use_references: bool = False
    scale: int = Field(default=2, ge=1, le=4)


class ReviewInput(Input):
    state: Literal["accepted", "rejected", "needs_revision"]
    notes: str = Field(default="", max_length=20000)
    criteria: dict[str, str] = Field(default_factory=dict)


class NoteInput(Input):
    text: str = Field(min_length=1, max_length=20000)
    shot_id: str | None = None
    actor_id: str | None = None
    timestamp: float | None = Field(default=None, ge=0)
