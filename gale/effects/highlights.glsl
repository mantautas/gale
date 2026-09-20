#version 330
#include "common.glsl"

uniform sampler2D frame;
uniform float threshold;
uniform float knee;

in vec2 uv;
out vec3 color;

void main() {
    vec3 c = texture(frame, uv).rgb;
    float l = luma(c);
    float w = smoothstep(threshold, threshold + knee, l);
    color = c * w;
}
