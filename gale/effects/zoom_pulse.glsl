#version 330

uniform sampler2D frame;
uniform float zoom;
uniform vec2 center;

in vec2 uv;
out vec3 color;

void main() {
    vec2 q = (uv - center) / zoom + center;
    color = texture(frame, q).rgb;
}
