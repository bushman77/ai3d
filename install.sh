
#!/usr/bin/env bash
# AI3D — dependency-aware installer (safe initial version)
# Default: dry run. --apply can build ONLY a missing stable-diffusion.cpp.
# Existing Hunyuan/Paint3D environments, models and drivers are never modified.
set -Eeuo pipefail

ROOT="${AI3D_ROOT:-$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)}"
SD_ROOT="${SD_ROOT:-$ROOT/stable-diffusion.cpp}"
SD_CLI="${SD_CLI:-$SD_ROOT/build/bin/sd-cli}"
HUN_ROOT="${HUNYUAN_ROOT:-$ROOT/Hunyuan3D-2}"
PAINT_ROOT="${PAINT3D_ROOT:-$ROOT/AiGameKit/Paint3D}"

SD_CPP_URL='https://github.com/leejet/stable-diffusion.cpp.git'
SD_CPP_COMMIT='d04e8950c1ec8d30248cbe996682b3182fb1adf6'

BUILD_JOBS="${BUILD_JOBS:-2}"
APPLY=0
ONLY=all
UNRESOLVED=0

usage() {
  cat <<'HELP'
Usage: bash install.sh [--dry-run] [--apply] [--only COMPONENT]

  --dry-run          Show what would be needed; make no changes (default).
  --apply            Allow building a MISSING stable-diffusion.cpp CUDA binary.
  --only COMPONENT   all | sd-cpp | hunyuan | paint3d

This is the initial safe installer, not yet a full fresh-machine setup.
It NEVER changes installed NVIDIA drivers, CUDA, Python environments,
PyTorch, model weights, or existing third-party source checkouts.

Default sd.cpp location: <AI3D_ROOT>/stable-diffusion.cpp (directory or symlink).
Existing symlinks are reused, never replaced or built through.
Overrides: AI3D_ROOT, SD_ROOT, SD_CLI,
           HUNYUAN_ROOT, PAINT3D_ROOT, BUILD_JOBS.
HELP
}

while (( $# )); do
  case "$1" in
    --apply) APPLY=1; shift ;;
    --dry-run) APPLY=0; shift ;;
    --only)
      [[ $# -ge 2 ]] || { usage >&2; exit 2; }
      ONLY="$2"; shift 2 ;;
    --help|-h) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; exit 2 ;;
  esac
done

case "$ONLY" in
  all|sd-cpp|hunyuan|paint3d) ;;
  *) echo "Invalid component: $ONLY" >&2; exit 2 ;;
esac

[[ "$BUILD_JOBS" =~ ^[1-9][0-9]*$ ]] || {
  echo 'BUILD_JOBS must be positive' >&2
  exit 2
}

reuse() { printf '[REUSE] %-21s %s\n' "$1" "$2"; }
need()  { printf '[NEEDS] %-21s %s\n' "$1" "$2"; UNRESOLVED=$((UNRESOLVED + 1)); }
info()  { printf '[INFO]  %-21s %s\n' "$1" "$2"; }
abort() { printf '[STOP] %s\n' "$*" >&2; exit 1; }

check_python() {
  local label="$1" root="$2" modules="$3" py
  py="$root/.venv/bin/python"

  if [[ -x "$py" && -f "$root/.venv/pyvenv.cfg" ]] &&
     PYTHONPATH="$root:$root/src${PYTHONPATH:+:$PYTHONPATH}" \
       "$py" -c 'import importlib.util,sys; sys.exit(any(importlib.util.find_spec(m) is None for m in sys.argv[1:]))' $modules; then
    reuse "$label" "$py (module discovery passed)"
  else
    need "$label" "Missing/incompatible environment at $root/.venv"
    info "$label setup" 'Not automated yet; preserve CUDA/PyTorch compatibility'
  fi
}

build_missing_sd() {
  local tool rev arch stage

  # A link is an external installation. Never build into or replace its target.
  [[ ! -L "$SD_ROOT" ]] || abort "Existing symlink at $SD_ROOT; refusing to build through or replace it"

  for tool in git cmake g++ nvcc nvidia-smi; do
    command -v "$tool" >/dev/null 2>&1 ||
      abort "Source build requires $tool"
  done

  if [[ -e "$SD_ROOT" && ! -d "$SD_ROOT" ]]; then
    abort "$SD_ROOT exists but is not a directory"
  fi

  if [[ ! -d "$SD_ROOT" ]]; then
    mkdir -p -- "$(dirname -- "$SD_ROOT")"
    stage="${SD_ROOT}.new-$$"

    [[ ! -e "$stage" ]] ||
      abort "Staging path already exists: $stage"

    info 'Clone source' "Pinned revision $SD_CPP_COMMIT"

    git clone --recursive "$SD_CPP_URL" "$stage" ||
      abort 'Clone failed; staged files left for inspection'

    git -C "$stage" checkout --detach "$SD_CPP_COMMIT" ||
      abort 'Revision checkout failed'

    git -C "$stage" submodule update --init --recursive ||
      abort 'Submodule setup failed'

    mv -- "$stage" "$SD_ROOT"
  fi

  rev="$(git -C "$SD_ROOT" rev-parse HEAD 2>/dev/null)" ||
    abort 'Existing source is not a Git checkout'

  [[ "$rev" == "$SD_CPP_COMMIT" ]] ||
    abort "Source is $rev, not pinned $SD_CPP_COMMIT; refusing reset"

  [[ -z "$(git -C "$SD_ROOT" status --porcelain --untracked-files=normal)" ]] ||
    abort 'Local source changes exist; refusing automatic build'

  [[ ! -e "$SD_ROOT/build" ]] ||
    abort 'Existing build directory detected; refusing to overwrite it'

  arch="$(nvidia-smi --query-gpu=compute_cap --format=csv,noheader 2>/dev/null | head -n 1 | tr -d '[:space:]')" || true

  [[ "$arch" =~ ^[0-9]+\.[0-9]+$ ]] ||
    abort "Cannot determine GPU architecture: $arch"

  arch="${arch/.}"
  info 'CUDA build' "Architecture $arch, jobs $BUILD_JOBS"

  cmake -S "$SD_ROOT" -B "$SD_ROOT/build" \
    -DSD_CUDA=ON \
    -DSD_BUILD_EXAMPLES=ON \
    -DCMAKE_CUDA_ARCHITECTURES="$arch" \
    -DCMAKE_BUILD_TYPE=Release

  cmake --build "$SD_ROOT/build" --parallel "$BUILD_JOBS"

  [[ -x "$SD_CLI" ]] ||
    abort "Build finished, but sd-cli missing at $SD_CLI"

  reuse 'sd.cpp built' "$SD_CLI"
}

check_sd() {
  if [[ -L "$SD_ROOT" && ! -d "$SD_ROOT" ]]; then
    abort "Broken stable-diffusion.cpp symlink: $SD_ROOT (repair the target before continuing)"
  fi

  if [[ -x "$SD_CLI" ]]; then
    reuse stable-diffusion.cpp "$SD_CLI"

    if [[ -f "$SD_ROOT/build/CMakeCache.txt" ]] &&
       grep -Eq '^(SD_CUDA|GGML_CUDA):BOOL=ON$' "$SD_ROOT/build/CMakeCache.txt"; then
      reuse 'sd.cpp CUDA' 'Enabled in CMake cache'
    else
      need 'sd.cpp CUDA' 'Cannot confirm CUDA-enabled binary; inspect manually'
    fi

    return
  fi

  need stable-diffusion.cpp "$SD_CLI"

  if (( APPLY )); then
    build_missing_sd
    UNRESOLVED=$((UNRESOLVED - 1))
  else
    info 'Source build' 'Would build pinned stable-diffusion.cpp if no conflicting checkout exists'
  fi
}

printf 'AI3D installer — %s\n' "$([[ "$APPLY" -eq 1 ]] && echo APPLY || echo DRY RUN)"
printf 'Root: %s\n' "$ROOT"

case "$ONLY" in
  all|sd-cpp) check_sd ;;
esac

case "$ONLY" in
  all|hunyuan) check_python Hunyuan "$HUN_ROOT" 'torch numpy trimesh PIL hy3dgen' ;;
esac

case "$ONLY" in
  all|paint3d) check_python Paint3D "$PAINT_ROOT" 'torch numpy PIL paint3d' ;;
esac

printf '\nUnresolved components/checks: %d\n' "$UNRESOLVED"

if (( UNRESOLVED > 0 )); then
  printf 'Review the unresolved items. No existing installations were replaced.\n'
  (( APPLY == 0 )) || exit 1
else
  printf 'All selected components detected; no changes required.\n'
fi

