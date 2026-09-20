#version 330

uniform sampler2D frame;
uniform sampler2D bloom;
uniform float amount;
uniform vec3 tint;

in vec2 uv;
out vec3 color;

void main() {
    vec3 c = texture(frame, uv).rgb;
    vec3 b = texture(bloom, uv).rgb * tint;
    color = clamp(c + b * amount, 0.0, 1.0);
}
