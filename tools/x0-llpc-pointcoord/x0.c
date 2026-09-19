/*
 * x0.c -- experiment X0: does a GPL fragment-shader library that declares
 * BuiltIn PointCoord ever fast-link on this Vulkan driver?
 *
 * It mirrors how DXVK v3.1.1 builds a D3D9 draw's *base* pipeline with
 * VK_EXT_graphics_pipeline_library (dxvk_graphics.cpp createBasePipeline):
 * a vertex-input library, a pre-rasterization (VS) library, a fragment-shader
 * library and a fragment-output library, linked WITHOUT link-time
 * optimization. Arm A's fragment shader declares and reads BuiltIn PointCoord,
 * as dxbc-spirv emits in every SM3 pixel shader; arm B's is identical without
 * it.
 *
 * For every arm and iteration, two separate sets of never-seen libraries are
 * created (the SPIR-V carries a fresh nonce each time), then:
 *   (i)  a link WITH    FAIL_ON_PIPELINE_COMPILE_REQUIRED: VkResult + time
 *   (ii) a link WITHOUT it:                                 VkResult + time
 *
 * Builds as 32-bit Windows (mingw) and as native Linux. The Vulkan loader is
 * opened at run time, so no import library is needed. See README.md.
 */

#define VK_NO_PROTOTYPES

#ifdef _WIN32
#  define WIN32_LEAN_AND_MEAN
#  include <windows.h>
#else
#  define _POSIX_C_SOURCE 200809L
#  include <dlfcn.h>
#  include <time.h>
#  include <unistd.h>
#endif

#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#include <vulkan/vulkan.h>

#include "x0_vs_spv.h"
#include "x0_fs_a_spv.h"
#include "x0_fs_b_spv.h"

#define X0_VERSION "1"
#ifndef X0_SOURCE_SHA
#  define X0_SOURCE_SHA "unknown"
#endif
#ifdef _WIN32
#  define X0_PLATFORM "windows"
#else
#  define X0_PLATFORM "linux"
#endif

/* Placeholder OpConstant values in the shaders (see shaders/x0.*). */
#define PH_FS 0xC0FFEE01u
#define PH_VS 0xC0FFEE02u

/* Verdict thresholds, on the median of link (ii). */
#define FAST_MS    2.0   /* a fast link is "well under a millisecond"; allow 2 */
#define SLOW_MS    5.0   /* a full compile is "tens of ms or more"             */
#define SLOW_RATIO 10.0  /* and at least 10x arm B                             */

#define MAX_ITERS 500

enum { ARM_A = 0, ARM_B = 1 };
enum { V_NONE = 0, V_PROVEN, V_FALSIFIED, V_OTHER, V_ERROR };

/* ------------------------------------------------------------------------ */
/* Vulkan entry points                                                      */

#define X0_GLOBAL_FNS(X) X(vkCreateInstance) X(vkEnumerateInstanceVersion)
#define X0_INSTANCE_FNS(X)                                                     \
  X(vkDestroyInstance) X(vkEnumeratePhysicalDevices)                           \
  X(vkGetPhysicalDeviceProperties2) X(vkGetPhysicalDeviceFeatures2)            \
  X(vkGetPhysicalDeviceQueueFamilyProperties)                                  \
  X(vkEnumerateDeviceExtensionProperties)                                      \
  X(vkGetPhysicalDeviceFormatProperties) X(vkCreateDevice)                     \
  X(vkGetDeviceProcAddr)
#define X0_DEVICE_FNS(X)                                                       \
  X(vkDestroyDevice) X(vkCreateGraphicsPipelines) X(vkDestroyPipeline)         \
  X(vkCreatePipelineLayout) X(vkDestroyPipelineLayout)

#define X0_DECL(n) static PFN_##n p_##n;
static PFN_vkGetInstanceProcAddr p_vkGetInstanceProcAddr;
X0_GLOBAL_FNS(X0_DECL)
X0_INSTANCE_FNS(X0_DECL)
X0_DEVICE_FNS(X0_DECL)

static int load_loader(void) {
#ifdef _WIN32
  HMODULE m = LoadLibraryA("vulkan-1.dll");
  if (!m)
    return 0;
  p_vkGetInstanceProcAddr = (PFN_vkGetInstanceProcAddr)(void (*)(void))
    GetProcAddress(m, "vkGetInstanceProcAddr");
#else
  void* m = dlopen("libvulkan.so.1", RTLD_NOW | RTLD_LOCAL);
  if (!m)
    m = dlopen("libvulkan.so", RTLD_NOW | RTLD_LOCAL);
  if (!m)
    return 0;
  *(void**)&p_vkGetInstanceProcAddr = dlsym(m, "vkGetInstanceProcAddr");
#endif
  return p_vkGetInstanceProcAddr != NULL;
}

/* ------------------------------------------------------------------------ */
/* Timing and nonces                                                        */

static int64_t ticks(void) {
#ifdef _WIN32
  LARGE_INTEGER c;
  QueryPerformanceCounter(&c);
  return c.QuadPart;
#else
  struct timespec ts;
  clock_gettime(CLOCK_MONOTONIC, &ts);
  return (int64_t)ts.tv_sec * 1000000000 + ts.tv_nsec;
#endif
}

static double ms_since(int64_t t0) {
  int64_t d = ticks() - t0;
#ifdef _WIN32
  static LARGE_INTEGER f;
  if (!f.QuadPart)
    QueryPerformanceFrequency(&f);
  return (double)d * 1000.0 / (double)f.QuadPart;
#else
  return (double)d / 1.0e6;
#endif
}

static uint32_t g_seed, g_ctr;
static int      g_fixedNonce;   /* diagnostic only: -FixedNonce, i.e. NOT cold */

static uint32_t mix32(uint32_t x) { /* bijective, so seed+counter never repeats */
  x ^= x >> 16; x *= 0x7feb352du;
  x ^= x >> 15; x *= 0x846ca68bu;
  x ^= x >> 16;
  return x;
}

static void seed_nonce(void) {
#ifdef _WIN32
  LARGE_INTEGER c;
  QueryPerformanceCounter(&c);
  g_seed = (uint32_t)c.QuadPart ^ (uint32_t)(c.QuadPart >> 32)
         ^ ((uint32_t)GetCurrentProcessId() * 2654435761u) ^ (uint32_t)GetTickCount();
#else
  struct timespec ts;
  clock_gettime(CLOCK_REALTIME, &ts);
  g_seed = (uint32_t)ts.tv_nsec ^ (uint32_t)ts.tv_sec ^ ((uint32_t)getpid() * 2654435761u);
#endif
  g_seed = mix32(g_seed);
}

static uint32_t next_nonce(void) {
  uint32_t n;
  if (g_fixedNonce)
    return g_seed;
  do { n = mix32(g_seed + g_ctr++); } while (n == PH_FS || n == PH_VS);
  return n;
}

/* ------------------------------------------------------------------------ */
/* SPIR-V: a mutable copy per shader, patched with a nonce before each use  */

typedef struct {
  uint32_t* code;
  size_t    words;
  size_t    patchIdx;
} Spv;

static int spv_init(Spv* s, const char* name, const uint32_t* src, size_t bytes, uint32_t ph) {
  size_t i, hits = 0;
  s->words = bytes / 4;
  s->code = (uint32_t*)malloc(bytes);
  if (!s->code)
    return 0;
  memcpy(s->code, src, bytes);
  if (s->words < 5 || s->code[0] != 0x07230203u) {
    fprintf(stderr, "x0: %s is not SPIR-V\n", name);
    return 0;
  }
  for (i = 5; i < s->words; ) {
    uint32_t wc = s->code[i] >> 16, op = s->code[i] & 0xffffu;
    if (!wc || i + wc > s->words)
      break;
    if (op == 43 /* OpConstant */ && wc == 4 && s->code[i + 3] == ph) {
      s->patchIdx = i + 3;
      hits++;
    }
    i += wc;
  }
  if (hits != 1) {
    fprintf(stderr, "x0: %s has %u nonce placeholders, expected 1\n", name, (unsigned)hits);
    return 0;
  }
  return 1;
}

static int spv_has_builtin(const Spv* s, uint32_t builtIn) {
  size_t i;
  for (i = 5; i < s->words; ) {
    uint32_t wc = s->code[i] >> 16, op = s->code[i] & 0xffffu;
    if (!wc || i + wc > s->words)
      break;
    if (op == 71 /* OpDecorate */ && wc >= 4 && s->code[i + 2] == 11 /* BuiltIn */
     && s->code[i + 3] == builtIn)
      return 1;
    if (op == 72 /* OpMemberDecorate */ && wc >= 5 && s->code[i + 3] == 11
     && s->code[i + 4] == builtIn)
      return 1;
    i += wc;
  }
  return 0;
}

#define SPV_BUILTIN_POINTCOORD 16u

/* ------------------------------------------------------------------------ */
/* Device context                                                           */

typedef struct {
  VkInstance       inst;
  VkPhysicalDevice pd;
  VkDevice         dev;
  int              devIndex;

  VkPhysicalDeviceProperties2                          props;
  VkPhysicalDeviceDriverProperties                     drv;
  VkPhysicalDeviceGraphicsPipelineLibraryPropertiesEXT gplProps;

  int extPipeLib, extGpl, extMaint5, extEds3, extHeap, extDescBuf;
  int featGpl, featMaint5, featEds3DepthClip, featHeap, featDescBuf;
  int featDepthClamp, featDepthBounds, featDynRendering, featCacheControl, featBda;

  /* what the device was created with */
  int useMaint5, useEds3DepthClip, useHeap, useDepthClamp, useDepthBounds;

  VkFormat depthFormat;
  int      depthHasStencil;
} Ctx;

typedef struct {
  const char*      name;   /* "heap" or "legacy" */
  int              heap;
  VkPipelineLayout layout; /* VK_NULL_HANDLE in heap mode, as in DXVK */
} Mode;

static const char* driver_id_name(VkDriverId id) {
  switch (id) {
    case VK_DRIVER_ID_AMD_PROPRIETARY:     return "AMD_PROPRIETARY";
    case VK_DRIVER_ID_AMD_OPEN_SOURCE:     return "AMD_OPEN_SOURCE";
    case VK_DRIVER_ID_MESA_RADV:           return "MESA_RADV";
    case VK_DRIVER_ID_NVIDIA_PROPRIETARY:  return "NVIDIA_PROPRIETARY";
    case VK_DRIVER_ID_INTEL_PROPRIETARY_WINDOWS: return "INTEL_PROPRIETARY_WINDOWS";
    case VK_DRIVER_ID_INTEL_OPEN_SOURCE_MESA:    return "INTEL_OPEN_SOURCE_MESA";
    case VK_DRIVER_ID_MESA_NVK:            return "MESA_NVK";
    case VK_DRIVER_ID_MESA_LLVMPIPE:       return "MESA_LLVMPIPE";
    default:                               return "OTHER";
  }
}

static const char* device_type_name(VkPhysicalDeviceType t) {
  switch (t) {
    case VK_PHYSICAL_DEVICE_TYPE_DISCRETE_GPU:   return "discrete";
    case VK_PHYSICAL_DEVICE_TYPE_INTEGRATED_GPU: return "integrated";
    case VK_PHYSICAL_DEVICE_TYPE_VIRTUAL_GPU:    return "virtual";
    case VK_PHYSICAL_DEVICE_TYPE_CPU:            return "cpu";
    default:                                     return "other";
  }
}

/* ------------------------------------------------------------------------ */
/* VkResult names                                                           */

static const char* res_short(int r) {
  switch (r) {
    case VK_SUCCESS:                     return "SUCCESS";
    case VK_PIPELINE_COMPILE_REQUIRED:   return "COMPILE_REQUIRED";
    case VK_ERROR_OUT_OF_HOST_MEMORY:    return "ERROR_OUT_OF_HOST_MEMORY";
    case VK_ERROR_OUT_OF_DEVICE_MEMORY:  return "ERROR_OUT_OF_DEVICE_MEMORY";
    case VK_ERROR_INITIALIZATION_FAILED: return "ERROR_INITIALIZATION_FAILED";
    case VK_ERROR_DEVICE_LOST:           return "ERROR_DEVICE_LOST";
    case VK_ERROR_EXTENSION_NOT_PRESENT: return "ERROR_EXTENSION_NOT_PRESENT";
    case VK_ERROR_FEATURE_NOT_PRESENT:   return "ERROR_FEATURE_NOT_PRESENT";
    case VK_ERROR_INCOMPATIBLE_DRIVER:   return "ERROR_INCOMPATIBLE_DRIVER";
    case VK_ERROR_UNKNOWN:               return "ERROR_UNKNOWN";
    default:                             return NULL;
  }
}

static const char* res_name(int r, char* buf, size_t n) {
  const char* s = res_short(r);
  if (s) snprintf(buf, n, "VK_%s%s", r == VK_PIPELINE_COMPILE_REQUIRED ? "PIPELINE_" : "", s);
  else   snprintf(buf, n, "VkResult(%d)", r);
  return buf;
}

/* "COMPILE_REQUIRED 25/25", or "SUCCESS 20 + COMPILE_REQUIRED 5 (of 25)" */
static void res_summary(const int* r, int n, char* buf, size_t sz) {
  int codes[8], counts[8], nc = 0, i, j;
  size_t used = 0;
  for (i = 0; i < n; i++) {
    for (j = 0; j < nc && codes[j] != r[i]; j++) {}
    if (j == nc && nc < 8) { codes[nc] = r[i]; counts[nc++] = 0; }
    if (j < nc) counts[j]++;
  }
  buf[0] = 0;
  if (nc == 1) {
    char tmp[48];
    const char* s = res_short(codes[0]);
    if (!s) { snprintf(tmp, sizeof(tmp), "VkResult(%d)", codes[0]); s = tmp; }
    snprintf(buf, sz, "%s %d/%d", s, counts[0], n);
    return;
  }
  for (j = 0; j < nc && used < sz; j++) {
    char tmp[48];
    const char* s = res_short(codes[j]);
    if (!s) { snprintf(tmp, sizeof(tmp), "VkResult(%d)", codes[j]); s = tmp; }
    used += (size_t)snprintf(buf + used, sz - used, "%s%s %d", j ? " + " : "", s, counts[j]);
  }
  if (used < sz)
    snprintf(buf + used, sz - used, " (of %d)", n);
}

static int count_res(const int* r, int n, int code) {
  int i, c = 0;
  for (i = 0; i < n; i++) c += r[i] == code;
  return c;
}

/* ------------------------------------------------------------------------ */
/* Statistics                                                               */

typedef struct { int n; double median, min, max, mean; } Stats;

static int cmp_d(const void* a, const void* b) {
  double x = *(const double*)a, y = *(const double*)b;
  return (x > y) - (x < y);
}

static Stats stats(const double* v, int n) {
  Stats s;
  double* t;
  int i;
  memset(&s, 0, sizeof(s));
  s.n = n;
  if (n <= 0)
    return s;
  t = (double*)malloc(sizeof(double) * (size_t)n);
  if (!t)
    return s;
  memcpy(t, v, sizeof(double) * (size_t)n);
  qsort(t, (size_t)n, sizeof(double), cmp_d);
  s.min = t[0];
  s.max = t[n - 1];
  s.median = (n & 1) ? t[n / 2] : 0.5 * (t[n / 2 - 1] + t[n / 2]);
  for (i = 0; i < n; i++) s.mean += t[i];
  s.mean /= n;
  free(t);
  return s;
}

/* ------------------------------------------------------------------------ */
/* Pipeline creation, shaped after DXVK v3.1.1                              */

static VkResult x0_create(const Ctx* c, const Mode* m, VkGraphicsPipelineCreateInfo* info,
                          VkPipelineCreateFlags2 flags, VkPipeline* out) {
  VkPipelineCreateFlags2CreateInfo f2 = { VK_STRUCTURE_TYPE_PIPELINE_CREATE_FLAGS_2_CREATE_INFO };

  if (m->heap)
    flags |= VK_PIPELINE_CREATE_2_DESCRIPTOR_HEAP_BIT_EXT;

  if (c->useMaint5) {
    /* DXVK chains VkPipelineCreateFlags2CreateInfo, and only when non-zero */
    if (flags) {
      f2.flags = flags;
      f2.pNext = info->pNext;
      info->pNext = &f2;
    }
  } else {
    /* LIBRARY (0x800) and FAIL_ON_PIPELINE_COMPILE_REQUIRED (0x100) have the
     * same values in the 32-bit flags */
    info->flags = (VkPipelineCreateFlags)flags;
  }

  *out = VK_NULL_HANDLE;
  /* DXVK passes no VkPipelineCache here */
  return p_vkCreateGraphicsPipelines(c->dev, VK_NULL_HANDLE, 1, info, NULL, out);
}

/* dxvk_graphics.cpp DxvkGraphicsPipelineVertexInputLibrary */
static VkResult make_vi_lib(const Ctx* c, const Mode* m, VkPipeline* out) {
  VkVertexInputBindingDescription b = { 0, 24, VK_VERTEX_INPUT_RATE_VERTEX };
  VkVertexInputAttributeDescription a[3] = {
    { 0, 0, VK_FORMAT_R32G32B32_SFLOAT, 0  },  /* POSITION  float3   */
    { 1, 0, VK_FORMAT_R32G32_SFLOAT,    16 },  /* TEXCOORD0 float2   */
    { 2, 0, VK_FORMAT_B8G8R8A8_UNORM,   12 },  /* COLOR0    D3DCOLOR */
  };
  VkPipelineVertexInputStateCreateInfo vi = { VK_STRUCTURE_TYPE_PIPELINE_VERTEX_INPUT_STATE_CREATE_INFO };
  VkPipelineInputAssemblyStateCreateInfo ia = { VK_STRUCTURE_TYPE_PIPELINE_INPUT_ASSEMBLY_STATE_CREATE_INFO };
  VkDynamicState dyn = VK_DYNAMIC_STATE_VERTEX_INPUT_BINDING_STRIDE;
  VkPipelineDynamicStateCreateInfo dy = { VK_STRUCTURE_TYPE_PIPELINE_DYNAMIC_STATE_CREATE_INFO };
  VkGraphicsPipelineLibraryCreateInfoEXT lib = { VK_STRUCTURE_TYPE_GRAPHICS_PIPELINE_LIBRARY_CREATE_INFO_EXT };
  VkGraphicsPipelineCreateInfo info = { VK_STRUCTURE_TYPE_GRAPHICS_PIPELINE_CREATE_INFO };

  vi.vertexBindingDescriptionCount = 1;
  vi.pVertexBindingDescriptions = &b;
  vi.vertexAttributeDescriptionCount = 3;
  vi.pVertexAttributeDescriptions = a;
  ia.topology = VK_PRIMITIVE_TOPOLOGY_TRIANGLE_LIST;
  dy.dynamicStateCount = 1;
  dy.pDynamicStates = &dyn;
  lib.flags = VK_GRAPHICS_PIPELINE_LIBRARY_VERTEX_INPUT_INTERFACE_BIT_EXT;

  info.pNext = &lib;
  info.pVertexInputState = &vi;
  info.pInputAssemblyState = &ia;
  info.pDynamicState = &dy;
  info.basePipelineIndex = -1;
  return x0_create(c, m, &info, VK_PIPELINE_CREATE_2_LIBRARY_BIT_KHR, out);
}

/* dxvk_graphics.cpp DxvkGraphicsPipelineFragmentOutputLibrary */
static VkResult make_fo_lib(const Ctx* c, const Mode* m, VkPipeline* out) {
  VkFormat color = VK_FORMAT_B8G8R8A8_UNORM;
  VkPipelineRenderingCreateInfo rt = { VK_STRUCTURE_TYPE_PIPELINE_RENDERING_CREATE_INFO };
  VkPipelineColorBlendAttachmentState att;
  VkPipelineColorBlendStateCreateInfo cb = { VK_STRUCTURE_TYPE_PIPELINE_COLOR_BLEND_STATE_CREATE_INFO };
  VkSampleMask mask = 0xffffffffu;
  VkPipelineMultisampleStateCreateInfo ms = { VK_STRUCTURE_TYPE_PIPELINE_MULTISAMPLE_STATE_CREATE_INFO };
  VkDynamicState dyn = VK_DYNAMIC_STATE_BLEND_CONSTANTS;
  VkPipelineDynamicStateCreateInfo dy = { VK_STRUCTURE_TYPE_PIPELINE_DYNAMIC_STATE_CREATE_INFO };
  VkGraphicsPipelineLibraryCreateInfoEXT lib = { VK_STRUCTURE_TYPE_GRAPHICS_PIPELINE_LIBRARY_CREATE_INFO_EXT };
  VkGraphicsPipelineCreateInfo info = { VK_STRUCTURE_TYPE_GRAPHICS_PIPELINE_CREATE_INFO };

  rt.colorAttachmentCount = 1;
  rt.pColorAttachmentFormats = &color;
  rt.depthAttachmentFormat = c->depthFormat;
  rt.stencilAttachmentFormat = c->depthHasStencil ? c->depthFormat : VK_FORMAT_UNDEFINED;

  memset(&att, 0, sizeof(att));
  att.colorWriteMask = VK_COLOR_COMPONENT_R_BIT | VK_COLOR_COMPONENT_G_BIT
                     | VK_COLOR_COMPONENT_B_BIT | VK_COLOR_COMPONENT_A_BIT;
  cb.attachmentCount = 1;
  cb.pAttachments = &att;

  ms.rasterizationSamples = VK_SAMPLE_COUNT_1_BIT;
  ms.pSampleMask = &mask;

  dy.dynamicStateCount = 1;
  dy.pDynamicStates = &dyn;

  lib.pNext = &rt;
  lib.flags = VK_GRAPHICS_PIPELINE_LIBRARY_FRAGMENT_OUTPUT_INTERFACE_BIT_EXT;

  info.pNext = &lib;
  info.pColorBlendState = &cb;
  info.pMultisampleState = &ms;
  info.pDynamicState = &dy;
  info.basePipelineIndex = -1;
  return x0_create(c, m, &info, VK_PIPELINE_CREATE_2_LIBRARY_BIT_KHR, out);
}

/* dxvk_shader.cpp DxvkShaderPipelineLibrary::compileVertexShaderPipeline */
static VkResult make_vs_lib(const Ctx* c, const Mode* m, const Spv* vs, VkPipeline* out) {
  VkDynamicState dyn[8];
  uint32_t nd = 0;
  VkPipelineDynamicStateCreateInfo dy = { VK_STRUCTURE_TYPE_PIPELINE_DYNAMIC_STATE_CREATE_INFO };
  VkPipelineViewportStateCreateInfo vp = { VK_STRUCTURE_TYPE_PIPELINE_VIEWPORT_STATE_CREATE_INFO };
  VkPipelineRasterizationStateCreateInfo rs = { VK_STRUCTURE_TYPE_PIPELINE_RASTERIZATION_STATE_CREATE_INFO };
  VkPipelineRenderingCreateInfo rt = { VK_STRUCTURE_TYPE_PIPELINE_RENDERING_CREATE_INFO };
  VkShaderModuleCreateInfo mod = { VK_STRUCTURE_TYPE_SHADER_MODULE_CREATE_INFO };
  VkPipelineShaderStageCreateInfo st = { VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO };
  VkGraphicsPipelineLibraryCreateInfoEXT lib = { VK_STRUCTURE_TYPE_GRAPHICS_PIPELINE_LIBRARY_CREATE_INFO_EXT };
  VkGraphicsPipelineCreateInfo info = { VK_STRUCTURE_TYPE_GRAPHICS_PIPELINE_CREATE_INFO };

  dyn[nd++] = VK_DYNAMIC_STATE_VIEWPORT_WITH_COUNT;
  dyn[nd++] = VK_DYNAMIC_STATE_SCISSOR_WITH_COUNT;
  dyn[nd++] = VK_DYNAMIC_STATE_DEPTH_BIAS;
  dyn[nd++] = VK_DYNAMIC_STATE_DEPTH_BIAS_ENABLE;
  dyn[nd++] = VK_DYNAMIC_STATE_CULL_MODE;
  dyn[nd++] = VK_DYNAMIC_STATE_FRONT_FACE;
  if (c->useEds3DepthClip)
    dyn[nd++] = VK_DYNAMIC_STATE_DEPTH_CLIP_ENABLE_EXT;
  dy.dynamicStateCount = nd;
  dy.pDynamicStates = dyn;

  rs.depthClampEnable = c->useDepthClamp ? VK_TRUE : VK_FALSE;
  rs.polygonMode = VK_POLYGON_MODE_FILL;
  rs.lineWidth = 1.0f;

  /* No VkShaderModule: the create info is chained into the stage, as DXVK does */
  mod.codeSize = vs->words * 4;
  mod.pCode = vs->code;
  st.pNext = &mod;
  st.stage = VK_SHADER_STAGE_VERTEX_BIT;
  st.pName = "main";

  lib.pNext = &rt;
  lib.flags = VK_GRAPHICS_PIPELINE_LIBRARY_PRE_RASTERIZATION_SHADERS_BIT_EXT;

  info.pNext = &lib;
  info.stageCount = 1;
  info.pStages = &st;
  info.pViewportState = &vp;
  info.pRasterizationState = &rs;
  info.pDynamicState = &dy;
  info.layout = m->layout;
  info.basePipelineIndex = -1;
  return x0_create(c, m, &info, VK_PIPELINE_CREATE_2_LIBRARY_BIT_KHR, out);
}

/* dxvk_shader.cpp DxvkShaderPipelineLibrary::compileFragmentShaderPipeline */
static VkResult make_fs_lib(const Ctx* c, const Mode* m, const Spv* fs, VkPipeline* out) {
  VkDynamicState dyn[12];
  uint32_t nd = 0;
  VkPipelineDynamicStateCreateInfo dy = { VK_STRUCTURE_TYPE_PIPELINE_DYNAMIC_STATE_CREATE_INFO };
  VkPipelineDepthStencilStateCreateInfo ds = { VK_STRUCTURE_TYPE_PIPELINE_DEPTH_STENCIL_STATE_CREATE_INFO };
  VkPipelineRenderingCreateInfo rt = { VK_STRUCTURE_TYPE_PIPELINE_RENDERING_CREATE_INFO };
  VkShaderModuleCreateInfo mod = { VK_STRUCTURE_TYPE_SHADER_MODULE_CREATE_INFO };
  VkPipelineShaderStageCreateInfo st = { VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO };
  VkGraphicsPipelineLibraryCreateInfoEXT lib = { VK_STRUCTURE_TYPE_GRAPHICS_PIPELINE_LIBRARY_CREATE_INFO_EXT };
  VkGraphicsPipelineCreateInfo info = { VK_STRUCTURE_TYPE_GRAPHICS_PIPELINE_CREATE_INFO };

  dyn[nd++] = VK_DYNAMIC_STATE_DEPTH_TEST_ENABLE;
  dyn[nd++] = VK_DYNAMIC_STATE_DEPTH_WRITE_ENABLE;
  dyn[nd++] = VK_DYNAMIC_STATE_DEPTH_COMPARE_OP;
  dyn[nd++] = VK_DYNAMIC_STATE_STENCIL_COMPARE_MASK;
  dyn[nd++] = VK_DYNAMIC_STATE_STENCIL_WRITE_MASK;
  dyn[nd++] = VK_DYNAMIC_STATE_STENCIL_REFERENCE;
  dyn[nd++] = VK_DYNAMIC_STATE_STENCIL_TEST_ENABLE;
  dyn[nd++] = VK_DYNAMIC_STATE_STENCIL_OP;
  if (c->useDepthBounds) {
    dyn[nd++] = VK_DYNAMIC_STATE_DEPTH_BOUNDS_TEST_ENABLE;
    dyn[nd++] = VK_DYNAMIC_STATE_DEPTH_BOUNDS;
  }
  dy.dynamicStateCount = nd;
  dy.pDynamicStates = dyn;

  mod.codeSize = fs->words * 4;
  mod.pCode = fs->code;
  st.pNext = &mod;
  st.stage = VK_SHADER_STAGE_FRAGMENT_BIT;
  st.pName = "main";

  lib.pNext = &rt;
  lib.flags = VK_GRAPHICS_PIPELINE_LIBRARY_FRAGMENT_SHADER_BIT_EXT;

  info.pNext = &lib;
  info.stageCount = 1;
  info.pStages = &st;
  info.pDepthStencilState = &ds;
  info.pDynamicState = &dy;
  info.layout = m->layout;
  info.basePipelineIndex = -1;
  /* no pMultisampleState: DXVK only passes one for sample-rate shading */
  return x0_create(c, m, &info, VK_PIPELINE_CREATE_2_LIBRARY_BIT_KHR, out);
}

/* dxvk_graphics.cpp DxvkGraphicsPipeline::createBasePipeline: no LTO flag */
static VkResult make_link(const Ctx* c, const Mode* m, VkPipeline vi, VkPipeline vs,
                          VkPipeline fs, VkPipeline fo, VkPipelineCreateFlags2 flags,
                          VkPipeline* out) {
  VkPipeline libs[4];
  VkPipelineLibraryCreateInfoKHR li = { VK_STRUCTURE_TYPE_PIPELINE_LIBRARY_CREATE_INFO_KHR };
  VkGraphicsPipelineCreateInfo info = { VK_STRUCTURE_TYPE_GRAPHICS_PIPELINE_CREATE_INFO };

  libs[0] = vi; libs[1] = vs; libs[2] = fs; libs[3] = fo;
  li.libraryCount = 4;
  li.pLibraries = libs;

  info.pNext = &li;
  info.layout = m->layout;
  info.basePipelineIndex = -1;
  return x0_create(c, m, &info, flags, out);
}

static void destroy_pipeline(const Ctx* c, VkPipeline p) {
  if (p != VK_NULL_HANDLE)
    p_vkDestroyPipeline(c->dev, p, NULL);
}

/* ------------------------------------------------------------------------ */
/* Measurement                                                              */

typedef struct {
  double vsLib[2 * MAX_ITERS], fsLib[2 * MAX_ITERS];
  double linkI[MAX_ITERS], linkII[MAX_ITERS];
  int    resI[MAX_ITERS], resII[MAX_ITERS];
  int    nLib, n;
} ArmData;

typedef struct {
  const char* name;
  int         heap, primary, ran;
  char        error[256];
  double      viLibMs, foLibMs;
  ArmData     arm[2];
  int         verdict;
  char        reason[512];
} ModeResult;

typedef struct {
  const char* jsonPath;
  const char* binding;    /* auto | both | heap | legacy */
  const char* appName;
  const char* engineName;
  int         iterations, warmup, device;
} Config;

static Spv g_vs, g_fs[2];

/* One arm, one iteration: link (i) and link (ii), each on its own fresh libraries. */
static int run_arm_once(const Ctx* c, const Mode* m, ModeResult* mr, int arm,
                        VkPipeline vi, VkPipeline fo, int record) {
  ArmData* d = &mr->arm[arm];
  int link;

  for (link = 0; link < 2; link++) {
    VkPipeline vs = VK_NULL_HANDLE, fs = VK_NULL_HANDLE, p = VK_NULL_HANDLE;
    VkPipelineCreateFlags2 flags = link == 0
      ? VK_PIPELINE_CREATE_2_FAIL_ON_PIPELINE_COMPILE_REQUIRED_BIT : 0;
    uint32_t nonce = next_nonce();
    double tvs, tfs, tl;
    VkResult rv, rf, rl;
    int64_t t0;

    g_vs.code[g_vs.patchIdx] = nonce;
    g_fs[arm].code[g_fs[arm].patchIdx] = nonce;

    t0 = ticks(); rv = make_vs_lib(c, m, &g_vs, &vs);       tvs = ms_since(t0);
    t0 = ticks(); rf = make_fs_lib(c, m, &g_fs[arm], &fs);  tfs = ms_since(t0);

    if (rv != VK_SUCCESS || rf != VK_SUCCESS) {
      char b1[48], b2[48];
      snprintf(mr->error, sizeof(mr->error), "arm %c library creation failed: VS %s, FS %s",
               arm == ARM_A ? 'A' : 'B', res_name(rv, b1, sizeof(b1)), res_name(rf, b2, sizeof(b2)));
      destroy_pipeline(c, vs);
      destroy_pipeline(c, fs);
      return 0;
    }

    t0 = ticks(); rl = make_link(c, m, vi, vs, fs, fo, flags, &p); tl = ms_since(t0);

    destroy_pipeline(c, p);
    destroy_pipeline(c, fs);
    destroy_pipeline(c, vs);

    if (record) {
      d->vsLib[d->nLib] = tvs;
      d->fsLib[d->nLib] = tfs;
      d->nLib++;
      if (link == 0) { d->linkI[d->n]  = tl; d->resI[d->n]  = rl; }
      else           { d->linkII[d->n] = tl; d->resII[d->n] = rl; }
    }
  }
  if (record)
    d->n++;
  return 1;
}

static void decide(ModeResult* mr) {
  ArmData* A = &mr->arm[ARM_A];
  ArmData* B = &mr->arm[ARM_B];
  Stats sa, sb;
  int aReq, aOkI, bOkI, aOkII, bOkII;
  char ra[96], rb[96];

  if (mr->error[0] || A->n == 0 || B->n == 0) {
    mr->verdict = V_ERROR;
    snprintf(mr->reason, sizeof(mr->reason), "%s", mr->error[0] ? mr->error : "no samples");
    return;
  }

  sa = stats(A->linkII, A->n);
  sb = stats(B->linkII, B->n);
  aReq  = count_res(A->resI,  A->n, VK_PIPELINE_COMPILE_REQUIRED) == A->n;
  aOkI  = count_res(A->resI,  A->n, VK_SUCCESS) == A->n;
  bOkI  = count_res(B->resI,  B->n, VK_SUCCESS) == B->n;
  aOkII = count_res(A->resII, A->n, VK_SUCCESS) == A->n;
  bOkII = count_res(B->resII, B->n, VK_SUCCESS) == B->n;

  res_summary(A->resI, A->n, ra, sizeof(ra));
  res_summary(B->resI, B->n, rb, sizeof(rb));
  snprintf(mr->reason, sizeof(mr->reason),
           "link(ii) median A %.3f ms, B %.3f ms; link(i) with FAIL_ON: A %s, B %s",
           sa.median, sb.median, ra, rb);

  if (aReq && bOkI && aOkII && bOkII && sb.median < FAST_MS
   && sa.median >= SLOW_MS && sa.median >= SLOW_RATIO * sb.median)
    mr->verdict = V_PROVEN;
  else if (aOkI && bOkI && aOkII && bOkII && sa.median < FAST_MS && sb.median < FAST_MS)
    mr->verdict = V_FALSIFIED;
  else
    mr->verdict = V_OTHER;
}

static const char* verdict_id(int v) {
  switch (v) {
    case V_PROVEN:    return "H0_PROVEN";
    case V_FALSIFIED: return "H0_FALSIFIED";
    case V_OTHER:     return "OTHER";
    case V_ERROR:     return "ERROR";
    default:          return "NONE";
  }
}

static void verdict_line(char* buf, size_t sz, const Ctx* c, const ModeResult* mr) {
  Stats sa = stats(mr->arm[ARM_A].linkII, mr->arm[ARM_A].n);
  Stats sb = stats(mr->arm[ARM_B].linkII, mr->arm[ARM_B].n);
  const char* dn = c->drv.driverName;
  const char* di = c->drv.driverInfo;

  if (mr->verdict == V_PROVEN)
    snprintf(buf, sz, "VERDICT: H0 PROVEN on %s %s -- a PointCoord fragment library never fast-links: "
             "link median %.3f ms (A) vs %.3f ms (B); A with FAIL_ON = VK_PIPELINE_COMPILE_REQUIRED %d/%d",
             dn, di, sa.median, sb.median,
             count_res(mr->arm[ARM_A].resI, mr->arm[ARM_A].n, VK_PIPELINE_COMPILE_REQUIRED),
             mr->arm[ARM_A].n);
  else if (mr->verdict == V_FALSIFIED)
    snprintf(buf, sz, "VERDICT: H0 FALSIFIED on %s %s -- both arms fast-link: "
             "link median %.3f ms (A), %.3f ms (B)", dn, di, sa.median, sb.median);
  else if (mr->verdict == V_OTHER)
    snprintf(buf, sz, "VERDICT: OTHER (report as-is) on %s %s -- %s", dn, di, mr->reason);
  else
    snprintf(buf, sz, "VERDICT: ERROR on %s %s -- %s", dn, di, mr->reason);
}

static int run_mode(const Ctx* c, const Config* cfg, ModeResult* mr) {
  Mode m;
  VkPipeline vi = VK_NULL_HANDLE, fo = VK_NULL_HANDLE;
  VkResult r;
  int64_t t0;
  int it;

  memset(&m, 0, sizeof(m));
  m.name = mr->name;
  m.heap = mr->heap;

  if (!m.heap) {
    /* dxvk_pipelayout.cpp: an INDEPENDENT_SETS layout with push data */
    VkPushConstantRange pcr = { VK_SHADER_STAGE_ALL_GRAPHICS, 0, 8 };
    VkPipelineLayoutCreateInfo li = { VK_STRUCTURE_TYPE_PIPELINE_LAYOUT_CREATE_INFO };
    li.flags = VK_PIPELINE_LAYOUT_CREATE_INDEPENDENT_SETS_BIT_EXT;
    li.pushConstantRangeCount = 1;
    li.pPushConstantRanges = &pcr;
    r = p_vkCreatePipelineLayout(c->dev, &li, NULL, &m.layout);
    if (r != VK_SUCCESS) {
      char b[48];
      snprintf(mr->error, sizeof(mr->error), "vkCreatePipelineLayout: %s", res_name(r, b, sizeof(b)));
      return 0;
    }
  }

  /* DXVK creates these on demand and keeps them; so does X0 */
  t0 = ticks(); r = make_vi_lib(c, &m, &vi); mr->viLibMs = ms_since(t0);
  if (r == VK_SUCCESS) {
    t0 = ticks(); r = make_fo_lib(c, &m, &fo); mr->foLibMs = ms_since(t0);
  }
  if (r != VK_SUCCESS) {
    char b[48];
    snprintf(mr->error, sizeof(mr->error), "vertex-input/fragment-output library: %s",
             res_name(r, b, sizeof(b)));
  } else {
    printf("  [%s] warming up (%d), then %d iterations per arm", m.name, cfg->warmup, cfg->iterations);
    fflush(stdout);
    for (it = -cfg->warmup; it < cfg->iterations; it++) {
      /* alternate which arm goes first, so neither always follows the other */
      int first = ((it + cfg->warmup) & 1) ? ARM_B : ARM_A;
      if (!run_arm_once(c, &m, mr, first, vi, fo, it >= 0)
       || !run_arm_once(c, &m, mr, 1 - first, vi, fo, it >= 0))
        break;
      if (it >= 0 && (it + 1) % 5 == 0) { putchar('.'); fflush(stdout); }
    }
    putchar('\n');
    mr->ran = 1;
  }

  destroy_pipeline(c, vi);
  destroy_pipeline(c, fo);
  if (m.layout != VK_NULL_HANDLE)
    p_vkDestroyPipelineLayout(c->dev, m.layout, NULL);

  decide(mr);
  return mr->error[0] == 0;
}

static void print_row(const char* label, const double* va, int na, const double* vb, int nb) {
  Stats a = stats(va, na), b = stats(vb, nb);
  char ca[64], cb[64];
  snprintf(ca, sizeof(ca), "%.3f (%.3f..%.3f)", a.median, a.min, a.max);
  snprintf(cb, sizeof(cb), "%.3f (%.3f..%.3f)", b.median, b.min, b.max);
  printf("  %-22s %-28s %s\n", label, ca, cb);
}

static void print_mode(const ModeResult* mr, const char* dxvkNote) {
  const ArmData* A = &mr->arm[ARM_A];
  const ArmData* B = &mr->arm[ARM_B];
  char ra[96], rb[96];

  printf("\n[mode %s]%s\n", mr->name, dxvkNote);
  if (mr->error[0] && (A->n == 0 || B->n == 0)) {
    printf("  ERROR: %s\n", mr->error);
    return;
  }
  printf("  vertex-input library %.3f ms, fragment-output library %.3f ms (once, shared)\n",
         mr->viLibMs, mr->foLibMs);
  printf("  %-22s %-28s %s\n", "ms: median (min..max)", "arm A: PointCoord", "arm B: no PointCoord");
  print_row("VS library create", A->vsLib, A->nLib, B->vsLib, B->nLib);
  print_row("FS library create", A->fsLib, A->nLib, B->fsLib, B->nLib);
  print_row("link (i) FAIL_ON", A->linkI, A->n, B->linkI, B->n);
  res_summary(A->resI, A->n, ra, sizeof(ra));
  res_summary(B->resI, B->n, rb, sizeof(rb));
  printf("  %-22s %-28s %s\n", "  result", ra, rb);
  print_row("link (ii) plain", A->linkII, A->n, B->linkII, B->n);
  res_summary(A->resII, A->n, ra, sizeof(ra));
  res_summary(B->resII, B->n, rb, sizeof(rb));
  printf("  %-22s %-28s %s\n", "  result", ra, rb);
  if (mr->error[0])
    printf("  ERROR (partial data): %s\n", mr->error);
  printf("  -> %s: %s\n", verdict_id(mr->verdict), mr->reason);
}

/* ------------------------------------------------------------------------ */
/* JSON                                                                     */

static void jstr(FILE* f, const char* s) {
  fputc('"', f);
  for (; s && *s; s++) {
    unsigned char ch = (unsigned char)*s;
    if (ch == '"' || ch == '\\') { fputc('\\', f); fputc(ch, f); }
    else if (ch < 0x20)          fprintf(f, "\\u%04x", ch);
    else                         fputc(ch, f);
  }
  fputc('"', f);
}

static void jkv_str(FILE* f, const char* k, const char* v, int comma) {
  jstr(f, k); fputs(": ", f);
  if (v) jstr(f, v); else fputs("null", f);
  if (comma) fputs(", ", f);
}

static void jstats(FILE* f, const char* k, const double* v, int n) {
  Stats s = stats(v, n);
  int i;
  jstr(f, k);
  fprintf(f, ": {\"n\": %d, \"median\": %.4f, \"min\": %.4f, \"max\": %.4f, \"mean\": %.4f, \"samples\": [",
          s.n, s.median, s.min, s.max, s.mean);
  for (i = 0; i < n; i++) fprintf(f, "%s%.4f", i ? ", " : "", v[i]);
  fputs("]}", f);
}

static void jresults(FILE* f, const char* k, const int* r, int n) {
  char b[48], sum[128];
  int i;
  res_summary(r, n, sum, sizeof(sum));
  jstr(f, k);
  fputs(": {\"summary\": ", f);
  jstr(f, sum);
  fprintf(f, ", \"success\": %d, \"compile_required\": %d, \"sequence\": [",
          count_res(r, n, VK_SUCCESS), count_res(r, n, VK_PIPELINE_COMPILE_REQUIRED));
  for (i = 0; i < n; i++) { if (i) fputs(", ", f); jstr(f, res_name(r[i], b, sizeof(b))); }
  fputs("]}", f);
}

static void jarm(FILE* f, const char* k, const char* desc, const ArmData* d) {
  jstr(f, k);
  fputs(": {", f);
  jkv_str(f, "fragment_shader", desc, 1);
  jstats(f, "vs_library_ms", d->vsLib, d->nLib);   fputs(", ", f);
  jstats(f, "fs_library_ms", d->fsLib, d->nLib);   fputs(", ", f);
  jstats(f, "link_fail_on_ms", d->linkI, d->n);    fputs(", ", f);
  jresults(f, "link_fail_on_result", d->resI, d->n); fputs(", ", f);
  jstats(f, "link_plain_ms", d->linkII, d->n);     fputs(", ", f);
  jresults(f, "link_plain_result", d->resII, d->n);
  fputs("}", f);
}

static const char* env_or_null(const char* k) {
  const char* v = getenv(k);
  return v;
}

static int write_json(const char* path, const Config* cfg, const Ctx* c, int haveDevice,
                      int gplOk, const char* dxvkModel, const ModeResult* modes, int nModes,
                      int armAPointCoord, int armBPointCoord, const char* verdict,
                      const char* verdictMode, const char* verdictLine) {
  static const char* envKeys[] = {
    "AMD_VK_PIPELINE_CACHE_PATH", "AMD_VK_PIPELINE_CACHE_FILENAME", "AMD_VK_USE_PIPELINE_CACHE",
    "MESA_SHADER_CACHE_DIR", "MESA_SHADER_CACHE_DISABLE", "RADV_PERFTEST", "RADV_DEBUG",
    "VK_DRIVER_FILES", "VK_ICD_FILENAMES", "VK_INSTANCE_LAYERS", "VK_LOADER_LAYERS_ENABLE",
  };
  FILE* f = fopen(path, "wb");
  char ts[32];
  time_t now = time(NULL);
  struct tm* g = gmtime(&now);
  size_t i;
  int mi;

  if (!f)
    return 0;
  if (g) strftime(ts, sizeof(ts), "%Y-%m-%dT%H:%M:%SZ", g);
  else   snprintf(ts, sizeof(ts), "unknown");

  fputs("{\n  ", f);
  jkv_str(f, "tool", "x0-llpc-pointcoord", 1);
  jkv_str(f, "version", X0_VERSION, 1);
  jkv_str(f, "source_sha256", X0_SOURCE_SHA, 1);
  jkv_str(f, "platform", X0_PLATFORM, 1);
  fprintf(f, "\"bits\": %d, ", (int)(sizeof(void*) * 8));
  jkv_str(f, "utc", ts, 0);
  fputs(",\n  \"config\": {", f);
  fprintf(f, "\"iterations\": %d, \"warmup\": %d, ", cfg->iterations, cfg->warmup);
  if (g_fixedNonce) fprintf(f, "\"fixed_nonce\": \"0x%08x\", ", g_seed);
  else              fprintf(f, "\"fixed_nonce\": null, \"nonce_seed\": \"0x%08x\", ", g_seed);
  jkv_str(f, "binding", cfg->binding, 1);
  jkv_str(f, "app_name", cfg->appName, 1);
  jkv_str(f, "engine_name", cfg->engineName, 1);
  fprintf(f, "\"fast_ms\": %.1f, \"slow_ms\": %.1f, \"slow_ratio\": %.1f},\n  \"env\": {",
          FAST_MS, SLOW_MS, SLOW_RATIO);
  for (i = 0; i < sizeof(envKeys) / sizeof(envKeys[0]); i++)
    jkv_str(f, envKeys[i], env_or_null(envKeys[i]), i + 1 < sizeof(envKeys) / sizeof(envKeys[0]));
  fputs("},\n  \"device\": ", f);
  if (!haveDevice) {
    fputs("null", f);
  } else {
    uint32_t av = c->props.properties.apiVersion, dv = c->props.properties.driverVersion;
    char api[32], drvv[32];
    snprintf(api, sizeof(api), "%u.%u.%u", VK_API_VERSION_MAJOR(av), VK_API_VERSION_MINOR(av), VK_API_VERSION_PATCH(av));
    snprintf(drvv, sizeof(drvv), "%u.%u.%u", VK_VERSION_MAJOR(dv), VK_VERSION_MINOR(dv), VK_VERSION_PATCH(dv));
    fprintf(f, "{\"index\": %d, ", c->devIndex);
    jkv_str(f, "name", c->props.properties.deviceName, 1);
    jkv_str(f, "type", device_type_name(c->props.properties.deviceType), 1);
    fprintf(f, "\"vendor_id\": \"0x%04x\", \"device_id\": \"0x%04x\", ",
            c->props.properties.vendorID, c->props.properties.deviceID);
    jkv_str(f, "driver_name", c->drv.driverName, 1);
    jkv_str(f, "driver_info", c->drv.driverInfo, 1);
    fprintf(f, "\"driver_id\": %d, ", (int)c->drv.driverID);
    jkv_str(f, "driver_id_name", driver_id_name(c->drv.driverID), 1);
    jkv_str(f, "api_version", api, 1);
    fprintf(f, "\"driver_version_raw\": %u, ", dv);
    jkv_str(f, "driver_version", drvv, 1);
    fprintf(f, "\"gpl\": {\"extension\": %s, \"graphicsPipelineLibrary\": %s, "
               "\"fastLinking\": %s, \"independentInterpolationDecoration\": %s}, ",
            c->extGpl ? "true" : "false", c->featGpl ? "true" : "false",
            c->gplProps.graphicsPipelineLibraryFastLinking ? "true" : "false",
            c->gplProps.graphicsPipelineLibraryIndependentInterpolationDecoration ? "true" : "false");
    fprintf(f, "\"descriptor_heap\": %s, \"descriptor_buffer\": %s, \"maintenance5\": %s, "
               "\"eds3_depth_clip\": %s, ",
            c->featHeap ? "true" : "false", c->featDescBuf ? "true" : "false",
            c->useMaint5 ? "true" : "false", c->useEds3DepthClip ? "true" : "false");
    jkv_str(f, "dxvk_binding_model", dxvkModel, 0);
    fputs("}", f);
  }
  fprintf(f, ",\n  \"gpl_supported\": %s,\n", gplOk ? "true" : "false");
  fprintf(f, "  \"shader_check\": {\"arm_a_declares_pointcoord\": %s, \"arm_b_declares_pointcoord\": %s},\n",
          armAPointCoord ? "true" : "false", armBPointCoord ? "true" : "false");
  fputs("  \"modes\": [", f);
  for (mi = 0; mi < nModes; mi++) {
    const ModeResult* mr = &modes[mi];
    fputs(mi ? ",\n    {" : "\n    {", f);
    jkv_str(f, "binding", mr->name, 1);
    fprintf(f, "\"primary\": %s, ", mr->primary ? "true" : "false");
    jkv_str(f, "verdict", verdict_id(mr->verdict), 1);
    jkv_str(f, "reason", mr->reason, 1);
    jkv_str(f, "error", mr->error[0] ? mr->error : NULL, 1);
    fprintf(f, "\"vertex_input_library_ms\": %.4f, \"fragment_output_library_ms\": %.4f,\n      ",
            mr->viLibMs, mr->foLibMs);
    jarm(f, "arm_a", "declares and reads BuiltIn PointCoord", &mr->arm[ARM_A]);
    fputs(",\n      ", f);
    jarm(f, "arm_b", "identical, no PointCoord", &mr->arm[ARM_B]);
    fputs("}", f);
  }
  fputs(nModes ? "\n  ],\n  " : "],\n  ", f);
  jkv_str(f, "verdict", verdict, 1);
  jkv_str(f, "verdict_binding", verdictMode, 1);
  fputs("\n  ", f);
  jkv_str(f, "verdict_line", verdictLine, 0);
  fputs("\n}\n", f);
  return fclose(f) == 0;
}

/* ------------------------------------------------------------------------ */
/* Setup                                                                    */

static int has_ext(const VkExtensionProperties* e, uint32_t n, const char* name) {
  uint32_t i;
  for (i = 0; i < n; i++)
    if (!strcmp(e[i].extensionName, name))
      return 1;
  return 0;
}

static void get_props(VkPhysicalDevice pd, VkPhysicalDeviceProperties2* p2,
                      VkPhysicalDeviceDriverProperties* drv,
                      VkPhysicalDeviceGraphicsPipelineLibraryPropertiesEXT* gpl) {
  memset(p2, 0, sizeof(*p2));
  memset(drv, 0, sizeof(*drv));
  p2->sType = VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_PROPERTIES_2;
  drv->sType = VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_DRIVER_PROPERTIES;
  p2->pNext = drv;
  if (gpl) {
    memset(gpl, 0, sizeof(*gpl));
    gpl->sType = VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_GRAPHICS_PIPELINE_LIBRARY_PROPERTIES_EXT;
    drv->pNext = gpl;
  }
  p_vkGetPhysicalDeviceProperties2(pd, p2);
  p2->pNext = NULL;
  drv->pNext = NULL;
}

static int streq_i(const char* a, const char* b) {
  for (; *a && *b; a++, b++) {
    char x = *a, y = *b;
    if (x >= 'A' && x <= 'Z') x = (char)(x - 'A' + 'a');
    if (y >= 'A' && y <= 'Z') y = (char)(y - 'A' + 'a');
    if (x != y) return 0;
  }
  return *a == *b;
}

static int opt_is(const char* arg, const char* name) {
  while (*arg == '-' || *arg == '/') arg++;
  return streq_i(arg, name);
}

static void usage(void) {
  printf("usage: x0 [-Json <path>] [-Iterations <n>] [-Warmup <n>]\n"
         "          [-Binding auto|both|heap|legacy] [-Device <index>]\n"
         "          [-AppName <name>] [-EngineName <name>]\n"
         "  -Binding auto   the binding model DXVK 3.1.1 would use on this device (default)\n"
         "           both   that one first, then the other as a cross-check\n"
         "  -FixedNonce <hex>  diagnostic: reuse one nonce, so repeats may hit the\n"
         "                     driver cache (NOT cold; shows what the nonce prevents)\n");
}

int main(int argc, char** argv) {
  Config cfg;
  Ctx c;
  VkApplicationInfo app = { VK_STRUCTURE_TYPE_APPLICATION_INFO };
  VkInstanceCreateInfo ici = { VK_STRUCTURE_TYPE_INSTANCE_CREATE_INFO };
  VkPhysicalDevice pds[16];
  uint32_t npd = 16, loaderVer = VK_API_VERSION_1_0, i;
  VkExtensionProperties* exts = NULL;
  uint32_t next = 0;
  ModeResult* modes = NULL;
  int nModes = 0, mi, gplOk = 0, rc = 0, primaryHeap = 0, dxvkWouldUseGpl;
  int armAPc, armBPc;
  const char* dxvkModel = "legacy";
  char verdictLine[1024];
  const char* verdict = "NONE";
  const char* verdictMode = NULL;
  VkResult r;

#ifdef _WIN32
  setvbuf(stdout, NULL, _IONBF, 0);
#endif

  memset(&cfg, 0, sizeof(cfg));
  memset(&c, 0, sizeof(c));
  cfg.binding = "auto";
  cfg.appName = "GTAIV.exe";   /* what DXVK passes: the host exe name */
  cfg.engineName = "DXVK";     /* drivers key app profiles on this    */
  cfg.iterations = 25;
  cfg.warmup = 2;
  cfg.device = -1;
  verdictLine[0] = 0;

  for (mi = 1; mi < argc; mi++) {
    const char* a = argv[mi];
    const char* v = mi + 1 < argc ? argv[mi + 1] : NULL;
    if (opt_is(a, "h") || opt_is(a, "help") || opt_is(a, "?")) { usage(); return 0; }
    if (!v) { usage(); return 3; }
    if      (opt_is(a, "json"))       cfg.jsonPath = v;
    else if (opt_is(a, "iterations")) cfg.iterations = atoi(v);
    else if (opt_is(a, "warmup"))     cfg.warmup = atoi(v);
    else if (opt_is(a, "binding"))    cfg.binding = v;
    else if (opt_is(a, "device"))     cfg.device = atoi(v);
    else if (opt_is(a, "appname"))    cfg.appName = v;
    else if (opt_is(a, "enginename")) cfg.engineName = v;
    else if (opt_is(a, "fixednonce")) { g_fixedNonce = 1; g_seed = (uint32_t)strtoul(v, NULL, 16); }
    else { usage(); return 3; }
    mi++;
  }
  if (cfg.iterations < 1 || cfg.iterations > MAX_ITERS || cfg.warmup < 0 || cfg.warmup > 50) {
    fprintf(stderr, "x0: -Iterations must be 1..%d, -Warmup 0..50\n", MAX_ITERS);
    return 3;
  }
  if (!streq_i(cfg.binding, "auto") && !streq_i(cfg.binding, "both")
   && !streq_i(cfg.binding, "heap") && !streq_i(cfg.binding, "legacy")) {
    usage();
    return 3;
  }

  printf("X0 v%s (source %.12s, %d-bit %s): does a PointCoord GPL fragment library fast-link?\n",
         X0_VERSION, X0_SOURCE_SHA, (int)(sizeof(void*) * 8), X0_PLATFORM);

  /* Shaders: nonce placeholders, and the one intended difference between the arms */
  if (!spv_init(&g_vs, "VS", x0_vs_spv, sizeof(x0_vs_spv), PH_VS)
   || !spv_init(&g_fs[ARM_A], "FS arm A", x0_fs_a_spv, sizeof(x0_fs_a_spv), PH_FS)
   || !spv_init(&g_fs[ARM_B], "FS arm B", x0_fs_b_spv, sizeof(x0_fs_b_spv), PH_FS))
    return 1;
  armAPc = spv_has_builtin(&g_fs[ARM_A], SPV_BUILTIN_POINTCOORD);
  armBPc = spv_has_builtin(&g_fs[ARM_B], SPV_BUILTIN_POINTCOORD);
  printf("shader check: arm A declares BuiltIn PointCoord: %s; arm B: %s\n",
         armAPc ? "yes" : "NO", armBPc ? "YES" : "no");
  if (!armAPc || armBPc) {
    fprintf(stderr, "x0: embedded shaders are wrong; rebuild\n");
    return 1;
  }
  if (g_fixedNonce) {
    if (g_seed == PH_FS || g_seed == PH_VS)
      g_seed ^= 1u;
    printf("DIAGNOSTIC -FixedNonce 0x%08x: every library reuses the same SPIR-V, so the\n"
           "runs after the first are NOT cold. Do not report this as the X0 result.\n", g_seed);
  } else {
    seed_nonce();
  }

  if (!load_loader()) {
    printf("Vulkan loader not found (vulkan-1.dll / libvulkan.so.1). No Vulkan driver?\n");
    return 1;
  }
#define X0_LOAD_G(n) p_##n = (PFN_##n)(void (*)(void))p_vkGetInstanceProcAddr(VK_NULL_HANDLE, #n);
  X0_GLOBAL_FNS(X0_LOAD_G)
  if (!p_vkCreateInstance) {
    printf("vkCreateInstance not found\n");
    return 1;
  }
  if (p_vkEnumerateInstanceVersion)
    p_vkEnumerateInstanceVersion(&loaderVer);
  if (loaderVer < VK_API_VERSION_1_3) {
    printf("Vulkan loader is %u.%u; DXVK 3.1.1 and X0 need 1.3\n",
           VK_API_VERSION_MAJOR(loaderVer), VK_API_VERSION_MINOR(loaderVer));
    return 1;
  }

  /* Same identity DXVK presents (dxvk_instance.cpp) */
  app.pApplicationName = cfg.appName;
  app.applicationVersion = 1;   /* DxvkInstanceFlag::ClientApiIsD3D9 */
  app.pEngineName = cfg.engineName;
  app.engineVersion = VK_MAKE_API_VERSION(0, 3, 1, 1);
  app.apiVersion = VK_API_VERSION_1_3;
  ici.pApplicationInfo = &app;
  r = p_vkCreateInstance(&ici, NULL, &c.inst);
  if (r != VK_SUCCESS) {
    char b[48];
    printf("vkCreateInstance: %s\n", res_name(r, b, sizeof(b)));
    return 1;
  }
#define X0_LOAD_I(n) p_##n = (PFN_##n)(void (*)(void))p_vkGetInstanceProcAddr(c.inst, #n);
  X0_INSTANCE_FNS(X0_LOAD_I)

  r = p_vkEnumeratePhysicalDevices(c.inst, &npd, pds);
  if ((r != VK_SUCCESS && r != VK_INCOMPLETE) || npd == 0) {
    printf("no Vulkan physical devices\n");
    rc = 1;
    goto json;
  }

  /* List every device; pick -Device, else the first discrete GPU, else #0 */
  c.devIndex = -1;
  printf("devices:\n");
  for (i = 0; i < npd; i++) {
    VkPhysicalDeviceProperties2 p2;
    VkPhysicalDeviceDriverProperties dp;
    get_props(pds[i], &p2, &dp, NULL);
    printf("  [%u] %s (%s) -- %s, %s\n", i, p2.properties.deviceName,
           device_type_name(p2.properties.deviceType), dp.driverName, dp.driverInfo);
    if (cfg.device < 0 && c.devIndex < 0
     && p2.properties.deviceType == VK_PHYSICAL_DEVICE_TYPE_DISCRETE_GPU)
      c.devIndex = (int)i;
  }
  if (cfg.device >= 0) {
    if ((uint32_t)cfg.device >= npd) {
      printf("-Device %d does not exist\n", cfg.device);
      rc = 3;
      goto json;
    }
    c.devIndex = cfg.device;
  }
  if (c.devIndex < 0)
    c.devIndex = 0;
  c.pd = pds[c.devIndex];

  p_vkEnumerateDeviceExtensionProperties(c.pd, NULL, &next, NULL);
  exts = (VkExtensionProperties*)calloc(next ? next : 1, sizeof(*exts));
  if (!exts) { rc = 1; goto json; }
  p_vkEnumerateDeviceExtensionProperties(c.pd, NULL, &next, exts);
  c.extPipeLib = has_ext(exts, next, VK_KHR_PIPELINE_LIBRARY_EXTENSION_NAME);
  c.extGpl     = has_ext(exts, next, VK_EXT_GRAPHICS_PIPELINE_LIBRARY_EXTENSION_NAME);
  c.extMaint5  = has_ext(exts, next, VK_KHR_MAINTENANCE_5_EXTENSION_NAME);
  c.extEds3    = has_ext(exts, next, VK_EXT_EXTENDED_DYNAMIC_STATE_3_EXTENSION_NAME);
  c.extHeap    = has_ext(exts, next, VK_EXT_DESCRIPTOR_HEAP_EXTENSION_NAME);
  c.extDescBuf = has_ext(exts, next, VK_EXT_DESCRIPTOR_BUFFER_EXTENSION_NAME);

  get_props(c.pd, &c.props, &c.drv, c.extGpl ? &c.gplProps : NULL);

  {
    VkPhysicalDeviceFeatures2 f2 = { VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_FEATURES_2 };
    VkPhysicalDeviceVulkan12Features f12 = { VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_VULKAN_1_2_FEATURES };
    VkPhysicalDeviceVulkan13Features f13 = { VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_VULKAN_1_3_FEATURES };
    VkPhysicalDeviceGraphicsPipelineLibraryFeaturesEXT fg = { VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_GRAPHICS_PIPELINE_LIBRARY_FEATURES_EXT };
    VkPhysicalDeviceMaintenance5Features fm5 = { VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_MAINTENANCE_5_FEATURES };
    VkPhysicalDeviceExtendedDynamicState3FeaturesEXT fe3 = { VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_EXTENDED_DYNAMIC_STATE_3_FEATURES_EXT };
    VkPhysicalDeviceDescriptorHeapFeaturesEXT fh = { VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_DESCRIPTOR_HEAP_FEATURES_EXT };
    VkPhysicalDeviceDescriptorBufferFeaturesEXT fdb = { VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_DESCRIPTOR_BUFFER_FEATURES_EXT };
    void** tail = &f13.pNext;

    f2.pNext = &f12;
    f12.pNext = &f13;
    if (c.extGpl)     { *tail = &fg;  tail = &fg.pNext; }
    if (c.extMaint5)  { *tail = &fm5; tail = &fm5.pNext; }
    if (c.extEds3)    { *tail = &fe3; tail = &fe3.pNext; }
    if (c.extHeap)    { *tail = &fh;  tail = &fh.pNext; }
    if (c.extDescBuf) { *tail = &fdb; tail = &fdb.pNext; }
    p_vkGetPhysicalDeviceFeatures2(c.pd, &f2);

    c.featGpl           = c.extGpl && c.extPipeLib && fg.graphicsPipelineLibrary;
    c.featMaint5        = c.extMaint5 && fm5.maintenance5;
    c.featEds3DepthClip = c.extEds3 && fe3.extendedDynamicState3DepthClipEnable;
    c.featHeap          = c.extHeap && fh.descriptorHeap;
    c.featDescBuf       = c.extDescBuf && fdb.descriptorBuffer;
    c.featDepthClamp    = f2.features.depthClamp;
    c.featDepthBounds   = f2.features.depthBounds;
    c.featDynRendering  = f13.dynamicRendering;
    c.featCacheControl  = f13.pipelineCreationCacheControl;
    c.featBda           = f12.bufferDeviceAddress;
  }

  {
    uint32_t av = c.props.properties.apiVersion, dv = c.props.properties.driverVersion;
    printf("selected [%d]: %s\n", c.devIndex, c.props.properties.deviceName);
    printf("  driverName   : %s\n", c.drv.driverName);
    printf("  driverInfo   : %s\n", c.drv.driverInfo);
    printf("  driverID     : %d (%s)\n", (int)c.drv.driverID, driver_id_name(c.drv.driverID));
    printf("  apiVersion   : %u.%u.%u   driverVersion: %u.%u.%u (0x%08x)\n",
           VK_API_VERSION_MAJOR(av), VK_API_VERSION_MINOR(av), VK_API_VERSION_PATCH(av),
           VK_VERSION_MAJOR(dv), VK_VERSION_MINOR(dv), VK_VERSION_PATCH(dv), dv);
    printf("  VK_EXT_graphics_pipeline_library: %s (feature %s, fastLinking %s, "
           "independentInterpolationDecoration %s)\n",
           c.extGpl ? "present" : "ABSENT", c.featGpl ? "on" : "off",
           c.gplProps.graphicsPipelineLibraryFastLinking ? "yes" : "no",
           c.gplProps.graphicsPipelineLibraryIndependentInterpolationDecoration ? "yes" : "no");
  }

  if (c.featHeap)         dxvkModel = "descriptor_heap";
  else if (c.featDescBuf) dxvkModel = "descriptor_buffer";
  dxvkWouldUseGpl = c.featGpl && c.gplProps.graphicsPipelineLibraryIndependentInterpolationDecoration;

  gplOk = c.featGpl;
  if (!gplOk) {
    printf("\nVK_EXT_graphics_pipeline_library is NOT SUPPORTED on this device.\n"
           "X0 cannot run, and DXVK does not use pipeline libraries here either.\n");
    verdict = "NO_GPL";
    snprintf(verdictLine, sizeof(verdictLine),
             "VERDICT: NO_GPL -- %s (%s) does not support VK_EXT_graphics_pipeline_library",
             c.drv.driverName, c.drv.driverInfo);
    printf("%s\n", verdictLine);
    rc = 2;
    goto json;
  }
  if (!dxvkWouldUseGpl)
    printf("  NOTE: no graphicsPipelineLibraryIndependentInterpolationDecoration, so DXVK 3.1.1\n"
           "        would NOT use GPL on this device; X0 runs anyway.\n");
  if (VK_API_VERSION_MINOR(c.props.properties.apiVersion) < 3 && VK_API_VERSION_MAJOR(c.props.properties.apiVersion) == 1) {
    printf("device is Vulkan %u.%u; X0 needs 1.3\n", VK_API_VERSION_MAJOR(c.props.properties.apiVersion),
           VK_API_VERSION_MINOR(c.props.properties.apiVersion));
    rc = 1;
    goto json;
  }
  if (!c.featDynRendering || !c.featCacheControl) {
    printf("device lacks dynamicRendering or pipelineCreationCacheControl\n");
    rc = 1;
    goto json;
  }

  /* Which binding models to run. DXVK: heap if supported, else descriptor
   * buffer, else legacy. X0 runs heap, or legacy (standing in for both). */
  primaryHeap = c.featHeap && c.featMaint5;
  {
    int wantHeap = 0, wantLegacy = 0;
    if (streq_i(cfg.binding, "auto"))        { wantHeap = primaryHeap; wantLegacy = !primaryHeap; }
    else if (streq_i(cfg.binding, "both"))   { wantHeap = primaryHeap; wantLegacy = 1; }
    else if (streq_i(cfg.binding, "heap"))   { wantHeap = 1; }
    else                                     { wantLegacy = 1; }
    if (wantHeap && !(c.featHeap && c.featMaint5)) {
      printf("-Binding heap: VK_EXT_descriptor_heap (with maintenance5) is not available\n");
      rc = 3;
      goto json;
    }
    modes = (ModeResult*)calloc(2, sizeof(ModeResult));
    if (!modes) { rc = 1; goto json; }
    if (wantHeap) {
      modes[nModes].name = "heap";
      modes[nModes].heap = 1;
      modes[nModes].primary = primaryHeap;
      nModes++;
    }
    if (wantLegacy) {
      modes[nModes].name = "legacy";
      modes[nModes].heap = 0;
      modes[nModes].primary = !primaryHeap;
      nModes++;
    }
    if (!modes[0].primary && nModes == 1)
      modes[0].primary = 1;  /* forced single mode: it is the verdict */
  }
  printf("  DXVK 3.1.1 binding model here: %s -> X0 runs: ", dxvkModel);
  for (mi = 0; mi < nModes; mi++)
    printf("%s%s%s", mi ? ", " : "", modes[mi].name, modes[mi].primary ? " (verdict)" : " (cross-check)");
  printf("\n");

  /* Device, with what DXVK would enable for this path */
  {
    float prio = 1.0f;
    uint32_t nq = 0, qfi = 0;
    VkQueueFamilyProperties qf[32];
    VkDeviceQueueCreateInfo qci = { VK_STRUCTURE_TYPE_DEVICE_QUEUE_CREATE_INFO };
    VkDeviceCreateInfo dci = { VK_STRUCTURE_TYPE_DEVICE_CREATE_INFO };
    VkPhysicalDeviceFeatures2 f2 = { VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_FEATURES_2 };
    VkPhysicalDeviceVulkan12Features f12 = { VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_VULKAN_1_2_FEATURES };
    VkPhysicalDeviceVulkan13Features f13 = { VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_VULKAN_1_3_FEATURES };
    VkPhysicalDeviceGraphicsPipelineLibraryFeaturesEXT fg = { VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_GRAPHICS_PIPELINE_LIBRARY_FEATURES_EXT };
    VkPhysicalDeviceMaintenance5Features fm5 = { VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_MAINTENANCE_5_FEATURES };
    VkPhysicalDeviceExtendedDynamicState3FeaturesEXT fe3 = { VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_EXTENDED_DYNAMIC_STATE_3_FEATURES_EXT };
    VkPhysicalDeviceDescriptorHeapFeaturesEXT fh = { VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_DESCRIPTOR_HEAP_FEATURES_EXT };
    const char* dexts[8];
    uint32_t nde = 0;
    void** tail = &f13.pNext;
    VkFormat cands[3] = { VK_FORMAT_D32_SFLOAT_S8_UINT, VK_FORMAT_D24_UNORM_S8_UINT, VK_FORMAT_D32_SFLOAT };

    nq = 32;
    p_vkGetPhysicalDeviceQueueFamilyProperties(c.pd, &nq, qf);
    for (i = 0; i < nq; i++)
      if (qf[i].queueFlags & VK_QUEUE_GRAPHICS_BIT) { qfi = i; break; }
    qci.queueFamilyIndex = qfi;
    qci.queueCount = 1;
    qci.pQueuePriorities = &prio;

    c.useMaint5 = c.featMaint5;
    c.useEds3DepthClip = c.featEds3DepthClip;
    c.useHeap = primaryHeap || (nModes && modes[0].heap);
    c.useDepthClamp = c.featDepthClamp;
    c.useDepthBounds = c.featDepthBounds;

    dexts[nde++] = VK_KHR_PIPELINE_LIBRARY_EXTENSION_NAME;
    dexts[nde++] = VK_EXT_GRAPHICS_PIPELINE_LIBRARY_EXTENSION_NAME;
    if (c.useMaint5)        dexts[nde++] = VK_KHR_MAINTENANCE_5_EXTENSION_NAME;
    if (c.useEds3DepthClip) dexts[nde++] = VK_EXT_EXTENDED_DYNAMIC_STATE_3_EXTENSION_NAME;
    if (c.useHeap)          dexts[nde++] = VK_EXT_DESCRIPTOR_HEAP_EXTENSION_NAME;

    f2.features.depthClamp = c.useDepthClamp ? VK_TRUE : VK_FALSE;
    f2.features.depthBounds = c.useDepthBounds ? VK_TRUE : VK_FALSE;
    f12.bufferDeviceAddress = (c.useHeap && c.featBda) ? VK_TRUE : VK_FALSE;
    f13.dynamicRendering = VK_TRUE;
    f13.pipelineCreationCacheControl = VK_TRUE;   /* required for FAIL_ON_... */
    fg.graphicsPipelineLibrary = VK_TRUE;
    fm5.maintenance5 = VK_TRUE;
    fe3.extendedDynamicState3DepthClipEnable = VK_TRUE;
    fh.descriptorHeap = VK_TRUE;

    f2.pNext = &f12;
    f12.pNext = &f13;
    *tail = &fg; tail = &fg.pNext;
    if (c.useMaint5)        { *tail = &fm5; tail = &fm5.pNext; }
    if (c.useEds3DepthClip) { *tail = &fe3; tail = &fe3.pNext; }
    if (c.useHeap)          { *tail = &fh;  tail = &fh.pNext; }

    dci.pNext = &f2;
    dci.queueCreateInfoCount = 1;
    dci.pQueueCreateInfos = &qci;
    dci.enabledExtensionCount = nde;
    dci.ppEnabledExtensionNames = dexts;
    r = p_vkCreateDevice(c.pd, &dci, NULL, &c.dev);
    if (r != VK_SUCCESS) {
      char b[48];
      printf("vkCreateDevice: %s\n", res_name(r, b, sizeof(b)));
      rc = 1;
      goto json;
    }
#define X0_LOAD_D(n) p_##n = (PFN_##n)(void (*)(void))p_vkGetDeviceProcAddr(c.dev, #n);
    X0_DEVICE_FNS(X0_LOAD_D)

    c.depthFormat = VK_FORMAT_UNDEFINED;
    for (i = 0; i < 3; i++) {
      VkFormatProperties fp;
      p_vkGetPhysicalDeviceFormatProperties(c.pd, cands[i], &fp);
      if (fp.optimalTilingFeatures & VK_FORMAT_FEATURE_DEPTH_STENCIL_ATTACHMENT_BIT) {
        c.depthFormat = cands[i];
        c.depthHasStencil = cands[i] != VK_FORMAT_D32_SFLOAT;
        break;
      }
    }
  }

  printf("identity: application \"%s\", engine \"%s\" 3.1.1 (what DXVK presents; driver app profiles key on it)\n",
         cfg.appName, cfg.engineName);
  printf("cache env: AMD_VK_PIPELINE_CACHE_PATH=%s\n"
         "           AMD_VK_USE_PIPELINE_CACHE=%s AMD_VK_PIPELINE_CACHE_FILENAME=%s\n",
         getenv("AMD_VK_PIPELINE_CACHE_PATH") ? getenv("AMD_VK_PIPELINE_CACHE_PATH") : "(unset)",
         getenv("AMD_VK_USE_PIPELINE_CACHE") ? getenv("AMD_VK_USE_PIPELINE_CACHE") : "(unset)",
         getenv("AMD_VK_PIPELINE_CACHE_FILENAME") ? getenv("AMD_VK_PIPELINE_CACHE_FILENAME") : "(unset)");
  if (!g_fixedNonce)
    printf("every library gets never-seen SPIR-V (nonce seed 0x%08x), so every compile is cold\n\n",
           g_seed);
  else
    printf("\n");

  for (mi = 0; mi < nModes; mi++)
    run_mode(&c, &cfg, &modes[mi]);

  for (mi = 0; mi < nModes; mi++)
    print_mode(&modes[mi], modes[mi].primary
      ? "  (the binding model DXVK 3.1.1 uses here: this is the verdict)"
      : "  (cross-check)");

  /* Verdict line, from the primary mode. If that mode could not run at all,
   * fall back to the cross-check and say so. */
  {
    const ModeResult* pm = NULL;
    const ModeResult* used;
    for (mi = 0; mi < nModes; mi++)
      if (modes[mi].primary) pm = &modes[mi];
    used = pm;
    if (pm && pm->verdict == V_ERROR)
      for (mi = 0; mi < nModes; mi++)
        if (&modes[mi] != pm && modes[mi].verdict != V_ERROR) { used = &modes[mi]; break; }
    if (used) {
      verdict = verdict_id(used->verdict);
      verdictMode = used->name;
      verdict_line(verdictLine, sizeof(verdictLine), &c, used);
      if (used != pm) {
        size_t len = strlen(verdictLine);
        snprintf(verdictLine + len, sizeof(verdictLine) - len,
                 " [%s mode failed: %s; verdict from the %s cross-check]", pm->name, pm->reason, used->name);
      }
    }
  }
  if (g_fixedNonce) {
    size_t len = strlen(verdictLine);
    snprintf(verdictLine + len, sizeof(verdictLine) - len, " [DIAGNOSTIC -FixedNonce: NOT cold]");
    verdict = "DIAGNOSTIC_NOT_COLD";
  }
  if (nModes == 2 && modes[0].verdict != modes[1].verdict)
    printf("\nNOTE: the two binding models disagree (%s: %s, %s: %s). Report both.\n",
           modes[0].name, verdict_id(modes[0].verdict), modes[1].name, verdict_id(modes[1].verdict));
  printf("\n%s\n", verdictLine);
  if (!strcmp(verdict, "ERROR"))
    rc = 1;

json:
  if (!rc && !verdictLine[0])
    rc = 1;
  if (!verdictLine[0])
    snprintf(verdictLine, sizeof(verdictLine), "VERDICT: ERROR -- X0 did not reach a measurement (see output)");
  if (!strcmp(verdict, "NONE"))
    verdict = "ERROR";
  if (cfg.jsonPath) {
    if (write_json(cfg.jsonPath, &cfg, &c, c.pd != VK_NULL_HANDLE, gplOk, dxvkModel, modes, nModes,
                   armAPc, armBPc, verdict, verdictMode, verdictLine))
      printf("wrote %s\n", cfg.jsonPath);
    else {
      printf("could not write %s\n", cfg.jsonPath);
      if (!rc) rc = 1;
    }
  }

  if (c.dev != VK_NULL_HANDLE)
    p_vkDestroyDevice(c.dev, NULL);
  if (c.inst != VK_NULL_HANDLE)
    p_vkDestroyInstance(c.inst, NULL);
  free(exts);
  free(modes);
  return rc;
}
