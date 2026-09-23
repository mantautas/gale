#version 330

// Dye carried by the fluid. Warm gray, not the Shadertoy palette.

uniform sampler2D field;
uniform sampler2D dye;
uniform vec2 resolution;
uniform float motion;
uniform float amount;
uniform float fade;

in vec2 uv;
out vec4 fluid;

const float DT = 0.15;

vec2 point1(float t) {
    t *= 0.62;
    return vec2(0.18, 0.42 + sin(t) * 0.18);
}

vec2 point2(float t) {
    t *= 0.62;
    return vec2(0.78, 0.58 + cos(t + 1.5708) * 0.16);
}

float puff(vec2 p) {
    return 0.0025 / (0.0005 + pow(length(p), 1.75));
}

void main() {
    vec2 w = 1.0 / resolution;
    vec2 velo = textureLod(field, uv, 0.0).xy;
    vec3 col = textureLod(dye, uv - DT * velo * w * 3.0, 0.0).rgb;

    float push = max(amount, 0.0) * DT * 0.12;
    vec3 tone = vec3(0.86, 0.84, 0.78);
    col += puff(uv - point1(motion)) * push * tone;
    col += puff(uv - point2(motion)) * push * tone * 0.85;

    float fall = mix(0.0015, 0.06, clamp(fade, 0.0, 1.0));
    col = max(col - (fall + col * fall) * 0.5, 0.0);
    fluid = vec4(clamp(col, 0.0, 5.0), 1.0);
}
