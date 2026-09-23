#version 330
#include "common.glsl"

// Turbulent volume, adapted from https://www.shadertoy.com/view/N3G3Dz
// The march displaces samples of the camera frame, so the footage is the volume.

uniform sampler2D frame;
uniform vec2 resolution;
uniform float time;
uniform float mix_amt;
uniform float amount;   // turbulence amplitude
uniform float scale;    // warp frequency
uniform float speed;
uniform float steps;

in vec2 uv;
out vec3 color;

mat2 rot(float angle) {
    float c = cos(angle);
    float s = sin(angle);
    return mat2(c, s, -s, c);
}

vec3 turb(vec3 p, float oct, float f, float amp) {
    for (float i = 0.0; i < oct; i++) {
        p.xy *= rot(amp * sin(f * p.z + i));
        p.yz *= rot(amp * sin(f * p.x + i + 1.234));
        p.zx *= rot(amp * sin(f * p.y + i + 2.468));
        f += f;
        amp *= 0.5;
    }
    return p;
}

void main() {
    vec2 suv = (uv * 2.0 - 1.0) * vec2(resolution.x / resolution.y, 1.0);

    float focal = 2.0;
    vec3 ro = vec3(0.0, 0.0, 3.0);
    vec3 rd = normalize(vec3(suv, -focal));

    float spin = time * speed;
    float c = cos(spin);
    float s = sin(spin);
    mat2 R = mat2(c, s, -s, c);
    ro.xz *= R;
    rd.xz *= R;
    ro.zy *= R;
    rd.zy *= R;

    float amp = mix(0.6, 2.8, clamp(amount, 0.0, 1.0));
    float freq = max(scale, 0.2);
    float limit = clamp(steps, 8.0, 96.0);

    float t = 0.4 * fract(
        dot(suv - 1.0, suv + 1.0) * 10.0
        + 1121.321 * sin(2.4 * fract(time) + dot(suv, vec2(111.3461, 95.6541)))
    );
    float aspect = resolution.x / max(resolution.y, 1.0);
    float best = 0.0;
    vec2 best_shift = vec2(0.0);
    for (int i = 0; i < 96; i++) {
        if (float(i) >= limit || t >= 1000.0) break;
        vec3 p = rd * t + ro;
        vec3 q = p;
        p = turb(p + s * 0.1, 3.0, freq, amp);

        float sdf = length(p + s * 0.2 - 1.0) - 1.0;
        sdf = max(sdf, length(q) - 2.25);
        sdf = max(sdf, dot(q, ro) + length(q) * 0.11);

        float dt = max(sdf, 0.0) * 0.04 + 5e-3;
        t += dt;

        float kernel = 0.1 / (dt + sdf * sdf * abs(sdf));
        float k = kernel * dt;
        if (k > best) {
            best = k;
            best_shift = (p.xy - q.xy);
            best_shift.x /= aspect;
        }
    }

    vec2 sample_uv = clamp(uv + best_shift * 0.16 * clamp(mix_amt, 0.0, 1.0), 0.001, 0.999);
    color = texture(frame, sample_uv).rgb;
}
