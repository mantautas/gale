#version 330
#include "common.glsl"

uniform sampler2D frame;
uniform vec2 resolution;
uniform float time;
uniform int mode;        // 0 none, then slices polar voronoi kaleido fold mosaic luma droste hex tiles
uniform float mix_amt;
uniform float amount;
uniform float scale;
uniform float count;
uniform float line_amt;
uniform float speed;
uniform vec2 center;

in vec2 uv;
out vec3 color;

vec2 to_centered(vec2 st) {
    vec2 p = st - center;
    p.x *= resolution.x / resolution.y;
    return p;
}

vec2 from_centered(vec2 p) {
    p.x /= resolution.x / resolution.y;
    return p + center;
}

vec3 sample_frame(vec2 q) {
    return texture(frame, clamp(q, 0.001, 0.999)).rgb;
}

// --- 1 slices: vertical bands with independent vertical shift ---
vec2 geo_slices(vec2 st) {
    float n = max(floor(count + 0.5), 1.0);
    float cell = floor(st.x * n);
    float id = hash11(vec2(cell, 7.13));
    float shift = (id - 0.5) * 2.0 * amount;
    vec2 q = st;
    q.y = fract(st.y + shift);
    return q;
}

float slices_edge(vec2 st) {
    float n = max(floor(count + 0.5), 1.0);
    float f = fract(st.x * n);
    return smoothstep(0.0, 0.04, min(f, 1.0 - f));
}

// --- 2 polar: ring + wedge quantization of the photograph ---
vec2 geo_polar(vec2 st) {
    vec2 p = to_centered(st);
    float r = length(p);
    float a = atan(p.y, p.x);
    float rings = max(floor(count + 0.5), 2.0);
    float rq = (floor(r * rings) + 0.5) / rings;
    float segs = rings * 2.0;
    float aq = (floor((a / 6.2831853 + 0.5) * segs) + 0.5) / segs * 6.2831853 - 3.14159265;
    float r2 = mix(r, rq, clamp(amount, 0.0, 1.0));
    float a2 = mix(a, aq, clamp(amount, 0.0, 1.0));
    a2 += time * speed * 0.15;
    return from_centered(vec2(cos(a2), sin(a2)) * r2);
}

// --- 3 voronoi: per-cell UV offset ---
vec2 geo_voronoi(vec2 st, out float edge) {
    vec2 p = st * max(scale, 0.5);
    vec2 n = floor(p);
    vec2 f = fract(p);
    float md = 8.0;
    vec2 best = n;
    for (int j = -1; j <= 1; j++) {
        for (int i = -1; i <= 1; i++) {
            vec2 g = vec2(float(i), float(j));
            vec2 o = hash2(n + g) * 0.5 + 0.5;
            vec2 r = g + o - f;
            float d = dot(r, r);
            if (d < md) {
                md = d;
                best = n + g;
            }
        }
    }
    vec2 jitter = (hash2(best) * 0.5) * amount;
    edge = smoothstep(0.0, 0.08, sqrt(md));
    return st + jitter;
}

// --- 4 kaleido: n-fold polar mirror ---
vec2 geo_kaleido(vec2 st) {
    vec2 p = to_centered(st);
    float segs = max(floor(count + 0.5), 2.0);
    float slice = 6.2831853 / segs;
    float a = atan(p.y, p.x);
    float r = length(p);
    a = mod(a, slice);
    a = abs(a - slice * 0.5);
    a += time * speed * 0.2;
    p = vec2(cos(a), sin(a)) * r;
    return from_centered(p);
}

// --- 5 fold: domain fold / paper crease ---
vec2 geo_fold(vec2 st) {
    vec2 p = st * max(scale, 1.0);
    p = abs(fract(p) * 2.0 - 1.0);
    p = mix(st, p, clamp(amount * 2.0, 0.0, 1.0));
    return p;
}

// --- 6 mosaic: integer tiles with per-tile rotate/zoom ---
vec2 geo_mosaic(vec2 st) {
    vec2 n = vec2(max(floor(count + 0.5), 2.0));
    n.y *= resolution.y / resolution.x;
    n.y = max(floor(n.y + 0.5), 2.0);
    vec2 cell = floor(st * n);
    vec2 local = fract(st * n) - 0.5;
    float ang = (hash11(cell) - 0.5) * amount * 4.0;
    float z = 1.0 + (hash11(cell + 19.2) - 0.5) * amount * 0.8;
    float ca = cos(ang);
    float sa = sin(ang);
    local = mat2(ca, -sa, sa, ca) * local / z;
    return (cell + local + 0.5) / n;
}

float mosaic_edge(vec2 st) {
    vec2 n = vec2(max(floor(count + 0.5), 2.0));
    n.y *= resolution.y / resolution.x;
    n.y = max(floor(n.y + 0.5), 2.0);
    vec2 f = fract(st * n);
    float e = min(min(f.x, f.y), min(1.0 - f.x, 1.0 - f.y));
    return smoothstep(0.0, 0.06, e);
}

// --- 7 luma: brightness as vertical relief ---
vec2 geo_luma(vec2 st) {
    float l = luma(texture(frame, st).rgb);
    vec2 dir = to_centered(st);
    float len = length(dir);
    dir = (len > 1e-4) ? dir / len : vec2(0.0, 1.0);
    return st + vec2(0.0, (l - 0.5) * amount) + dir * (l - 0.5) * amount * 0.25;
}

// --- 8 droste: log-polar recursive zoom ---
vec2 geo_droste(vec2 st) {
    vec2 p = to_centered(st);
    float r = max(length(p), 1e-4);
    float period = log(max(scale, 1.15));
    float wrapped = mod(log(r) - time * speed * 0.4, period);
    float nr = exp(wrapped) * mix(1.0, 0.55, clamp(amount, 0.0, 1.0));
    return from_centered(p / r * nr);
}

// --- 9 hex: hexagonal tessellation ---
vec2 hex_relative(vec2 p) {
    const vec2 s = vec2(1.0, 1.7320508);
    vec2 a = mod(p, s) - s * 0.5;
    vec2 b = mod(p + s * 0.5, s) - s * 0.5;
    return (dot(a, a) < dot(b, b)) ? a : b;
}

vec2 geo_hex(vec2 st, out float edge) {
    vec2 p = st * max(scale, 1.0) * vec2(resolution.x / resolution.y, 1.0);
    vec2 gv = hex_relative(p);
    vec2 center_p = p - gv;
    edge = smoothstep(0.0, 0.08, 0.5 - length(gv));
    vec2 jitter = (hash2(floor(center_p * 8.0)) * 0.5) * amount;
    return st + jitter / max(scale, 1.0);
}

// --- 10 tiles: simple grid repeat ---
vec2 geo_tiles(vec2 st) {
    float n = max(floor(count + 0.5), 2.0);
    vec2 p = (st - 0.5) * n + 0.5;
    return fract(p);
}

void main() {
    vec3 src = texture(frame, uv).rgb;
    if (mode <= 0 || mix_amt <= 0.001) {
        color = src;
        return;
    }

    vec2 q = uv;
    float edge = 1.0;

    if (mode == 1) {
        q = geo_slices(uv);
        edge = slices_edge(uv);
    } else if (mode == 2) {
        q = geo_polar(uv);
    } else if (mode == 3) {
        q = geo_voronoi(uv, edge);
    } else if (mode == 4) {
        q = geo_kaleido(uv);
    } else if (mode == 5) {
        q = geo_fold(uv);
    } else if (mode == 6) {
        q = geo_mosaic(uv);
        edge = mosaic_edge(uv);
    } else if (mode == 7) {
        q = geo_luma(uv);
    } else if (mode == 8) {
        q = geo_droste(uv);
    } else if (mode == 9) {
        q = geo_hex(uv, edge);
    } else if (mode == 10) {
        q = geo_tiles(uv);
    }

    vec3 warped = sample_frame(q);
    vec3 mixed = mix(src, warped, clamp(mix_amt, 0.0, 1.0));
    mixed *= mix(1.0, mix(0.32, 1.0, edge), clamp(line_amt, 0.0, 1.0));
    color = clamp(mixed, 0.0, 1.0);
}
