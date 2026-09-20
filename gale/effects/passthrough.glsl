#version 330
uniform sampler2D frame;
in vec2 uv;
out vec3 color;
void main() {
    color = texture(frame, uv).rgb;
}
