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
from gale.look import Look
from gale.timeline import Timeline

UniformFn = Callable[[float], dict]


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
    def __init__(self, effects: list[Effect]):
        self.effects = effects

    def apply(self, frame: moderngl.Texture, t: float) -> moderngl.Texture:
        current = frame
        for effect in self.effects:
            current = effect.apply(current, t)
        return current

    def reset(self) -> None:
        for effect in self.effects:
            reset = getattr(effect, "reset", None)
            if reset:
                reset()

    def read(self) -> np.ndarray:
        return self.effects[-1].read()


def build_look(
    ctx: moderngl.Context,
    analysis_path: str | None,
    width: int,
    height: int,
    fps: float,
    params: Look | None = None,
) -> Stack:
    if analysis_path is None:
        return Stack([Simple(ctx, "passthrough", width, height, lambda t: {})])

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

    def flow(t: float) -> dict:
        energy = 0.6 * tl.value("low", t) + 0.4 * tl.value("mid", t)
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

    def grain(t: float) -> dict:
        gr = params.grain
        return {
            "grain": gr.amount + gr.amount_mod * tl.value("rms", t),
            "fiber": gr.fiber + gr.fiber_mod * tl.value("mid", t),
        }

    return Stack(
        [
            Simple(ctx, "grade", width, height, grade),
            Simple(ctx, "curl_flow", width, height, flow),
            Feedback(ctx, width, height, trails),
            Halation(ctx, width, height, glow),
            Simple(ctx, "grain", width, height, grain),
        ]
    )
