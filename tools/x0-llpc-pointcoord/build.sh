#!/usr/bin/env bash
# Build X0.
#   x0.exe      32-bit Windows, written next to this script (the committed prebuilt)
#   x0-linux    native Linux x86_64, in the build dir, for validating on RADV
#
# x0.exe is built with MSVC /MT through msvc-wine (static CRT: imports only
# KERNEL32.dll). Without msvc-wine it falls back to mingw-w64, which imports the
# UCRT that ships with Windows 10/11.
#
# Needs: glslangValidator, spirv-val, gcc, Vulkan headers in /usr/include/vulkan,
# and msvc-wine ($MSVC_BIN, default ~/.local/opt/msvc/bin/x86) + wine, or
# i686-w64-mingw32-gcc. Intermediates and the Wine prefix go to $X0_BUILD_DIR
# (default: under $XDG_RUNTIME_DIR, else /tmp), never into the repo.
#
# Run: bash tools/x0-llpc-pointcoord/build.sh
set -euo pipefail

here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
out=${X0_BUILD_DIR:-${XDG_RUNTIME_DIR:-/tmp}/x0-build}
msvc_bin=${MSVC_BIN:-$HOME/.local/opt/msvc/bin/x86}
mkdir -p "$out/inc"

# 1. SPIR-V. Validate the binaries, then emit them as C arrays for x0.c.
glsl() {  # <name> <source> [defines...]
  local name=$1 src=$2; shift 2
  glslangValidator -V --target-env vulkan1.3 "$@" -o "$out/$name.spv" "$src" >/dev/null
  spirv-val --target-env vulkan1.3 "$out/$name.spv"
  glslangValidator -V --target-env vulkan1.3 "$@" --vn "$name" -o "$out/$name.h" "$src" >/dev/null
}
glsl x0_vs_spv   "$here/shaders/x0.vert"
glsl x0_fs_a_spv "$here/shaders/x0.frag" -DX0_POINTCOORD
glsl x0_fs_b_spv "$here/shaders/x0.frag"

# 2. Source hash, baked into the binary and printed by it.
src_sha=$(cat "$here/x0.c" "$here/shaders/x0.vert" "$here/shaders/x0.frag" | sha256sum | cut -d' ' -f1)

# 3. The Windows compilers do not search /usr/include; expose only the Vulkan headers.
ln -sfn /usr/include/vulkan   "$out/inc/vulkan"
ln -sfn /usr/include/vk_video "$out/inc/vk_video"

# 4. Windows, 32-bit like GTA IV.
if [[ -x $msvc_bin/cl ]]; then
  export WINEPREFIX=${X0_WINEPREFIX:-$out/wineprefix} WINEDEBUG=-all
  [[ -d $WINEPREFIX ]] || wineboot -i >"$out/wineboot.log" 2>&1
  # wineserver inherits and holds output fds: log to a file, never pipe cl.
  # -Brepro: no timestamp, so the same source and toolchain give the same bytes.
  if ! "$msvc_bin/cl" -nologo -O2 -MT -TC -std:c11 -W3 -D_CRT_SECURE_NO_WARNINGS \
      "-DX0_SOURCE_SHA=\"$src_sha\"" -I"$out" -I"$out/inc" \
      -Fo"$out/x0.obj" -Fe"$here/x0.exe" "$here/x0.c" -link -Brepro >"$out/cl.log" 2>&1; then
    cat "$out/cl.log"
    exit 1
  fi
  toolchain="MSVC $(ls "$msvc_bin/../../vc/tools/msvc" | tail -n1) x86 /MT via msvc-wine"
else
  echo "msvc-wine not found at $msvc_bin; falling back to mingw-w64 (UCRT, not a static CRT)"
  i686-w64-mingw32-gcc -std=c11 -O2 -Wall -Wextra -Wno-missing-field-initializers \
    -I"$out" -I"$out/inc" -DX0_SOURCE_SHA="\"$src_sha\"" -static -static-libgcc -s \
    -Wl,--no-insert-timestamp -o "$here/x0.exe" "$here/x0.c"
  toolchain="$(i686-w64-mingw32-gcc --version | head -n1)"
fi

# 5. Linux, for validation only (not committed).
gcc -std=c11 -O2 -Wall -Wextra -Wno-missing-field-initializers -I"$out" \
  -DX0_SOURCE_SHA="\"$src_sha\"" -o "$out/x0-linux" "$here/x0.c" -ldl

echo "toolchain     : $toolchain"
echo "source sha256 : $src_sha"
echo "x0.exe sha256 : $(sha256sum "$here/x0.exe" | cut -d' ' -f1)"
echo "x0.exe imports: $(objdump -p "$here/x0.exe" | awk '/DLL Name/ {print $3}' | tr '\n' ' ')"
echo "linux build   : $out/x0-linux"
