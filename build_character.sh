#!/usr/bin/env bash
# One-command, resumable character build: card -> references -> meshes ->
# textures -> editable assembly -> heuristically fitted static game GLB.
# Run from any directory: bash ~/ai3d/build_character.sh [options]
set -Eeuo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

PYTHON="${PYTHON:-python3}"
BLENDER="${BLENDER:-blender}"
CARD="examples/space_nova/characters/mara_venn.json"
PREFIX="mara_complete_v1"
ASSEMBLY=""
OUTPUT_DIR="$ROOT/outputs"
BODY_SHAPE=""
BODY_IMAGE=""
BODY_AUTO=1
QUALITY="fast"
GAME_FACES=60000
DRY_RUN=0
FORCE=0
REFIT=0
DIAGNOSE=0
DIAGNOSE_BLEND=""
DIAGNOSE_REPORT=""
DIAGNOSE_OBJECT="Mesh"
DIAGNOSE_SIDE="negative-x"
THIGH_PROTOTYPE=0
THIGH_OUTPUT=""
THIGH_INSET="0.0"
THIGH_METHOD="guided"

usage() {
  cat <<'HELP'
Usage: bash build_character.sh [options]

Build a character from its card all the way through a fitted static GLB.
The stages run sequentially (important for 6 GB VRAM) and resume by default.

  --card FILE            Character card (default: Mara Venn example)
  --prefix NAME          Component run prefix (default: mara_complete_v1)
  --assembly NAME        Assembly run folder (default: PREFIX_assembly)
  --output-dir DIR       Generated asset root (default: ./outputs)
  --body-shape GLB       Reuse existing body geometry instead of Hunyuan
  --body-image PNG       Matching reference for --body-shape
  --fresh-body           Generate the body from the card, don't auto-reuse Mara
  --quality PRESET       Paint3D quality: fast|low|medium|high|highest
  --game-faces NUMBER    Target for combined static GLB (default: 60000)
  --refit                Recalculate heuristic assembly transforms
  --force                Regenerate stages or overwrite an existing thigh prototype
  --dry-run              Print planned inference commands; write nothing
  --diagnose             Analyze saved thigh-hole scene; no rebuild/inference
  --diagnose-blend FILE  Source .blend (default: saved hole_in_thigh_exposed.blend)
  --diagnose-object NAME Mesh object to inspect (default: Mesh)
  --diagnose-side SIDE   negative-x|positive-x|both (default: negative-x)
  --diagnose-report FILE Destination .json (default: beside .blend)
  --thigh-prototype      Create a separate, diagnostic thigh preview .blend
  --thigh-method METHOD  guided|stations (default: guided mesh-driven side panel)
  --thigh-output FILE    Prototype .blend path (method-specific, beside source)
  --thigh-inset FLOAT    guided: move patch inward +X; stations: shrink radius
  -h, --help             Show this help

If present, outputs/mara_body_shape50/{01_reference.png,03_shape.glb}
are reused automatically for the default Mara card. No original asset is edited.
The final GLB is a best-effort STATIC mesh, not an animated/rigged character.
Unverified region meshes remain staged in the editable .blend to avoid
silently covering/duplicating the body's clothing, hair, or gloves.
HELP
}

die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }
need_value() { [[ $# -ge 2 && -n "$2" ]] || die "Missing value after $1"; }

while (($#)); do
  case "$1" in
    --card|--prefix|--assembly|--output-dir|--body-shape|--body-image|--quality|--game-faces|--diagnose-blend|--diagnose-object|--diagnose-side|--diagnose-report|--thigh-output|--thigh-inset|--thigh-method)
      need_value "$@"
      case "$1" in
        --card) CARD="$2";;
        --prefix) PREFIX="$2";;
        --assembly) ASSEMBLY="$2";;
        --output-dir) OUTPUT_DIR="$2";;
        --body-shape) BODY_SHAPE="$2";;
        --body-image) BODY_IMAGE="$2";;
        --quality) QUALITY="$2";;
        --game-faces) GAME_FACES="$2";;
        --diagnose-blend) DIAGNOSE_BLEND="$2"; DIAGNOSE=1;;
        --diagnose-object) DIAGNOSE_OBJECT="$2"; DIAGNOSE=1;;
        --diagnose-side) DIAGNOSE_SIDE="$2"; DIAGNOSE=1;;
        --diagnose-report) DIAGNOSE_REPORT="$2"; DIAGNOSE=1;;
        --thigh-output) THIGH_OUTPUT="$2"; THIGH_PROTOTYPE=1;;
        --thigh-inset) THIGH_INSET="$2"; THIGH_PROTOTYPE=1;;
        --thigh-method) THIGH_METHOD="$2"; THIGH_PROTOTYPE=1;;
      esac
      shift 2;;
    --fresh-body) BODY_AUTO=0; shift;;
    --diagnose) DIAGNOSE=1; shift;;
    --thigh-prototype) THIGH_PROTOTYPE=1; shift;;
    --refit) REFIT=1; shift;;
    --force) FORCE=1; REFIT=1; shift;;
    --dry-run) DRY_RUN=1; shift;;
    -h|--help) usage; exit 0;;
    *) die "Unknown option $1 (see --help)";;
  esac
done

[[ "$PREFIX" =~ ^[a-zA-Z0-9][a-zA-Z0-9_-]*$ ]] || die "Invalid --prefix"
ASSEMBLY="${ASSEMBLY:-${PREFIX}_assembly}"
[[ "$ASSEMBLY" =~ ^[a-zA-Z0-9][a-zA-Z0-9_-]*$ ]] || die "Invalid --assembly"
[[ "$GAME_FACES" =~ ^[0-9]+$ ]] && ((10#$GAME_FACES >= 100)) || die "--game-faces must be at least 100"
case "$QUALITY" in fast|low|medium|high|highest) ;; *) die "Invalid --quality";; esac
# Diagnostic mode is deliberately separate from the expensive build.
# Never validate/generate/fit/export while only inspecting a saved .blend file.
if (( DIAGNOSE )); then
  case "$DIAGNOSE_SIDE" in negative-x|positive-x|both) ;; *) die "Invalid --diagnose-side";; esac
  [[ -n "$DIAGNOSE_OBJECT" ]] || die "Empty --diagnose-object"
  DIAGNOSE_BLEND="${DIAGNOSE_BLEND:-$OUTPUT_DIR/$ASSEMBLY/hole_in_thigh_exposed.blend}"
  [[ -s "$DIAGNOSE_BLEND" ]] || die "Diagnostic scene missing or empty: $DIAGNOSE_BLEND"
  [[ "$DIAGNOSE_BLEND" == *.blend ]] || die "Diagnostic scene must be .blend"
  if [[ -z "$DIAGNOSE_REPORT" ]]; then
    scene_name="$(basename -- "$DIAGNOSE_BLEND")"
    DIAGNOSE_REPORT="$(dirname -- "$DIAGNOSE_BLEND")/topology_${scene_name%.blend}.json"
  fi
  [[ "$DIAGNOSE_REPORT" == *.json ]] || die "Report must be .json"
  command -v "$BLENDER" >/dev/null || die "Blender not found: $BLENDER"
  [[ -f "$ROOT/ai3d/diagnostics/blender_topology.py" ]] || die "Missing diagnostic adapter"
  diag_cmd=("$BLENDER" --background "$DIAGNOSE_BLEND" --python-exit-code 1
    --python "$ROOT/ai3d/diagnostics/blender_topology.py" --
    --object "$DIAGNOSE_OBJECT" --side "$DIAGNOSE_SIDE" --report "$DIAGNOSE_REPORT")
  if (( DRY_RUN )); then
    printf 'Would run read-only diagnostic:'
    printf ' %q' "${diag_cmd[@]}"
    printf '\n'
  else
    printf '\n[DIAGNOSE] No generation, mesh edits, or Blender scene saves\n'
    "${diag_cmd[@]}"
  fi
  exit 0
fi

if (( THIGH_PROTOTYPE )); then
  (( ! DIAGNOSE )) || die "Choose either --diagnose or --thigh-prototype"
  [[ "$THIGH_INSET" =~ ^([0-9]+([.][0-9]+)?|[.][0-9]+)$ ]] || die "Invalid --thigh-inset"
  case "$THIGH_METHOD" in guided|stations) ;; *) die "Invalid --thigh-method";; esac
  # Fitting is Mara-only; the Python generator validates range more strictly.
  source_scene="$OUTPUT_DIR/$ASSEMBLY/hole_in_thigh_exposed.blend"
  [[ -s "$source_scene" ]] || die "Missing experimental scene: $source_scene"
  if [[ "$THIGH_METHOD" == guided ]]; then
    default_thigh_file="thigh_guided_prototype.blend"
  else
    default_thigh_file="thigh_underlay_prototype.blend"
  fi
  THIGH_OUTPUT="${THIGH_OUTPUT:-$OUTPUT_DIR/$ASSEMBLY/$default_thigh_file}"
  [[ "$THIGH_OUTPUT" == *.blend ]] || die "Prototype output must be .blend"
  command -v "$BLENDER" >/dev/null || die "Blender not found: $BLENDER"
  proto_cmd=("$BLENDER" --background "$source_scene" --python-exit-code 1
     --python "$ROOT/ai3d/diagnostics/blender_thigh_prototype.py" --
     --output "$THIGH_OUTPUT" --inset "$THIGH_INSET" --method "$THIGH_METHOD")
  if (( FORCE )); then proto_cmd+=(--overwrite); fi
  if (( DRY_RUN )); then
     printf 'Would create separate prototype:'
     printf ' %q' "${proto_cmd[@]}"
     printf '\n'
  else
     printf '\n[THIGH PROTOTYPE] Keep source untouched; new test .blend only\n'
     "${proto_cmd[@]}"
  fi
  exit 0
fi

command -v "$PYTHON" >/dev/null || die "Python not found: $PYTHON"
[[ -f "$CARD" ]] || die "Missing card: $CARD"
if (( ! DRY_RUN )); then
  command -v "$BLENDER" >/dev/null || die "Blender not found: $BLENDER"
fi

"$PYTHON" -m ai3d character validate "$CARD"

# Reuse the successful body shape and the exact image used for reconstruction.
# A reference from a different run can paint the wrong surface details.
if (( BODY_AUTO )) && [[ -z "$BODY_SHAPE" && "$CARD" == examples/space_nova/characters/mara_venn.json ]]; then
  candidate="$OUTPUT_DIR/mara_body_shape50"
  if [[ -s "$candidate/03_shape.glb" && -s "$candidate/01_reference.png" ]]; then
    BODY_SHAPE="$candidate/03_shape.glb"
    BODY_IMAGE="$candidate/01_reference.png"
  fi
fi
if [[ -n "$BODY_SHAPE" ]]; then
  [[ -s "$BODY_SHAPE" ]] || die "Body shape missing/empty: $BODY_SHAPE"
  if [[ -z "$BODY_IMAGE" ]]; then
    parent="$(dirname -- "$BODY_SHAPE")"
    for ext in png jpg jpeg; do
      if [[ -s "$parent/01_reference.$ext" ]]; then
        BODY_IMAGE="$parent/01_reference.$ext"
        break
      fi
    done
  fi
  [[ -n "$BODY_IMAGE" && -s "$BODY_IMAGE" ]] || die "Supply the matching --body-image for $BODY_SHAPE"
elif [[ -n "$BODY_IMAGE" ]]; then
  die "--body-image requires --body-shape (or use the generic ai3d generate command)"
fi

COMMON=(--output-dir "$OUTPUT_DIR" --blender "$BLENDER")
ACTION=(--resume)
if (( FORCE )); then ACTION=(--force); fi
if (( DRY_RUN )); then ACTION+=(--dry-run); fi

printf '\n[1/4] Generate / texture / optimize primary body\n'
if [[ -n "$BODY_SHAPE" ]]; then
  printf 'Reusing body: %s\n' "$BODY_SHAPE"
  "$PYTHON" -m ai3d generate \
    --name "${PREFIX}_body_front" --image "$BODY_IMAGE" \
    --shape-mesh "$BODY_SHAPE" --stop-after game \
    --category humanoid --quality "$QUALITY" \
    --paint-faces 40000 --game-faces 30000 \
    "${COMMON[@]}" "${ACTION[@]}"
else
  "$PYTHON" -m ai3d character generate "$CARD" \
    --part body --stop-after game --quality "$QUALITY" \
    --run-prefix "$PREFIX" "${COMMON[@]}" "${ACTION[@]}"
fi

printf '\n[2/4] Generate / texture / optimize every other card part\n'
"$PYTHON" -m ai3d character generate "$CARD" \
  --all --skip body --include-regions --stop-after game \
  --run-prefix "$PREFIX" --quality "$QUALITY" \
  "${COMMON[@]}" "${ACTION[@]}"

MANIFEST="$OUTPUT_DIR/$ASSEMBLY/assembly.json"
MEASUREMENTS="$OUTPUT_DIR/$ASSEMBLY/measurements.json"
FINAL="$OUTPUT_DIR/$ASSEMBLY/character.glb"
if (( DRY_RUN )); then
  printf '\n[3/4] Would create/rebuild assembly: %s\n' "$MANIFEST"
  printf '[4/4] Would auto-fit then optimize static GLB: %s\n' "$FINAL"
  exit 0
fi

printf '\n[3/4] Import all components into Blender assembly\n'
if [[ -f "$MANIFEST" ]]; then
  "$PYTHON" -m ai3d character assemble "$CARD" \
    --run-prefix "$PREFIX" --name "$ASSEMBLY" \
    "${COMMON[@]}" --rebuild
else
  "$PYTHON" -m ai3d character assemble "$CARD" \
    --run-prefix "$PREFIX" --name "$ASSEMBLY" --all-parts \
    --layout overlay --source-stage painted \
    "${COMMON[@]}"
fi

FIT_ARGS=()
if (( REFIT )); then FIT_ARGS=(--refit); fi
"$PYTHON" -m ai3d.characters.autofit \
  --manifest "$MANIFEST" --measurements "$MEASUREMENTS" "${FIT_ARGS[@]}"
"$PYTHON" -m ai3d character assemble "$CARD" \
  --run-prefix "$PREFIX" --name "$ASSEMBLY" \
  "${COMMON[@]}" --rebuild

printf '\n[4/4] Optimize assembled static character and verify textures\n'
"$BLENDER" --background --factory-startup --python-exit-code 1 \
  --python "$ROOT/ai3d/optimization/blender_finalize.py" -- \
  --input "$OUTPUT_DIR/$ASSEMBLY/preview.glb" \
  --output "$FINAL" --target-faces "$GAME_FACES"
"$PYTHON" -m ai3d inspect "$FINAL" --require-texture
printf '\nDONE: %s\n' "$FINAL"
printf 'EDITABLE ASSEMBLY: %s\n' "$OUTPUT_DIR/$ASSEMBLY/preview.blend"
printf 'FIT SETTINGS: %s\n' "$MANIFEST"
printf 'NOTE: static mesh only. Automated fitting is approximate; inspect head/neck and accessories in Blender.\n'
