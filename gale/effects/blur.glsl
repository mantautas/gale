#version 330

uniform sampler2D frame;
uniform vec2 direction;  // one pixel step in UV, e.g. (1/w, 0)

in vec2 uv;
out vec3 color;

void main() {
    // 9-tap Gaussian
    vec3 s = texture(frame, uv).rgb * 0.227027;
    s += texture(frame, uv + direction * 1.384615).rgb * 0.316216;
    s += texture(frame, uv - direction * 1.384615).rgb * 0.316216;
    s += texture(frame, uv + direction * 3.230769).rgb * 0.070270;
    s += texture(frame, uv - direction * 3.230769).rgb * 0.070270;
    color = s;
}
