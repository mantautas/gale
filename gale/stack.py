"""The look: grade → curl flow → feedback trails → halation → grain.

Pulse/zoom is intentionally not in this stack. Music drives texture
density, warp amount, trail mix, and glow — not camera punches.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

import moderngl
import numpy as np

from gale.effects import load_effect
from gale.engine.gl import ShaderPass
from gale.look import GEO_MODE_INDEX, OVERLAY_MODE_INDEX, Look, resolve_path
from gale.timeline import Timeline

UniformFn = Callable[[float], dict]
BINDABLE_PATHS = (
    "geo.amount",
    "geo.count",
    "geo.scale",
    "overlay.amount",
    "overlay.count",
    "overlay.scale",
)


class Effect(Protocol):
    def apply(self, frame: moderngl.Texture, t: float) -> moderngl.Texture: ...
    def read(self) -> np.ndarray: ...


class Simple:
    def __init__(
        self,
        ctx: moderngl.Context,
        name: str,
        width: int,
        height: int,
        uniforms: UniformFn,
    ):
        self.width = width
        self.height = height
        self.pass_ = ShaderPass(ctx, load_effect(name), width, height)
        self.uniforms = uniforms

    def apply(self, frame: moderngl.Texture, t: float) -> moderngl.Texture:
        u = {
            "resolution": (float(self.width), float(self.height)),
            "time": t,
            **self.uniforms(t),
        }
        return self.pass_.render(uniforms=u, textures={"frame": frame})

    def read(self) -> np.ndarray:
        return self.pass_.read()


class Feedback:
    def __init__(
        self,
        ctx: moderngl.Context,
        width: int,
        height: int,
        uniforms: UniformFn,
    ):
        self.ctx = ctx
        self.pass_ = ShaderPass(ctx, load_effect("feedback"), width, height)
        self.uniforms = uniforms
        history = ctx.texture((width, height), 3)
        history.filter = (moderngl.LINEAR, moderngl.LINEAR)
        history.repeat_x = False
        history.repeat_y = False
        self.history_fbo = ctx.framebuffer(color_attachments=[history])
        self.history_fbo.clear(0.0, 0.0, 0.0)

    def reset(self) -> None:
        self.history_fbo.clear(0.0, 0.0, 0.0)

    def apply(self, frame: moderngl.Texture, t: float) -> moderngl.Texture:
        out = self.pass_.render(
            uniforms=self.uniforms(t),
            textures={"frame": frame, "history": self.history_fbo.color_attachments[0]},
        )
        self.ctx.copy_framebuffer(self.history_fbo, self.pass_.fbo)
        return out

    def read(self) -> np.ndarray:
        return self.pass_.read()


class Halation:
    def __init__(
        self,
        ctx: moderngl.Context,
        width: int,
        height: int,
        uniforms: UniformFn,
    ):
        self.width = width
        self.height = height
        self.uniforms = uniforms
        self.extract = ShaderPass(ctx, load_effect("highlights"), width, height)
        self.blur_h = ShaderPass(ctx, load_effect("blur"), width, height)
        self.blur_v = ShaderPass(ctx, load_effect("blur"), width, height)
        self.comp = ShaderPass(ctx, load_effect("halation"), width, height)

    def apply(self, frame: moderngl.Texture, t: float) -> moderngl.Texture:
        u = self.uniforms(t)
        hi = self.extract.render(
            uniforms={"threshold": u.get("threshold", 0.55), "knee": u.get("knee", 0.25)},
            textures={"frame": frame},
        )
        dx = 1.0 / self.width
        dy = 1.0 / self.height
        h = self.blur_h.render(uniforms={"direction": (dx, 0.0)}, textures={"frame": hi})
        # extra blur pass pair so the glow is soft, not a sparkle
        v = self.blur_v.render(uniforms={"direction": (0.0, dy)}, textures={"frame": h})
        h2 = self.blur_h.render(uniforms={"direction": (dx * 2.0, 0.0)}, textures={"frame": v})
        v2 = self.blur_v.render(uniforms={"direction": (0.0, dy * 2.0)}, textures={"frame": h2})
        return self.comp.render(
            uniforms={
                "amount": u.get("amount", 0.35),
                "tint": u.get("tint", (1.0, 0.38, 0.16)),
            },
            textures={"frame": frame, "bloom": v2},
        )

    def read(self) -> np.ndarray:
        return self.comp.read()


class Stack:
    def __init__(
        self,
        steps: list[tuple[Effect, Callable[[], bool]]],
        clip_state: dict | None = None,
        fallback: Effect | None = None,
    ):
        self.steps = steps
        self._clip_state = clip_state if clip_state is not None else {"clip_u": 0.0}
        self._fallback = fallback
        self._last: Effect | None = fallback

    @property
    def effects(self) -> list[Effect]:
        return [effect for effect, _ in self.steps]

    @property
    def clip_u(self) -> float:
        return float(self._clip_state.get("clip_u", 0.0))

    def apply(
        self,
        frame: moderngl.Texture,
        t: float,
        clip_u: float = 0.0,
    ) -> moderngl.Texture:
        self._clip_state["clip_u"] = float(clip_u)
        current = frame
        self._last = None
        for effect, enabled in self.steps:
            if not enabled():
                continue
            current = effect.apply(current, t)
            self._last = effect
        if self._last is None:
            if self._fallback is None:
                raise RuntimeError("stack has no enabled effects and no fallback")
            current = self._fallback.apply(current, t)
            self._last = self._fallback
        return current

    def reset(self) -> None:
        for effect, _ in self.steps:
            reset = getattr(effect, "reset", None)
            if reset:
                reset()

    def read(self) -> np.ndarray:
        assert self._last is not None
        return self._last.read()


def resolve_bindings(
    params: Look,
    tl: Timeline | None,
    song_t: float,
    clip_u: float,
    paths: tuple[str, ...] = BINDABLE_PATHS,
) -> dict[str, float]:
    """Same formula Frame / Keep / Loop / gale-render use for bindable params."""
    out: dict[str, float] = {}
    for path in paths:
        binding = params.binding_for(path)
        audio = 0.0
        if tl is not None and binding is not None and binding.modulate != "none":
            audio = tl.audio(binding.modulate, song_t)
        out[path] = resolve_path(params, path, audio, clip_u)
    return out


def build_look(
    ctx: moderngl.Context,
    analysis_path: str | None,
    width: int,
    height: int,
    fps: float,
    params: Look | None = None,
) -> Stack:
    clip_state = {"clip_u": 0.0}
    fallback = Simple(ctx, "passthrough", width, height, lambda t: {})
    if analysis_path is None:
        return Stack([(fallback, lambda: True)], clip_state, fallback)

    tl = Timeline(analysis_path, fps)
    params = params or Look()

    def grade(_t: float) -> dict:
        g = params.grade
        return {
            "contrast": g.contrast,
            "saturation": g.saturation,
            "crush": g.crush,
            "shadow_tint": tuple(g.shadow_tint),
            "highlight_tint": tuple(g.highlight_tint),
        }

    def geo(t: float) -> dict:
        g = params.geo
        resolved = resolve_bindings(params, tl, t, float(clip_state["clip_u"]))
        return {
            "mode": int(GEO_MODE_INDEX.get(g.mode, 0)),
            "mix_amt": 0.0 if g.mode == "none" else g.mix,
            "amount": resolved["geo.amount"],
            "scale": resolved["geo.scale"],
            "count": resolved["geo.count"],
            "line_amt": g.line,
            "speed": g.speed,
            "center": (g.center_x, g.center_y),
        }

    def flow(t: float) -> dict:
        energy = tl.audio("energy", t)
        f = params.flow
        return {
            "amount": f.amount + f.amount_mod * energy,
            "scale": f.scale,
            "speed": f.speed + f.speed_mod * energy,
        }

    def trails(t: float) -> dict:
        tr = params.trails
        hit = tl.onset_pulse(t, "low", tau=tr.hit_tau)
        return {
            "mix_amt": tr.mix + tr.mix_mod * hit,
            "decay": tr.decay,
            "zoom": tr.zoom,
            "angle": tr.angle,
        }

    def glow(t: float) -> dict:
        gl = params.glow
        return {
            "threshold": gl.threshold,
            "knee": gl.knee,
            "amount": gl.amount + gl.amount_mod * tl.value("rms", t),
            "tint": tuple(gl.tint),
        }

    def overlay(t: float) -> dict:
        o = params.overlay
        resolved = resolve_bindings(params, tl, t, float(clip_state["clip_u"]))
        return {
            "mode": int(OVERLAY_MODE_INDEX.get(o.mode, 0)),
            "mix_amt": 0.0 if o.mode == "none" else o.mix,
            "amount": resolved["overlay.amount"],
            "line_amt": o.line,
            "scale": resolved["overlay.scale"],
            "count": resolved["overlay.count"],
            "speed": o.speed,
            "bright": o.bright,
            "center": (o.center_x, o.center_y),
            "tint": tuple(o.tint),
        }

    def grain(t: float) -> dict:
        gr = params.grain
        return {
            "grain": gr.amount + gr.amount_mod * tl.value("rms", t),
            "fiber": gr.fiber + gr.fiber_mod * tl.value("mid", t),
        }

    return Stack(
        [
            (Simple(ctx, "grade", width, height, grade), lambda: params.grade.enabled),
            (Simple(ctx, "geo", width, height, geo), lambda: params.geo.enabled and params.geo.mode != "none"),
            (Simple(ctx, "curl_flow", width, height, flow), lambda: params.flow.enabled),
            (Feedback(ctx, width, height, trails), lambda: params.trails.enabled),
            (Halation(ctx, width, height, glow), lambda: params.glow.enabled),
            (Simple(ctx, "overlay", width, height, overlay), lambda: params.overlay.enabled and params.overlay.mode != "none"),
            (Simple(ctx, "grain", width, height, grain), lambda: params.grain.enabled),
        ],
        clip_state,
        fallback,
    )
