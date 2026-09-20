"""OpenGL context + fullscreen-quad shader pass helpers.

macOS has no headless GL, so we create a hidden GLFW window to host the
context. Everything renders offscreen into FBOs regardless.
"""

from __future__ import annotations

import glfw
import moderngl
import numpy as np

_window = None  # keep a reference so GLFW doesn't GC the window

VERT = """\
#version 330
in vec2 in_pos;
out vec2 uv;
void main() {
    uv = in_pos * 0.5 + 0.5;
    gl_Position = vec4(in_pos, 0.0, 1.0);
}
"""


def create_context() -> moderngl.Context:
    global _window
    if not glfw.init():
        raise RuntimeError("glfw.init() failed")
    glfw.window_hint(glfw.VISIBLE, glfw.FALSE)
    glfw.window_hint(glfw.CONTEXT_VERSION_MAJOR, 4)
    glfw.window_hint(glfw.CONTEXT_VERSION_MINOR, 1)
    glfw.window_hint(glfw.OPENGL_PROFILE, glfw.OPENGL_CORE_PROFILE)
    glfw.window_hint(glfw.OPENGL_FORWARD_COMPAT, True)
    _window = glfw.create_window(64, 64, "gale", None, None)
    if not _window:
        glfw.terminate()
        raise RuntimeError("failed to create hidden GL window")
    glfw.make_context_current(_window)
    return moderngl.create_context()


class ShaderPass:
    """One fullscreen-quad fragment shader rendering into its own FBO.

    Textures are bound by name (sampler uniforms), uniforms set by name;
    missing uniforms in the shader are silently skipped so effect params
    can be a superset of what a given shader uses.
    """

    def __init__(
        self,
        ctx: moderngl.Context,
        frag_src: str,
        width: int,
        height: int,
    ):
        self.ctx = ctx
        self.prog = ctx.program(vertex_shader=VERT, fragment_shader=frag_src)
        quad = np.array([-1, -1, 1, -1, -1, 1, 1, 1], dtype="f4")
        self.vbo = ctx.buffer(quad.tobytes())
        self.vao = ctx.vertex_array(self.prog, [(self.vbo, "2f", "in_pos")])
        color = ctx.texture((width, height), 3)
        color.filter = (moderngl.LINEAR, moderngl.LINEAR)
        color.repeat_x = False
        color.repeat_y = False
        self.fbo = ctx.framebuffer(color_attachments=[color])

    def render(
        self,
        uniforms: dict | None = None,
        textures: dict[str, moderngl.Texture] | None = None,
    ) -> moderngl.Texture:
        self.fbo.use()
        unit = 0
        for name, tex in (textures or {}).items():
            if name not in self.prog:
                continue
            tex.use(unit)
            self.prog[name] = unit
            unit += 1
        for name, value in (uniforms or {}).items():
            if name in self.prog:
                self.prog[name].value = value
        self.vao.render(moderngl.TRIANGLE_STRIP)
        return self.fbo.color_attachments[0]

    def read(self) -> np.ndarray:
        """Read back the FBO as (H, W, 3) uint8, top row first."""
        w, h = self.fbo.size
        data = self.fbo.color_attachments[0].read()
        arr = np.frombuffer(data, np.uint8).reshape((h, w, 3))
        return np.ascontiguousarray(arr[::-1])  # GL reads bottom-up
