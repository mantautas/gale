#version 330
#include "common.glsl"

uniform sampler2D frame;
uniform sampler2D history;
uniform float mix_amt;   // 0 = current only, 1 = full trail
uniform float decay;
uniform float zoom;      // <1 expands trails, >1 recedes toward center
uniform float angle;     // radians of history rotation

in vec2 uv;
out vec3 color;

void main() {
    float ca = cos(angle);
    float sa = sin(angle);
    vec2 p = uv - 0.5;
    p = mat2(ca, -sa, sa, ca) * p;

    float z = max(zoom, 0.5);
    vec2 p1 = p / z + 0.5;
    // second tap stretches further in the same direction so ghosts run longer
    float z2 = max(mix(1.0, zoom, 2.2), 0.5);
    vec2 p2 = p / z2 + 0.5;

    vec3 curr = texture(frame, uv).rgb;
    vec3 prev1 = texture(history, clamp(p1, 0.001, 0.999)).rgb;
    vec3 prev2 = texture(history, clamp(p2, 0.001, 0.999)).rgb;
    vec3 prev = max(prev1, prev2) * decay;

    // lighten keeps dark areas relatively clean; screen fattens highlight ghosts
    vec3 lighten = max(curr, prev);
    vec3 screen = curr + prev - curr * prev;
    vec3 trail = mix(lighten, screen, 0.42);
    color = mix(curr, trail, clamp(mix_amt, 0.0, 1.0));
}
