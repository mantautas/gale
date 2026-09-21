#version 330
#include "common.glsl"

uniform sampler2D frame;
uniform vec2 resolution;
uniform float time;
uniform float mix_amt;
uniform float scanlines;
uniform float mask_amt;
uniform float curvature;
uniform float vignette;
uniform float bleed;

in vec2 uv;
out vec3 color;

vec2 barrel(vec2 st) {
    vec2 p = st * 2.0 - 1.0;
    float k = curvature * 0.55;
    p *= 1.0 + k * dot(p, p);
    return p * 0.5 + 0.5;
}

void main() {
    vec3 src = texture(frame, uv).rgb;
    if (mix_amt <= 0.001) {
        color = src;
        return;
    }

    vec2 st = barrel(uv);
    if (st.x < 0.0 || st.x > 1.0 || st.y < 0.0 || st.y > 1.0) {
        color = mix(src, vec3(0.0), clamp(mix_amt, 0.0, 1.0));
        return;
    }

    vec2 px = 1.0 / resolution;
    float b = bleed * 1.7;
    vec3 c;
    if (b < 0.001) {
        c = texture(frame, clamp(st, 0.001, 0.999)).rgb;
    } else {
        c = vec3(
            texture(frame, clamp(st + vec2(-px.x * b, 0.0), 0.001, 0.999)).r,
            texture(frame, clamp(st, 0.001, 0.999)).g,
            texture(frame, clamp(st + vec2(px.x * b, 0.0), 0.001, 0.999)).b
        );
    }

    float line = 0.5 + 0.5 * sin(st.y * resolution.y * 3.14159265);
    line = mix(1.0, mix(0.40, 1.0, line), clamp(scanlines, 0.0, 1.0));
    float wobble = 1.0 - 0.03 * clamp(scanlines, 0.0, 1.0) * sin(time * 7.3 + st.y * 11.0);
    c *= line * wobble;

    float tri = mod(st.x * resolution.x, 3.0);
    vec3 triad = vec3(float(tri < 1.0), float(tri >= 1.0 && tri < 2.0), float(tri >= 2.0));
    triad = triad * 1.35 + 0.22;
    c *= mix(vec3(1.0), triad, clamp(mask_amt, 0.0, 1.0));

    float vig = smoothstep(1.32, 0.28, length(uv * 2.0 - 1.0));
    c *= mix(1.0, vig, clamp(vignette, 0.0, 1.0));

    color = mix(src, clamp(c, 0.0, 1.0), clamp(mix_amt, 0.0, 1.0));
}
