#version 330
#include "common.glsl"

uniform sampler2D frame;
uniform float contrast;
uniform float saturation;
uniform float crush;          // >1 darkens mids/shadows
uniform vec3 shadow_tint;     // cool
uniform vec3 highlight_tint;  // warm — protects the lantern

in vec2 uv;
out vec3 color;

void main() {
    vec3 c = texture(frame, uv).rgb;
    float l = luma(c);

    c = pow(max(c, 0.0), vec3(crush));
    c = (c - 0.5) * contrast + 0.5;
    c = mix(vec3(luma(c)), c, saturation);

    float w = smoothstep(0.12, 0.62, l);
    c *= mix(shadow_tint, highlight_tint, w);

    color = clamp(c, 0.0, 1.0);
}
