#version 330
#include "common.glsl"

uniform sampler2D frame;
uniform vec2 resolution;
uniform float time;
uniform float mix_amt;
uniform float amount;   // shift distance, fraction of the frame
uniform float count;
uniform float speed;
uniform float split;    // extra RGB offset along the slide
uniform int axis;       // 0 horizontal bands slide in x, 1 vertical bands slide in y
uniform int colors;     // 0 rgb … which channel leads, centers, trails
uniform int color_on;   // 0 = no channel split, 1 = split

in vec2 uv;
out vec3 color;

float ch(vec3 c, int i) {
    if (i == 0) return c.r;
    if (i == 1) return c.g;
    return c.b;
}

void write_ch(inout vec3 c, int i, float v) {
    if (i == 0) c.r = v;
    else if (i == 1) c.g = v;
    else c.b = v;
}

void split_roles(out int lead, out int mid, out int trail) {
    lead = 0;
    mid = 1;
    trail = 2;
    if (colors == 1) { lead = 0; mid = 2; trail = 1; }       // rbg
    else if (colors == 2) { lead = 1; mid = 0; trail = 2; }  // grb
    else if (colors == 3) { lead = 1; mid = 2; trail = 0; }  // gbr
    else if (colors == 4) { lead = 2; mid = 0; trail = 1; }  // brg
    else if (colors == 5) { lead = 2; mid = 1; trail = 0; }  // bgr
}

vec3 sample_shift(vec2 q, float along) {
    vec2 dir = axis == 0 ? vec2(1.0, 0.0) : vec2(0.0, 1.0);
    float chroma = color_on == 0 ? 0.0 : split * amount * 0.45;
    int lead, mid, trail;
    split_roles(lead, mid, trail);
    vec3 ahead = texture(frame, fract(q + dir * (along + chroma))).rgb;
    vec3 center = texture(frame, fract(q + dir * along)).rgb;
    vec3 behind = texture(frame, fract(q + dir * (along - chroma))).rgb;
    vec3 outc = center;
    write_ch(outc, lead, ch(ahead, lead));
    write_ch(outc, mid, ch(center, mid));
    write_ch(outc, trail, ch(behind, trail));
    return outc;
}

void main() {
    vec3 src = texture(frame, uv).rgb;
    if (mix_amt <= 0.001 || amount <= 0.0005) {
        color = src;
        return;
    }

    float n = max(floor(count + 0.5), 2.0);
    float coord = axis == 0 ? uv.y : uv.x;
    float cell = floor(coord * n);
    float id = hash11(vec2(cell, 9.17));
    float wave = sin(time * speed * 2.4 + cell * 0.61 + id * 6.2831853);
    float along = ((id * 2.0 - 1.0) * 0.45 + wave * 0.55) * amount;

    color = mix(src, sample_shift(uv, along), clamp(mix_amt, 0.0, 1.0));
}
