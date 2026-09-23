#version 330
#include "common.glsl"

uniform sampler2D frame;
uniform vec2 resolution;
uniform float time;
uniform int mode;       // 0 none, 1 grid, 2 radar, 3 contours, 4 voronoi, 5 edges
uniform float mix_amt;
uniform float amount;    // mode-specific: perspective / threshold / strength
uniform float line_amt;  // stroke thickness
uniform float scale;
uniform float count;
uniform float speed;
uniform float bright;   // 0 ink (darken), 1 light add
uniform float radius;   // sun ring radius
uniform float irregular; // sun surface breakup
uniform vec2 center;
uniform vec3 tint;

in vec2 uv;
out vec3 color;

vec2 to_centered(vec2 st) {
    vec2 p = st - center;
    p.x *= resolution.x / resolution.y;
    return p;
}

float hair(float dist, float width) {
    float w = max(width, 1.5 / min(resolution.x, resolution.y));
    return 1.0 - smoothstep(0.0, w, abs(dist));
}

float grid_ortho(vec2 st, float n, float width) {
    vec2 g = st * n;
    g.y *= resolution.y / resolution.x;
    vec2 f = fract(g) - 0.5;
    float d = min(abs(f.x), abs(f.y)) / n;
    return hair(d, width);
}

float grid_perspective(vec2 st, float n, float width) {
    vec2 p = st - vec2(center.x, center.y);
    float z = max(abs(p.y), 0.04);
    vec2 g;
    g.x = p.x / z * n;
    g.y = (0.35 / z + time * speed * 0.25) * n;
    vec2 f = fract(g) - 0.5;
    float d = min(abs(f.x), abs(f.y)) * z / n;
    float fade = smoothstep(0.0, 0.12, abs(p.y));
    return hair(d, width) * fade;
}

float overlay_grid(vec2 st, float width) {
    float n = max(count, 2.0);
    float ortho = grid_ortho(st, n, width);
    float persp = grid_perspective(st, n, width);
    return mix(ortho, persp, clamp(amount, 0.0, 1.0));
}

float overlay_radar(vec2 st, float width) {
    vec2 p = to_centered(st);
    float r = length(p);
    float a = atan(p.y, p.x);
    float rings_n = max(count, 2.0);
    float ring_d = (fract(r * rings_n + time * speed * 0.15) - 0.5) / rings_n;
    float spokes_n = max(floor(count + 0.5), 2.0);
    float spoke_d = (fract((a / 6.2831853) * spokes_n) - 0.5) * 6.2831853 / spokes_n * max(r, 0.02);
    return max(hair(ring_d, width), hair(spoke_d, width));
}

float overlay_contours(vec2 st, float width) {
    float l = luma(texture(frame, st).rgb);
    float bands = max(count, 2.0);
    float f = (fract(l * bands) - 0.5) / bands;
    return hair(f, width * (0.4 + 0.8 * amount));
}

float overlay_voronoi(vec2 st, float width) {
    vec2 p = st * max(scale, 0.5);
    vec2 n = floor(p);
    vec2 f = fract(p);
    float d1 = 8.0;
    float d2 = 8.0;
    for (int j = -1; j <= 1; j++) {
        for (int i = -1; i <= 1; i++) {
            vec2 g = vec2(float(i), float(j));
            vec2 o = hash2(n + g) * 0.5 + 0.5;
            vec2 r = g + o - f;
            float d = length(r);
            if (d < d1) {
                d2 = d1;
                d1 = d;
            } else if (d < d2) {
                d2 = d;
            }
        }
    }
    float edge = (d2 - d1) / max(scale, 0.5);
    return hair(edge, width);
}

float luma_at(vec2 st) {
    return luma(texture(frame, clamp(st, 0.001, 0.999)).rgb);
}

float overlay_edges(vec2 st) {
    vec2 px = 1.0 / resolution;
    float n00 = luma_at(st + px * vec2(-1.0, -1.0));
    float n10 = luma_at(st + px * vec2( 0.0, -1.0));
    float n20 = luma_at(st + px * vec2( 1.0, -1.0));
    float n01 = luma_at(st + px * vec2(-1.0,  0.0));
    float n21 = luma_at(st + px * vec2( 1.0,  0.0));
    float n02 = luma_at(st + px * vec2(-1.0,  1.0));
    float n12 = luma_at(st + px * vec2( 0.0,  1.0));
    float n22 = luma_at(st + px * vec2( 1.0,  1.0));
    float gx = -n00 - 2.0 * n01 - n02 + n20 + 2.0 * n21 + n22;
    float gy = -n00 - 2.0 * n10 - n20 + n02 + 2.0 * n12 + n22;
    float e = length(vec2(gx, gy));
    float thr = mix(0.05, 0.45, clamp(amount, 0.0, 1.0));
    return smoothstep(thr, thr + 0.12, e);
}

// Burning ring. Limb noise is seamless via cos/sin. Drift scrolls every layer.
float overlay_sun(vec2 st) {
    vec2 p = to_centered(st);
    float r = length(p);
    float a = atan(p.y, p.x);
    vec2 ring = vec2(cos(a), sin(a));
    float crawl = time * speed * 3.2;
    float irreg = clamp(irregular, 0.0, 1.0);
    float limb = fbm(ring * 2.1 + vec2(crawl, crawl * 0.37));
    float tongue = fbm(ring * 5.4 + vec2(-crawl * 1.15, crawl * 0.42));
    float grain_n = fbm(ring * mix(7.0, 18.0, clamp(scale / 12.0, 0.0, 1.0)) + vec2(crawl * 1.6, -crawl));
    float rad = max(radius, 0.02);
    rad *= 1.0 + (limb * 0.72 + tongue * 0.38) * irreg;
    float width = mix(0.010, 0.10, clamp(line_amt, 0.0, 1.0));
    width *= 1.0 + max(tongue, 0.0) * irreg * 1.15;
    float d = r - rad;
    float band = exp(-d * d / max(width * width, 1e-5));
    float corona = exp(-max(d, 0.0) * max(d, 0.0) / max(width * width * 22.0, 1e-4));
    float heat = mix(0.28, 1.45, smoothstep(-0.35, 0.72, grain_n * 0.7 + tongue * 0.45));
    float shine = mix(0.25, 2.6, clamp(amount, 0.0, 1.0));
    return (band * heat + corona * 0.5) * shine;
}

void main() {
    vec3 src = texture(frame, uv).rgb;
    if (mode <= 0 || mix_amt <= 0.001) {
        color = src;
        return;
    }

    float width = mix(0.0010, 0.009, clamp(line_amt, 0.0, 1.0));
    if (mode == 6) {
        vec3 hot = mix(tint, vec3(1.0, 0.97, 0.90), 0.72);
        color = clamp(src + hot * overlay_sun(uv) * mix_amt, 0.0, 1.0);
        return;
    }
    float line = 0.0;
    if (mode == 1) line = overlay_grid(uv, width);
    else if (mode == 2) line = overlay_radar(uv, width);
    else if (mode == 3) line = overlay_contours(uv, width);
    else if (mode == 4) line = overlay_voronoi(uv, width);
    else if (mode == 5) line = overlay_edges(uv);

    vec3 lit = src + tint * line * mix_amt;
    vec3 ink = src * (1.0 - line * mix_amt);
    color = clamp(mix(ink, lit, clamp(bright, 0.0, 1.0)), 0.0, 1.0);
}
