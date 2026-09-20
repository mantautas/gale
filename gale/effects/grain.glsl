#version 330
#include "common.glsl"

uniform sampler2D frame;
uniform vec2 resolution;
uniform float time;
uniform float grain;     // film grain amplitude
uniform float fiber;     // slow dirt / fiber overlay

in vec2 uv;
out vec3 color;

void main() {
    vec3 c = texture(frame, uv).rgb;
    float l = luma(c);

    vec2 pix = uv * resolution;
    // new grain every frame, slightly different per channel
    float n  = hash11(pix + vec2(time * 19.7, time * 13.3));
    float nr = hash11(pix + vec2(time * 23.1, 17.0));
    float nb = hash11(pix + vec2(7.0, time * 29.9));

    float shadow = mix(1.15, 0.35, smoothstep(0.0, 0.7, l));
    vec3 g = vec3(n, mix(n, nr, 0.4), mix(n, nb, 0.4)) - 0.5;
    c += g * grain * shadow;

    float dirt = fbm(uv * vec2(4.5, 7.0) + vec2(0.0, time * 0.015));
    c *= 1.0 + (dirt - 0.15) * fiber;

    color = clamp(c, 0.0, 1.0);
}
