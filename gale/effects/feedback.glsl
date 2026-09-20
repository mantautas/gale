#version 330
#include "common.glsl"

uniform sampler2D frame;
uniform sampler2D history;
uniform float mix_amt;   // 0 = current only, ~0.3 = visible trails
uniform float decay;
uniform float zoom;      // >1 recedes trails toward center
uniform float angle;     // radians of history rotation

in vec2 uv;
out vec3 color;

void main() {
    float ca = cos(angle);
    float sa = sin(angle);
    vec2 p = uv - 0.5;
    p = mat2(ca, -sa, sa, ca) * p;
    p = p / zoom + 0.5;

    vec3 curr = texture(frame, uv).rgb;
    vec3 prev = texture(history, clamp(p, 0.0, 1.0)).rgb * decay;

    // lighten-blend: highlights (lantern, foam) persist; dark sea stays clean
    vec3 trail = max(curr, prev);
    color = mix(curr, trail, mix_amt);
}
