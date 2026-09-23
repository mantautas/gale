"""Look parameters: YAML on disk, sliders in the play UI, uniforms at render.

`*_mod` fields are the extra amount added when the matching audio
feature is at 1.0. Set a mod to 0 to make that effect static.

`bindings` drive Auto/Mod for geo/overlay amount, count, scale, and trails.mix.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
import math

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

OVERLAY_MODES = [
    "none",
    "grid",
    "radar",
    "contours",
    "voronoi",
    "edges",
]
OVERLAY_MODE_INDEX = {name: i for i, name in enumerate(OVERLAY_MODES)}

SLICE_AXES = ["horizontal", "vertical"]
SLICE_AXIS_INDEX = {name: i for i, name in enumerate(SLICE_AXES)}

# First letter shifts forward, middle stays, last shifts back. rgb is the original split.
SLICE_SPLIT_COLORS = ["rgb", "rbg", "grb", "gbr", "brg", "bgr"]
SLICE_SPLIT_INDEX = {name: i for i, name in enumerate(SLICE_SPLIT_COLORS)}

AUTOMATION_MODES = ["none", "increasing", "decreasing", "wave"]
MODULATE_SOURCES = ["none", "rms", "low", "mid", "high", "energy", "beat", "onset", "kick"]

# UI group name → Look section attribute (for enable toggles).
SECTION_ATTR = {
    "Overlay": "overlay",
    "Geo": "geo",
    "Grade": "grade",
    "Flow": "flow",
    "Trails": "trails",
    "Glow": "glow",
    "Grain": "grain",
    "Halftone": "halftone",
    "CRT": "crt",
    "Slice": "slice",
}

# Slider schema for the play UI. `path` is dotted against Look.to_dict().
# `open` on the first row of a group is the default collapsed state.
# `bindable` marks rows that get Auto/Mod controls.
# `audio` marks sliders whose value is a soundtrack contribution (`*_mod`).
SLIDERS = [
    {"group": "Overlay", "open": True, "path": "overlay.mode", "label": "Mode", "type": "enum", "options": OVERLAY_MODES},
    {"group": "Overlay", "path": "overlay.mix", "label": "Mix", "min": 0.0, "max": 1.0, "step": 0.01},
    {
        "group": "Overlay",
        "path": "overlay.amount",
        "label": "Amount",
        "modes": "grid/contours/edges",
        "min": 0.0,
        "max": 1.0,
        "step": 0.01,
        "bindable": True,
    },
    {
        "group": "Overlay",
        "path": "overlay.count",
        "label": "Count",
        "modes": "grid/radar/contours",
        "min": 2.0,
        "max": 32.0,
        "step": 1.0,
        "bindable": True,
    },
    {
        "group": "Overlay",
        "path": "overlay.scale",
        "label": "Scale",
        "modes": "voronoi",
        "min": 0.5,
        "max": 12.0,
        "step": 0.1,
        "bindable": True,
    },
    {
        "group": "Overlay",
        "path": "overlay.line",
        "label": "Stroke",
        "modes": "grid/radar/contours/voronoi",
        "min": 0.0,
        "max": 1.0,
        "step": 0.01,
    },
    {"group": "Overlay", "path": "overlay.bright", "label": "Bright", "modes": "ink → light", "min": 0.0, "max": 1.0, "step": 0.01},
    {
        "group": "Overlay",
        "path": "overlay.speed",
        "label": "Drift",
        "modes": "grid/radar",
        "min": 0.0,
        "max": 1.0,
        "step": 0.01,
    },
    {
        "group": "Overlay",
        "path": "overlay.center_x",
        "label": "Center X",
        "modes": "grid/radar",
        "min": 0.0,
        "max": 1.0,
        "step": 0.01,
    },
    {
        "group": "Overlay",
        "path": "overlay.center_y",
        "label": "Center Y",
        "modes": "grid/radar",
        "min": 0.0,
        "max": 1.0,
        "step": 0.01,
    },
    {"group": "Geo", "open": True, "path": "geo.mode", "label": "Mode", "type": "enum", "options": GEO_MODES},
    {"group": "Geo", "path": "geo.mix", "label": "Mix", "min": 0.0, "max": 1.0, "step": 0.01},
    {
        "group": "Geo",
        "path": "geo.amount",
        "label": "Amount",
        "modes": "slices/polar/voronoi/fold/mosaic/luma/droste/hex",
        "min": 0.0,
        "max": 0.8,
        "step": 0.01,
        "bindable": True,
    },
    {
        "group": "Geo",
        "path": "geo.count",
        "label": "Count",
        "modes": "slices/polar/kaleido/mosaic/tiles",
        "min": 2.0,
        "max": 36.0,
        "step": 1.0,
        "bindable": True,
    },
    {
        "group": "Geo",
        "path": "geo.scale",
        "label": "Scale",
        "modes": "voronoi/fold/hex/droste",
        "min": 0.5,
        "max": 12.0,
        "step": 0.1,
        "bindable": True,
    },
    {
        "group": "Geo",
        "path": "geo.line",
        "label": "Lines",
        "modes": "slices/voronoi/mosaic/hex",
        "min": 0.0,
        "max": 1.0,
        "step": 0.01,
    },
    {
        "group": "Geo",
        "path": "geo.speed",
        "label": "Spin",
        "modes": "polar/kaleido/droste",
        "min": 0.0,
        "max": 1.0,
        "step": 0.01,
    },
    {
        "group": "Geo",
        "path": "geo.center_x",
        "label": "Center X",
        "modes": "polar/kaleido/luma/droste",
        "min": 0.0,
        "max": 1.0,
        "step": 0.01,
    },
    {
        "group": "Geo",
        "path": "geo.center_y",
        "label": "Center Y",
        "modes": "polar/kaleido/luma/droste",
        "min": 0.0,
        "max": 1.0,
        "step": 0.01,
    },
    {"group": "Grade", "open": False, "path": "grade.contrast", "label": "Contrast", "min": 0.7, "max": 1.8, "step": 0.01},
    {"group": "Grade", "path": "grade.saturation", "label": "Saturation", "min": 0.0, "max": 1.5, "step": 0.01},
    {"group": "Grade", "path": "grade.crush", "label": "Crush", "min": 0.8, "max": 1.4, "step": 0.01},
    {"group": "Flow", "open": False, "path": "flow.amount", "label": "Amount", "min": 0.0, "max": 0.08, "step": 0.001},
    {"group": "Flow", "path": "flow.amount_mod", "label": "Amount × energy", "min": 0.0, "max": 0.08, "step": 0.001, "audio": True},
    {"group": "Flow", "path": "flow.scale", "label": "Scale", "min": 0.4, "max": 8.0, "step": 0.1},
    {"group": "Flow", "path": "flow.speed", "label": "Speed", "min": 0.0, "max": 1.0, "step": 0.01},
    {"group": "Flow", "path": "flow.speed_mod", "label": "Speed × energy", "min": 0.0, "max": 1.0, "step": 0.01, "audio": True},
    {
        "group": "Trails",
        "open": False,
        "path": "trails.mix",
        "label": "Mix",
        "min": 0.0,
        "max": 1.0,
        "step": 0.01,
        "bindable": True,
    },
    {"group": "Trails", "path": "trails.decay", "label": "Decay", "min": 0.5, "max": 0.995, "step": 0.005},
    {
        "group": "Trails",
        "path": "trails.zoom",
        "label": "Zoom",
        "modes": "<1 expand / >1 recede",
        "min": 0.94,
        "max": 1.08,
        "step": 0.001,
    },
    {"group": "Trails", "path": "trails.angle", "label": "Spin", "min": -0.08, "max": 0.08, "step": 0.001},
    {"group": "Glow", "open": False, "path": "glow.threshold", "label": "Threshold", "min": 0.2, "max": 0.9, "step": 0.01},
    {"group": "Glow", "path": "glow.amount", "label": "Amount", "min": 0.0, "max": 1.2, "step": 0.01},
    {"group": "Glow", "path": "glow.amount_mod", "label": "Amount × RMS", "min": 0.0, "max": 1.2, "step": 0.01, "audio": True},
    {"group": "Grain", "open": False, "path": "grain.amount", "label": "Grain", "min": 0.0, "max": 0.2, "step": 0.005},
    {"group": "Grain", "path": "grain.amount_mod", "label": "Grain × RMS", "min": 0.0, "max": 0.2, "step": 0.005, "audio": True},
    {"group": "Grain", "path": "grain.fiber", "label": "Fiber", "min": 0.0, "max": 0.3, "step": 0.01},
    {"group": "Grain", "path": "grain.fiber_mod", "label": "Fiber × mids", "min": 0.0, "max": 0.3, "step": 0.01, "audio": True},
    {
        "group": "Halftone",
        "open": False,
        "path": "halftone.amount",
        "label": "Amount",
        "min": 0.0,
        "max": 1.0,
        "step": 0.01,
    },
    {
        "group": "Halftone",
        "path": "halftone.scale",
        "label": "Scale",
        "min": 0.5,
        "max": 12.0,
        "step": 0.1,
        "bindable": True,
    },
    {"group": "Halftone", "path": "halftone.angle", "label": "Angle", "min": 0.0, "max": 1.57, "step": 0.01},
    {"group": "Halftone", "path": "halftone.contrast", "label": "Contrast", "min": 0.0, "max": 1.0, "step": 0.01},
    {
        "group": "CRT",
        "open": False,
        "path": "crt.amount",
        "label": "Amount",
        "min": 0.0,
        "max": 1.0,
        "step": 0.01,
    },
    {
        "group": "CRT",
        "path": "crt.scanlines",
        "label": "Scanlines",
        "min": 0.0,
        "max": 1.0,
        "step": 0.01,
        "bindable": True,
    },
    {"group": "CRT", "path": "crt.mask", "label": "Mask", "min": 0.0, "max": 1.0, "step": 0.01},
    {"group": "CRT", "path": "crt.curvature", "label": "Curve", "min": 0.0, "max": 0.5, "step": 0.01},
    {"group": "CRT", "path": "crt.vignette", "label": "Vignette", "min": 0.0, "max": 1.0, "step": 0.01},
    {"group": "CRT", "path": "crt.bleed", "label": "Bleed", "min": 0.0, "max": 1.0, "step": 0.01},
    {"group": "Slice", "open": False, "path": "slice.axis", "label": "Axis", "type": "enum", "options": SLICE_AXES},
    {"group": "Slice", "path": "slice.mix", "label": "Mix", "min": 0.0, "max": 1.0, "step": 0.01},
    {
        "group": "Slice",
        "path": "slice.amount",
        "label": "Amount",
        "min": 0.0,
        "max": 0.5,
        "step": 0.005,
        "bindable": True,
    },
    {
        "group": "Slice",
        "path": "slice.count",
        "label": "Count",
        "min": 2.0,
        "max": 48.0,
        "step": 1.0,
        "bindable": True,
    },
    {"group": "Slice", "path": "slice.speed", "label": "Speed", "min": 0.0, "max": 1.0, "step": 0.01},
    {"group": "Slice", "path": "slice.color", "label": "Colors", "modes": "horizontal", "type": "toggle"},
    {"group": "Slice", "path": "slice.split", "label": "Split", "min": 0.0, "max": 1.0, "step": 0.01},
    {
        "group": "Slice",
        "path": "slice.colors",
        "label": "Colors",
        "modes": "lead · center · trail",
        "type": "enum",
        "options": SLICE_SPLIT_COLORS,
    },
]


def _take(cls, data: dict | None):
    valid = {f.name for f in fields(cls)}
    return cls(**{k: v for k, v in (data or {}).items() if k in valid})


@dataclass
class Overlay:
    enabled: bool = True
    mode: str = "none"
    mix: float = 0.45
    amount: float = 0.35
    amount_mod: float = 0.0
    count: float = 8.0
    scale: float = 4.0
    line: float = 0.35
    bright: float = 1.0
    speed: float = 0.04
    center_x: float = 0.5
    center_y: float = 0.5
    tint: list[float] = field(default_factory=lambda: [0.92, 0.84, 0.72])


@dataclass
class Geo:
    enabled: bool = True
    mode: str = "none"
    mix: float = 1.0
    amount: float = 0.18
    amount_mod: float = 0.0
    count: float = 8.0
    scale: float = 4.0
    line: float = 0.12
    speed: float = 0.04
    center_x: float = 0.5
    center_y: float = 0.5


@dataclass
class Grade:
    enabled: bool = True
    contrast: float = 1.12
    saturation: float = 0.82
    crush: float = 1.08
    shadow_tint: list[float] = field(default_factory=lambda: [0.86, 0.94, 1.05])
    highlight_tint: list[float] = field(default_factory=lambda: [1.06, 0.98, 0.90])


@dataclass
class Flow:
    enabled: bool = True
    amount: float = 0.006
    amount_mod: float = 0.018
    scale: float = 2.4
    speed: float = 0.12
    speed_mod: float = 0.20


@dataclass
class Trails:
    enabled: bool = True
    mix: float = 0.22
    mix_mod: float = 0.0
    decay: float = 0.96
    zoom: float = 0.988
    angle: float = 0.004
    hit_tau: float = 0.40


@dataclass
class Glow:
    enabled: bool = True
    threshold: float = 0.52
    knee: float = 0.28
    amount: float = 0.22
    amount_mod: float = 0.35
    tint: list[float] = field(default_factory=lambda: [1.0, 0.36, 0.14])


@dataclass
class Grain:
    enabled: bool = True
    amount: float = 0.045
    amount_mod: float = 0.070
    fiber: float = 0.06
    fiber_mod: float = 0.08


@dataclass
class Halftone:
    enabled: bool = False
    amount: float = 0.72
    scale: float = 4.2
    angle: float = 0.40
    contrast: float = 0.55


@dataclass
class Crt:
    enabled: bool = False
    amount: float = 1.0
    scanlines: float = 0.42
    mask: float = 0.28
    curvature: float = 0.10
    vignette: float = 0.22
    bleed: float = 0.18


@dataclass
class Slice:
    enabled: bool = False
    axis: str = "horizontal"
    mix: float = 1.0
    amount: float = 0.16
    count: float = 14.0
    speed: float = 0.22
    split: float = 0.40
    color: bool = True
    colors: str = "rgb"


@dataclass
class Binding:
    path: str
    automation: str = "none"
    modulate: str = "none"
    depth: float = 0.0


def _binding_from_dict(data: dict) -> Binding | None:
    path = data.get("path")
    if not path:
        return None
    automation = data.get("automation", "none")
    modulate = data.get("modulate", "none")
    if automation not in AUTOMATION_MODES:
        automation = "none"
    if modulate not in MODULATE_SOURCES:
        modulate = "none"
    return Binding(
        path=str(path),
        automation=automation,
        modulate=modulate,
        depth=float(data.get("depth", 0.0)),
    )


def auto_shape(automation: str, base: float, clip_u: float, lo: float, hi: float) -> float:
    """Clip-local automation shape. u in [0, 1]."""
    u = max(0.0, min(1.0, clip_u))
    if automation == "increasing":
        return base + (hi - base) * u
    if automation == "decreasing":
        return base + (lo - base) * u
    if automation == "wave":
        span = hi - lo
        if span <= 0:
            return base
        # One sine cycle; phase so u=0 lands on the parked slider.
        target = max(lo, min(hi, base))
        # value = lo + span * (0.5 + 0.5 * sin(2πu + φ))
        # at u=0: 0.5 + 0.5*sin(φ) = (base-lo)/span
        norm = (target - lo) / span
        sin_phi = max(-1.0, min(1.0, 2.0 * norm - 1.0))
        phi = math.asin(sin_phi)
        return lo + span * (0.5 + 0.5 * math.sin(2.0 * math.pi * u + phi))
    return base


def slider_range(path: str) -> tuple[float, float]:
    """min/max for a bindable path from SLIDERS schema."""
    for s in SLIDERS:
        if s.get("path") == path and "min" in s and "max" in s:
            return float(s["min"]), float(s["max"])
    raise KeyError(f"no slider range for {path}")


def get_path_value(look: "Look", path: str) -> float:
    cur: object = look
    for key in path.split("."):
        cur = getattr(cur, key)
    return float(cur)


def resolve_path(
    look: "Look",
    path: str,
    audio: float,
    clip_u: float,
) -> float:
    """Resolve one bindable path: auto_shape + depth × audio, clamped."""
    lo, hi = slider_range(path)
    base = get_path_value(look, path)
    return resolve_bound(base, look.binding_for(path), audio, clip_u, lo, hi)


def resolve_bound(
    base: float,
    binding: Binding | None,
    audio: float,
    clip_u: float,
    lo: float,
    hi: float,
) -> float:
    """output = auto_shape + depth × audio, clamped to [lo, hi]."""
    automation = binding.automation if binding else "none"
    modulate = binding.modulate if binding else "none"
    depth = binding.depth if binding else 0.0
    shaped = auto_shape(automation, base, clip_u, lo, hi)
    if modulate != "none" and depth:
        shaped = shaped + depth * audio
    return max(lo, min(hi, shaped))


def _migrate_mod_slider(
    section: dict,
    path: str,
    field: str,
    source: str,
    bindings: list[Binding],
) -> list[Binding]:
    """Old *_mod slider → binding if no binding yet."""
    if any(b.path == path for b in bindings):
        return bindings
    if field not in section:
        return bindings
    depth = float(section.get(field) or 0.0)
    if depth == 0.0:
        return bindings
    bindings = list(bindings)
    bindings.append(
        Binding(path=path, automation="none", modulate=source, depth=depth)
    )
    return bindings


@dataclass
class Look:
    overlay: Overlay = field(default_factory=Overlay)
    geo: Geo = field(default_factory=Geo)
    grade: Grade = field(default_factory=Grade)
    flow: Flow = field(default_factory=Flow)
    trails: Trails = field(default_factory=Trails)
    glow: Glow = field(default_factory=Glow)
    grain: Grain = field(default_factory=Grain)
    halftone: Halftone = field(default_factory=Halftone)
    crt: Crt = field(default_factory=Crt)
    slice: Slice = field(default_factory=Slice)
    bindings: list[Binding] = field(default_factory=list)

    def to_dict(self) -> dict:
        data = asdict(self)
        # Drop inert bindings so YAML stays clean.
        data["bindings"] = [
            b
            for b in data["bindings"]
            if b.get("automation", "none") != "none" or b.get("modulate", "none") != "none"
        ]
        return data

    def binding_for(self, path: str) -> Binding | None:
        for b in self.bindings:
            if b.path == path:
                return b
        return None

    def set_binding(self, binding: Binding) -> None:
        self.bindings = [b for b in self.bindings if b.path != binding.path]
        if binding.automation != "none" or binding.modulate != "none":
            self.bindings.append(binding)

    @classmethod
    def from_dict(cls, data: dict | None, *, migrate: bool = False) -> "Look":
        data = data or {}
        geo_data = dict(data.get("geo") or {})
        if geo_data.get("mode") not in GEO_MODE_INDEX:
            geo_data["mode"] = "none"
        overlay_data = dict(data.get("overlay") or {})
        if overlay_data.get("mode") not in OVERLAY_MODE_INDEX:
            overlay_data["mode"] = "none"
        slice_data = dict(data.get("slice") or {})
        if slice_data.get("axis") not in SLICE_AXIS_INDEX:
            slice_data["axis"] = "horizontal"
        if slice_data.get("colors") not in SLICE_SPLIT_INDEX:
            slice_data["colors"] = "rgb"
        bindings: list[Binding] = []
        for raw in data.get("bindings") or []:
            if isinstance(raw, dict):
                b = _binding_from_dict(raw)
                if b is not None:
                    bindings.append(b)
        if migrate:
            bindings = _migrate_mod_slider(geo_data, "geo.amount", "amount_mod", "energy", bindings)
            bindings = _migrate_mod_slider(overlay_data, "overlay.amount", "amount_mod", "energy", bindings)
            trails_data = dict(data.get("trails") or {})
            bindings = _migrate_mod_slider(trails_data, "trails.mix", "mix_mod", "kick", bindings)
        return cls(
            overlay=_take(Overlay, overlay_data),
            geo=_take(Geo, geo_data),
            grade=_take(Grade, data.get("grade")),
            flow=_take(Flow, data.get("flow")),
            trails=_take(Trails, data.get("trails")),
            glow=_take(Glow, data.get("glow")),
            grain=_take(Grain, data.get("grain")),
            halftone=_take(Halftone, data.get("halftone")),
            crt=_take(Crt, data.get("crt")),
            slice=_take(Slice, slice_data),
            bindings=bindings,
        )

    @classmethod
    def load(cls, path: str | Path) -> "Look":
        raw = yaml.safe_load(Path(path).read_text()) or {}
        return cls.from_dict(raw, migrate=True)

    def save(self, path: str | Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(yaml.safe_dump(self.to_dict(), sort_keys=False))

    def replace(self, data: dict) -> None:
        """Mutate in place so the live stack picks up new values."""
        other = Look.from_dict(data)
        self.overlay = other.overlay
        self.geo = other.geo
        self.grade = other.grade
        self.flow = other.flow
        self.trails = other.trails
        self.glow = other.glow
        self.grain = other.grain
        self.halftone = other.halftone
        self.crt = other.crt
        self.slice = other.slice
        self.bindings = other.bindings
