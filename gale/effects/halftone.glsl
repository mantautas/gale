#version 330
#include "common.glsl"

uniform sampler2D frame;
uniform vec2 resolution;
uniform float time;
uniform float mix_amt;
uniform float scale;     // larger = coarser dots
uniform float angle;     // radians
uniform float contrast;

in vec2 uv;
out vec3 color;

void main() {
    vec3 src = texture(frame, uv).rgb;
    if (mix_amt <= 0.001) {
        color = src;
        return;
    }

    float l = luma(src);
    vec2 p = (uv - 0.5) * vec2(resolution.x / max(resolution.y, 1.0), 1.0);
    float ca = cos(angle);
    float sa = sin(angle);
    p = mat2(ca, -sa, sa, ca) * p;

    float cell = mix(0.016, 0.12, clamp((scale - 0.5) / 11.5, 0.0, 1.0));
    vec2 f = fract(p / max(cell, 0.004)) - 0.5;
    float dist = length(f) * 1.41421356;

    float tone = pow(clamp(l, 0.0, 1.0), mix(0.75, 1.55, clamp(contrast, 0.0, 1.0)));
    float radius = mix(0.92, 0.04, tone);
    float hard = mix(0.16, 0.035, clamp(contrast, 0.0, 1.0));
    float ink = 1.0 - smoothstep(radius, radius + hard, dist);

    vec3 paper = mix(src, vec3(l), 0.22) * vec3(1.04, 1.02, 0.98);
    vec3 blot = src * vec3(0.10, 0.09, 0.08);
    vec3 ht = mix(paper, blot, ink);
    color = mix(src, ht, clamp(mix_amt, 0.0, 1.0));
}
