#version 330
#include "common.glsl"

uniform sampler2D frame;
uniform vec2 resolution;
uniform float time;
uniform float amount;   // UV displacement magnitude
uniform float scale;    // noise spatial scale
uniform float speed;    // how fast the field evolves

in vec2 uv;
out vec3 color;

void main() {
    float aspect = resolution.x / resolution.y;
    vec2 p = vec2(uv.x * aspect, uv.y) * scale;
    p += vec2(time * speed * 0.15, time * speed * 0.07);

    vec2 flow = curl_noise(p);
    // keep vertical motion a bit stronger — suits sea/fog
    flow.y *= 1.25;

    vec2 q = uv + flow * amount;
    q = clamp(q, 0.001, 0.999);
    color = texture(frame, q).rgb;
}
