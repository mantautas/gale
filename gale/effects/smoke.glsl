#version 330
#include "common.glsl"

uniform sampler2D frame;
uniform sampler2D smoke;
uniform float mix_amt;

in vec2 uv;
out vec3 color;

void main() {
    vec3 src = texture(frame, uv).rgb;
    vec3 dye = texture(smoke, uv).rgb;
    vec3 haze = 1.0 - exp(-dye * 2.4);
    vec3 lifted = clamp(src + haze, 0.0, 1.0);
    color = mix(src, lifted, clamp(mix_amt, 0.0, 1.0));
}
