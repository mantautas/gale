"""Look parameters: YAML on disk, sliders in the play UI, uniforms at render.

`*_mod` fields are the extra amount added when the matching audio
feature is at 1.0. Set a mod to 0 to make that effect static.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

import yaml

GEO_MODES = [
    "none",
    "slices",
    "polar",
    "voronoi",
    "kaleido",
    "fold",
    "mosaic",
    "luma",
    "droste",
    "hex",
    "tiles",
]
GEO_MODE_INDEX = {name: i for i, name in enumerate(GEO_MODES)}

# Slider schema for the play UI. `path` is dotted against Look.to_dict().
SLIDERS = [
    {"group": "Geo", "path": "geo.mode", "label": "Mode", "type": "enum", "options": GEO_MODES},
    {"group": "Geo", "path": "geo.mix", "label": "Mix", "min": 0.0, "max": 1.0, "step": 0.01},
    {"group": "Geo", "path": "geo.amount", "label": "Amount", "min": 0.0, "max": 0.8, "step": 0.01},
    {"group": "Geo", "path": "geo.amount_mod", "label": "Amount × energy", "min": 0.0, "max": 0.8, "step": 0.01},
    {"group": "Geo", "path": "geo.count", "label": "Count (slices/kaleido/tiles)", "min": 2.0, "max": 36.0, "step": 1.0},
    {"group": "Geo", "path": "geo.scale", "label": "Scale (voronoi/fold/hex/droste)", "min": 0.5, "max": 12.0, "step": 0.1},
    {"group": "Geo", "path": "geo.line", "label": "Cell lines", "min": 0.0, "max": 1.0, "step": 0.01},
    {"group": "Geo", "path": "geo.speed", "label": "Spin / drift", "min": 0.0, "max": 1.0, "step": 0.01},
    {"group": "Geo", "path": "geo.center_x", "label": "Center X", "min": 0.0, "max": 1.0, "step": 0.01},
    {"group": "Geo", "path": "geo.center_y", "label": "Center Y", "min": 0.0, "max": 1.0, "step": 0.01},
    {"group": "Grade", "path": "grade.contrast", "label": "Contrast", "min": 0.7, "max": 1.8, "step": 0.01},
    {"group": "Grade", "path": "grade.saturation", "label": "Saturation", "min": 0.0, "max": 1.5, "step": 0.01},
    {"group": "Grade", "path": "grade.crush", "label": "Crush", "min": 0.8, "max": 1.4, "step": 0.01},
    {"group": "Flow", "path": "flow.amount", "label": "Amount", "min": 0.0, "max": 0.08, "step": 0.001},
    {"group": "Flow", "path": "flow.amount_mod", "label": "Amount × energy", "min": 0.0, "max": 0.08, "step": 0.001},
    {"group": "Flow", "path": "flow.scale", "label": "Scale", "min": 0.4, "max": 8.0, "step": 0.1},
    {"group": "Flow", "path": "flow.speed", "label": "Speed", "min": 0.0, "max": 1.0, "step": 0.01},
    {"group": "Flow", "path": "flow.speed_mod", "label": "Speed × energy", "min": 0.0, "max": 1.0, "step": 0.01},
    {"group": "Trails", "path": "trails.mix", "label": "Mix", "min": 0.0, "max": 0.7, "step": 0.01},
    {"group": "Trails", "path": "trails.mix_mod", "label": "Mix × kick", "min": 0.0, "max": 0.7, "step": 0.01},
    {"group": "Trails", "path": "trails.decay", "label": "Decay", "min": 0.7, "max": 0.99, "step": 0.01},
    {"group": "Trails", "path": "trails.zoom", "label": "Zoom", "min": 0.99, "max": 1.03, "step": 0.001},
    {"group": "Glow", "path": "glow.threshold", "label": "Threshold", "min": 0.2, "max": 0.9, "step": 0.01},
    {"group": "Glow", "path": "glow.amount", "label": "Amount", "min": 0.0, "max": 1.2, "step": 0.01},
    {"group": "Glow", "path": "glow.amount_mod", "label": "Amount × RMS", "min": 0.0, "max": 1.2, "step": 0.01},
    {"group": "Grain", "path": "grain.amount", "label": "Grain", "min": 0.0, "max": 0.2, "step": 0.005},
    {"group": "Grain", "path": "grain.amount_mod", "label": "Grain × RMS", "min": 0.0, "max": 0.2, "step": 0.005},
    {"group": "Grain", "path": "grain.fiber", "label": "Fiber", "min": 0.0, "max": 0.3, "step": 0.01},
    {"group": "Grain", "path": "grain.fiber_mod", "label": "Fiber × mids", "min": 0.0, "max": 0.3, "step": 0.01},
]


def _take(cls, data: dict | None):
    valid = {f.name for f in fields(cls)}
    return cls(**{k: v for k, v in (data or {}).items() if k in valid})


@dataclass
class Geo:
    mode: str = "none"
    mix: float = 1.0
    amount: float = 0.18
    amount_mod: float = 0.12
    count: float = 8.0
    scale: float = 4.0
    line: float = 0.12
    speed: float = 0.04
    center_x: float = 0.5
    center_y: float = 0.5


@dataclass
class Grade:
    contrast: float = 1.12
    saturation: float = 0.82
    crush: float = 1.08
    shadow_tint: list[float] = field(default_factory=lambda: [0.86, 0.94, 1.05])
    highlight_tint: list[float] = field(default_factory=lambda: [1.06, 0.98, 0.90])


@dataclass
class Flow:
    amount: float = 0.006
    amount_mod: float = 0.018
    scale: float = 2.4
    speed: float = 0.12
    speed_mod: float = 0.20


@dataclass
class Trails:
    mix: float = 0.14
    mix_mod: float = 0.28
    decay: float = 0.94
    zoom: float = 1.004
    angle: float = 0.004
    hit_tau: float = 0.40


@dataclass
class Glow:
    threshold: float = 0.52
    knee: float = 0.28
    amount: float = 0.22
    amount_mod: float = 0.35
    tint: list[float] = field(default_factory=lambda: [1.0, 0.36, 0.14])


@dataclass
class Grain:
    amount: float = 0.045
    amount_mod: float = 0.070
    fiber: float = 0.06
    fiber_mod: float = 0.08


@dataclass
class Look:
    geo: Geo = field(default_factory=Geo)
    grade: Grade = field(default_factory=Grade)
    flow: Flow = field(default_factory=Flow)
    trails: Trails = field(default_factory=Trails)
    glow: Glow = field(default_factory=Glow)
    grain: Grain = field(default_factory=Grain)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict | None) -> "Look":
        data = data or {}
        geo_data = dict(data.get("geo") or {})
        if geo_data.get("mode") not in GEO_MODE_INDEX:
            geo_data["mode"] = "none"
        return cls(
            geo=_take(Geo, geo_data),
            grade=_take(Grade, data.get("grade")),
            flow=_take(Flow, data.get("flow")),
            trails=_take(Trails, data.get("trails")),
            glow=_take(Glow, data.get("glow")),
            grain=_take(Grain, data.get("grain")),
        )

    @classmethod
    def load(cls, path: str | Path) -> "Look":
        raw = yaml.safe_load(Path(path).read_text()) or {}
        return cls.from_dict(raw)

    def save(self, path: str | Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(yaml.safe_dump(self.to_dict(), sort_keys=False))

    def replace(self, data: dict) -> None:
        """Mutate in place so the live stack picks up new values."""
        other = Look.from_dict(data)
        self.geo = other.geo
        self.grade = other.grade
        self.flow = other.flow
        self.trails = other.trails
        self.glow = other.glow
        self.grain = other.grain
