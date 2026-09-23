#version 330

// Velocity / density / curl step from Chimera's Breath (nimitz, 2018),
// based on Guay, Colin, Egli, "Simple and fast fluids".
// xy velocity, z density, w curl. No mouse drawing.

uniform sampler2D field;
uniform vec2 resolution;
uniform float motion;
uniform float amount;
uniform float vorticity;

in vec2 uv;
out vec4 fluid;

const float DT = 0.15;

float mag2(vec2 p) { return dot(p, p); }

vec2 point1(float t) {
    t *= 0.62;
    return vec2(0.18, 0.42 + sin(t) * 0.18);
}

vec2 point2(float t) {
    t *= 0.62;
    return vec2(0.78, 0.58 + cos(t + 1.5708) * 0.16);
}

void main() {
    vec2 w = 1.0 / resolution;
    const float K = 0.2;
    const float visc = 0.55;

    vec4 data = textureLod(field, uv, 0.0);
    vec4 tr = textureLod(field, uv + vec2(w.x, 0.0), 0.0);
    vec4 tl = textureLod(field, uv - vec2(w.x, 0.0), 0.0);
    vec4 tu = textureLod(field, uv + vec2(0.0, w.y), 0.0);
    vec4 td = textureLod(field, uv - vec2(0.0, w.y), 0.0);

    vec3 dx = (tr.xyz - tl.xyz) * 0.5;
    vec3 dy = (tu.xyz - td.xyz) * 0.5;
    vec2 dens_dif = vec2(dx.z, dy.z);

    data.z -= DT * dot(vec3(dens_dif, dx.x + dy.y), data.xyz);

    vec2 laplacian = tu.xy + td.xy + tr.xy + tl.xy - 4.0 * data.xy;
    vec2 visc_force = vec2(visc) * laplacian;
    data.xyw = textureLod(field, uv - DT * data.xy * w, 0.0).xyw;

    float push = max(amount, 0.0);
    vec2 force = push * vec2(0.0003, 0.00015) / (mag2(uv - point1(motion)) + 0.0001);
    force -= push * vec2(0.0003, 0.00015) / (mag2(uv - point2(motion)) + 0.0001);

    data.xy += DT * (visc_force - K / DT * dens_dif + force);
    data.xy = max(vec2(0.0), abs(data.xy) - 1e-4) * sign(data.xy);

    data.w = tr.y - tl.y - tu.x + td.x;
    vec2 vort = vec2(abs(tu.w) - abs(td.w), abs(tl.w) - abs(tr.w));
    vort *= vorticity / length(vort + 1e-9) * data.w;
    data.xy += vort;

    data.y *= smoothstep(0.5, 0.48, abs(uv.y - 0.5));
    fluid = clamp(data, vec4(vec2(-10.0), 0.5, -10.0), vec4(vec2(10.0), 3.0, 10.0));
}
