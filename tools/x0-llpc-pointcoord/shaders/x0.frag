#version 450
// X0 fragment shader, built twice by build.sh:
//   arm A: -DX0_POINTCOORD  declares and reads BuiltIn PointCoord
//   arm B: (no define)       identical, with a constant in its place
//
// The TEXCOORD0 read mirrors dxbc-spirv's point-sprite emulation
// (sm3/sm3_io_map.cpp:676-698 @ bf14419e, the commit DXVK v3.1.1 pins):
// every TEXCOORD component is Select(enablePointSprite, pointCoord, texcoord),
// with pointCoord = (PointCoord.x, PointCoord.y, 0, 0). In a DXVK GPL library
// enablePointSprite is a spec constant lowered to a buffer load
// (dxvk_shader_ir.cpp: lowerSpecConstantsToCbv), i.e. a run-time value, so
// PointCoord stays live. Here it is a push-data load: also a run-time value,
// and it needs no descriptor set.
//
// X0_NONCE: see x0.vert.

#define X0_NONCE 0xC0FFEE01u

layout(location = 0) in vec4 vTexcoord0;
layout(location = 1) in vec4 vColor0;

layout(location = 0) out vec4 oC0;

layout(push_constant) uniform X0PushData {
  uint specWord;   // bit 0: enablePointSprite
  uint probe;
} pc;

void main() {
  bool pointSprite = (pc.specWord & 1u) != 0u;

#ifdef X0_POINTCOORD
  vec4 pointCoord = vec4(gl_PointCoord, 0.0, 0.0);
#else
  vec4 pointCoord = vec4(0.0);
#endif

  // mix() with a bool vector compiles to OpSelect, as dxbc-spirv's Select does.
  vec4 tc = mix(vTexcoord0, pointCoord, bvec4(pointSprite));

  vec4 c = tc * vColor0;
  if (pc.probe == X0_NONCE)
    c.a = 0.5;
  oC0 = c;
}
