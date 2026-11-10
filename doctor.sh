
#!/usr/bin/env bash
# AI3D — read-only dependency audit
set -uo pipefail

ROOT="${AI3D_ROOT:-$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)}"
SD_ROOT="${SD_ROOT:-$ROOT/stable-diffusion.cpp}"
SD_CLI="${SD_CLI:-$SD_ROOT/build/bin/sd-cli}"
HUN_ROOT="${HUNYUAN_ROOT:-$ROOT/Hunyuan3D-2}"
PAINT_ROOT="${PAINT3D_ROOT:-$ROOT/AiGameKit/Paint3D}"
HUN_MODEL="${HUNYUAN_MODEL_ROOT:-$ROOT/models/Hunyuan3D-2mini}"
QWEN_MODEL="${QWEN_MODEL_ROOT:-$HOME/models/Qwen-Image-2512}"
DEEP=0
FAILED=0
WARNED=0

case "${1:-}" in
  "") ;;
  --deep) DEEP=1 ;;
  --help|-h) echo 'Usage: bash doctor.sh [--deep]'; exit 0 ;;
  *) echo "Unknown option: $1" >&2; exit 2 ;;
esac
[[ $# -le 1 ]] || { echo 'Too many arguments' >&2; exit 2; }

ok()      { printf '[OK]      %-23s %s\n' "$1" "$2"; }
warn()    { printf '[WARN]    %-23s %s\n' "$1" "$2"; WARNED=$((WARNED + 1)); }
fail()    { printf '[MISSING] %-23s %s\n' "$1" "$2"; FAILED=$((FAILED + 1)); }
section() { printf '\n=== %s ===\n' "$1"; }

check_cmd() {
  local found
  found="$(command -v "$2" 2>/dev/null)" || true
  if [[ -n "$found" ]]; then ok "$1" "$found"; else fail "$1" "$2 not found"; fi
}

check_file() {
  if [[ -s "$2" ]]; then ok "$1" "$2"; else fail "$1" "$2"; fi
}

check_python() {
  local label="$1" root="$2" modules="$3" py
  py="$root/.venv/bin/python"

  if [[ ! -x "$py" || ! -f "$root/.venv/pyvenv.cfg" ]]; then
    fail "$label environment" "$root/.venv"
    return
  fi

  ok "$label Python" "$("$py" --version 2>&1) — $py"

  if PYTHONPATH="$root:$root/src${PYTHONPATH:+:$PYTHONPATH}" \
      "$py" -c 'import importlib.util,sys; missing=[m for m in sys.argv[1:] if importlib.util.find_spec(m) is None]; print("    Missing modules:", ", ".join(missing)) if missing else None; sys.exit(bool(missing))' $modules; then
    ok "$label packages" 'Required module names found'
  else
    fail "$label packages" 'One or more required modules unavailable'
  fi

  if (( DEEP )); then
    if "$py" -c 'import torch; print("    PyTorch:", torch.__version__, "runtime CUDA:", torch.version.cuda, flush=True); assert torch.cuda.is_available(), "CUDA unavailable"; print("    GPU:", torch.cuda.get_device_name(0), flush=True)' ; then
      ok "$label CUDA" 'PyTorch GPU initialization successful'
    else
      fail "$label CUDA" 'PyTorch could not initialize GPU'
    fi
  fi
}

printf 'AI3D dependency doctor (read-only)\n'
printf 'AI3D root: %s\n' "$ROOT"

section 'System tools'
check_cmd Git git
check_cmd CMake cmake
check_cmd 'C++ compiler' g++
check_cmd Blender blender
check_cmd Python3 python3
check_cmd systemd-run systemd-run

if command -v ninja >/dev/null 2>&1; then
  ok Ninja "$(command -v ninja)"
elif [[ -x "$HUN_ROOT/.venv/bin/ninja" ]]; then
  ok Ninja "$HUN_ROOT/.venv/bin/ninja"
else
  fail Ninja 'Not found on PATH or in Hunyuan venv'
fi

section 'NVIDIA / CUDA'

if command -v nvidia-smi >/dev/null 2>&1; then
  gpu="$(nvidia-smi --query-gpu=name,driver_version,compute_cap --format=csv,noheader 2>/dev/null | head -n 1)" || true
  if [[ -n "$gpu" ]]; then ok GPU "$gpu"; else fail GPU 'nvidia-smi failed'; fi
else
  fail GPU 'nvidia-smi not found'
fi

if command -v nvcc >/dev/null 2>&1; then
  ok 'CUDA compiler' "$(nvcc --version | grep 'release' | tail -n 1)"
else
  warn 'CUDA compiler' 'nvcc unavailable; CUDA builds require a compatible toolkit'
fi

section 'Source-built inference'

if [[ -L "$SD_ROOT" && ! -d "$SD_ROOT" ]]; then
  fail 'sd.cpp symlink' "Broken symlink: $SD_ROOT"
elif [[ -L "$SD_ROOT" ]]; then
  ok 'sd.cpp symlink' "$(readlink -- "$SD_ROOT")"
fi

if [[ -x "$SD_CLI" ]]; then
  ok stable-diffusion.cpp "$SD_CLI"
  cache="$SD_ROOT/build/CMakeCache.txt"

  if [[ -f "$cache" ]] && grep -Eq '^(SD_CUDA|GGML_CUDA):BOOL=ON$' "$cache"; then
    ok 'sd.cpp CUDA flags' 'CMake cache confirms CUDA enabled'
  else
    warn 'sd.cpp CUDA flags' 'Cannot verify CUDA build configuration'
  fi
else
  fail stable-diffusion.cpp "$SD_CLI"
fi

section 'Python environments'
check_python Hunyuan "$HUN_ROOT" 'torch numpy trimesh PIL hy3dgen'
check_python Paint3D "$PAINT_ROOT" 'torch numpy PIL paint3d'

section 'Model file presence'
check_file Hunyuan3D-2mini "$HUN_MODEL/hunyuan3d-dit-v2-mini/model.fp16.safetensors"
check_file Qwen-Image "$QWEN_MODEL/qwen-image-2512-Q3_K_M.gguf"
check_file 'Qwen vision model' "$QWEN_MODEL/Qwen2.5-VL-7B-Instruct-Q4_K_M.gguf"
check_file 'Qwen image VAE' "$QWEN_MODEL/qwen_image_vae.safetensors"

warn 'Paint3D weights' 'Weight locations/checksums are not yet audited'

section Summary
printf 'Missing/failed: %d | Warnings/unverified: %d\n' "$FAILED" "$WARNED"

(( FAILED == 0 )) || exit 1
printf 'Basic checks passed. This is not a full inference test.\n'

