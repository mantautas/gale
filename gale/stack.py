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
from gale.engine.gl import VERT, ShaderPass
from gale.look import GEO_MODE_INDEX, OVERLAY_MODE_INDEX, SLICE_AXIS_INDEX, SLICE_SPLIT_INDEX, Look, resolve_path
from gale.timeline import Timeline

UniformFn = Callable[[float], dict]
BINDABLE_PATHS = (
    "geo.amount",
    "geo.count",
    "geo.scale",
    "overlay.amount",
    "overlay.count",
    "overlay.scale",
    "overlay.speed",
    "overlay.irregular",
    "trails.mix",
    "halftone.scale",
    "crt.scanlines",
    "slice.amount",
    "slice.count",
    "turb.amount",
    "smoke.amount",
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


def _float_field(ctx: moderngl.Context, width: int, height: int) -> moderngl.Texture:
    tex = ctx.texture((width, height), 4, dtype="f2")
    tex.filter = (moderngl.LINEAR, moderngl.LINEAR)
    tex.repeat_x = False
    tex.repeat_y = False
    return tex


class Smoke:
    """Half-resolution fluid. Three solver steps and one dye step per frame."""

    def __init__(
        self,
        ctx: moderngl.Context,
        width: int,
        height: int,
        uniforms: UniformFn,
    ):
        self.ctx = ctx
        self.uniforms = uniforms
        self.sim_size = (max(2, width // 2), max(2, height // 2))
        sw, sh = self.sim_size
        quad = ctx.buffer(np.array([-1, -1, 1, -1, -1, 1, 1, 1], dtype="f4"))
        self.sim_prog = ctx.program(vertex_shader=VERT, fragment_shader=load_effect("smoke_sim"))
        self.dye_prog = ctx.program(vertex_shader=VERT, fragment_shader=load_effect("smoke_dye"))
        self.sim_vao = ctx.vertex_array(self.sim_prog, [(quad, "2f", "in_pos")])
        self.dye_vao = ctx.vertex_array(self.dye_prog, [(quad, "2f", "in_pos")])
        self.vel = [_float_field(ctx, sw, sh) for _ in range(2)]
        self.dye = [_float_field(ctx, sw, sh) for _ in range(2)]
        self.vel_fbo = [ctx.framebuffer(color_attachments=[tex]) for tex in self.vel]
        self.dye_fbo = [ctx.framebuffer(color_attachments=[tex]) for tex in self.dye]
        self.comp = ShaderPass(ctx, load_effect("smoke"), width, height)
        self._vel_i = 0
        self._dye_i = 0
        self.reset()

    def reset(self) -> None:
        for fbo in self.vel_fbo:
            fbo.clear(0.0, 0.0, 0.5, 0.0)
        for fbo in self.dye_fbo:
            fbo.clear(0.0, 0.0, 0.0, 1.0)
        self._vel_i = 0
        self._dye_i = 0

    def _draw(self, prog, vao, dst, textures: dict, uniforms: dict) -> None:
        dst.use()
        unit = 0
        for name, tex in textures.items():
            if name not in prog:
                continue
            tex.use(unit)
            prog[name].value = unit
            unit += 1
        for name, value in uniforms.items():
            if name in prog:
                prog[name].value = value
        vao.render(moderngl.TRIANGLE_STRIP)

    def apply(self, frame: moderngl.Texture, t: float) -> moderngl.Texture:
        u = self.uniforms(t)
        sw, sh = self.sim_size
        sim_u = {
            "resolution": (float(sw), float(sh)),
            "motion": t * (0.15 + float(u.get("speed", 0.4)) * 1.1),
            "amount": float(u.get("amount", 0.75)),
            "vorticity": float(u.get("vorticity", 0.11)),
        }
        for _ in range(3):
            src_i = self._vel_i
            dst_i = 1 - src_i
            self._draw(self.sim_prog, self.sim_vao, self.vel_fbo[dst_i], {"field": self.vel[src_i]}, sim_u)
            self._vel_i = dst_i
        dye_u = {
            "resolution": (float(sw), float(sh)),
            "motion": sim_u["motion"],
            "amount": sim_u["amount"],
            "fade": float(u.get("fade", 0.25)),
        }
        src_d = self._dye_i
        dst_d = 1 - src_d
        self._draw(
            self.dye_prog,
            self.dye_vao,
            self.dye_fbo[dst_d],
            {"field": self.vel[self._vel_i], "dye": self.dye[src_d]},
            dye_u,
        )
        self._dye_i = dst_d
        return self.comp.render(
            uniforms={"mix_amt": float(u.get("mix_amt", 0.55))},
            textures={"frame": frame, "smoke": self.dye[self._dye_i]},
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

    def slice_shift(t: float) -> dict:
        s = params.slice
        resolved = resolve_bindings(params, tl, t, float(clip_state["clip_u"]))
        return {
            "mix_amt": s.mix,
            "amount": resolved["slice.amount"],
            "count": resolved["slice.count"],
            "speed": s.speed,
            "split": s.split,
            "axis": int(SLICE_AXIS_INDEX.get(s.axis, 0)),
            "colors": int(SLICE_SPLIT_INDEX.get(s.colors, 0)),
            "color_on": 0 if s.axis == "horizontal" and not s.color else 1,
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
        resolved = resolve_bindings(params, tl, t, float(clip_state["clip_u"]))
        return {
            "mix_amt": resolved["trails.mix"],
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
            "speed": resolved["overlay.speed"],
            "bright": o.bright,
            "radius": o.radius,
            "irregular": resolved["overlay.irregular"],
            "center": (o.center_x, o.center_y),
            "tint": tuple(o.tint),
        }

    def grain(t: float) -> dict:
        gr = params.grain
        return {
            "grain": gr.amount + gr.amount_mod * tl.value("rms", t),
            "fiber": gr.fiber + gr.fiber_mod * tl.value("mid", t),
        }

    def halftone(t: float) -> dict:
        h = params.halftone
        resolved = resolve_bindings(params, tl, t, float(clip_state["clip_u"]))
        return {
            "mix_amt": h.amount,
            "scale": resolved["halftone.scale"],
            "angle": h.angle,
            "contrast": h.contrast,
        }

    def crt(t: float) -> dict:
        c = params.crt
        resolved = resolve_bindings(params, tl, t, float(clip_state["clip_u"]))
        return {
            "mix_amt": c.amount,
            "scanlines": resolved["crt.scanlines"],
            "mask_amt": c.mask,
            "curvature": c.curvature,
            "vignette": c.vignette,
            "bleed": c.bleed,
        }

    def turb(t: float) -> dict:
        tb = params.turb
        resolved = resolve_bindings(params, tl, t, float(clip_state["clip_u"]))
        return {
            "mix_amt": tb.mix,
            "amount": resolved["turb.amount"],
            "scale": tb.scale,
            "speed": tb.speed,
            "steps": tb.steps,
        }

    def smoke(t: float) -> dict:
        sm = params.smoke
        resolved = resolve_bindings(params, tl, t, float(clip_state["clip_u"]))
        return {
            "mix_amt": sm.mix,
            "amount": resolved["smoke.amount"],
            "speed": sm.speed,
            "vorticity": sm.vorticity,
            "fade": sm.fade,
        }

    return Stack(
        [
            (Simple(ctx, "grade", width, height, grade), lambda: params.grade.enabled),
            (Simple(ctx, "geo", width, height, geo), lambda: params.geo.enabled and params.geo.mode != "none"),
            (Simple(ctx, "slice", width, height, slice_shift), lambda: params.slice.enabled),
            (Simple(ctx, "curl_flow", width, height, flow), lambda: params.flow.enabled),
            (Feedback(ctx, width, height, trails), lambda: params.trails.enabled),
            (Halation(ctx, width, height, glow), lambda: params.glow.enabled),
            (Simple(ctx, "overlay", width, height, overlay), lambda: params.overlay.enabled and params.overlay.mode != "none"),
            (Simple(ctx, "halftone", width, height, halftone), lambda: params.halftone.enabled),
            (Simple(ctx, "turb", width, height, turb), lambda: params.turb.enabled),
            (Smoke(ctx, width, height, smoke), lambda: params.smoke.enabled),
            (Simple(ctx, "grain", width, height, grain), lambda: params.grain.enabled),
            (Simple(ctx, "crt", width, height, crt), lambda: params.crt.enabled),
        ],
        clip_state,
        fallback,
    )
