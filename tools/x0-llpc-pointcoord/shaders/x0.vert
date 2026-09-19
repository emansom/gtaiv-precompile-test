#version 450
// X0 pre-rasterization shader. Shaped like a DXVK D3D9 SM3 vertex shader:
// POSITION / COLOR0 / TEXCOORD0 in, TEXCOORD0 / COLOR0 out.
//
// X0_NONCE is a placeholder. x0.c patches a fresh value into this OpConstant
// before every library it creates, so the driver never sees the same SPIR-V
// twice. The compare against push data keeps the constant live, so no driver
// can strip it before hashing the module.

#define X0_NONCE 0xC0FFEE02u

layout(location = 0) in vec4 aPosition;
layout(location = 1) in vec4 aTexcoord0;
layout(location = 2) in vec4 aColor0;

layout(location = 0) out vec4 vTexcoord0;
layout(location = 1) out vec4 vColor0;

layout(push_constant) uniform X0PushData {
  uint specWord;   // bit 0: enablePointSprite (what DXVK keeps in D3D9SpecData)
  uint probe;      // compared against the nonce; never equal at run time
} pc;

void main() {
  vec4 p = aPosition;
  if (pc.probe == X0_NONCE)
    p.x += 1.0;
  gl_Position = p;
  vTexcoord0 = aTexcoord0;
  vColor0 = aColor0;
}
