#!/usr/bin/env bash
# Staged modular character build: design -> component references -> shape ->
# paint -> game component GLBs -> reversible preview, with review gates.
# The pre-modular whole-character builder is kept behind --legacy-full-build.
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
THIGH_REVIEW=0
THIGH_OUTPUT=""
THIGH_INSET="0.0"
THIGH_METHOD="guided"
BODY_ONLY=0
MODULAR_STAGE=""
MODULAR_PARTS=()
MODULAR_ALL=0
EXPERIMENTAL_REGION_MESH=0
LEGACY_FULL=0
PAINT_DEBUG=0
OUTFIT_REFERENCES=0
PROTOTYPE_ALL=0
PREFIX_SPECIFIED=0

usage() {
  cat <<'HELP'
Usage: bash build_character.sh [options]

Default behavior is a READ-ONLY modular build plan. Select one component
and one stage, review its result, then explicitly advance to the next stage.
Parts are processed serially (suitable for 6 GB VRAM); --resume is default.

  --stage STAGE         plan|reference|shape|paint|game|preview
  --part ID             Process one card part (repeatable; not for preview)
  --all-parts           Generate ALL part references only (not meshes)
  --prototype-all-parts
                        Run ALL parts from Qwen to Hunyuan to Paint3D to
                        optimized GLBs, then render 3 views each + HTML gallery.
                        Experimental regions INCLUDED; no fitting/assembly.
                        Default prefix: mara_prototype_full_v1
  --outfit-references   Alias: --stage reference --part upper_outfit
                        --part lower_outfit; preserve body/head outputs
  --experimental-region-mesh
                        Permit stand-alone Hunyuan geometry for a region,
                        which still needs fitting (not automatically exported)
  --paint-debug         Save per-view diagnostics during paint/game stages
  --legacy-full-build   Opt in to historical four-stage automatic build
  --card FILE            Character card (default: Mara Venn example)
  --prefix NAME          Component run prefix (default: mara_complete_v1)
  --assembly NAME        Assembly run folder (default: PREFIX_assembly)
  --output-dir DIR       Generated asset root (default: ./outputs)
  --body-shape GLB       Reuse existing body geometry instead of Hunyuan
  --body-image PNG       Matching reference for --body-shape
  --fresh-body           Generate the body from the card, don't auto-reuse Mara
  --body-only            Alias: --stage shape --part body (no automatic assembly)
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
  --thigh-review         Create separate guided patch + reversible remnant review
  --thigh-method METHOD  guided|stations (default: guided mesh-driven side panel)
  --thigh-output FILE    Prototype .blend path (method-specific, beside source)
  --thigh-inset FLOAT    guided: move patch inward +X; stations: shrink radius
  -h, --help             Show this help

If present, outputs/mara_body_shape50/{01_reference.png,03_shape.glb}
are reused automatically for the default Mara card. No original asset is edited.
The master outfit/design is in the card and prompt.txt BEFORE splitting.
It is NOT image-conditioned into each component yet. Region references
(upper_outfit, lower_outfit, hands, hair) are design inputs, not fitted geometry.
Preview stages only body + detailed head and never publish a game character.
--legacy-full-build produces a STATIC GLB and retains historical behavior.
HELP
}

die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }
need_value() { [[ $# -ge 2 && -n "$2" ]] || die "Missing value after $1"; }

while (($#)); do
  case "$1" in
    --card|--prefix|--assembly|--output-dir|--body-shape|--body-image|--quality|--game-faces|--diagnose-blend|--diagnose-object|--diagnose-side|--diagnose-report|--thigh-output|--thigh-inset|--thigh-method|--stage|--part)
      need_value "$@"
      case "$1" in
        --card) CARD="$2";;
        --prefix) PREFIX="$2"; PREFIX_SPECIFIED=1;;
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
        --stage) MODULAR_STAGE="$2";;
        --part) MODULAR_PARTS+=("$2");;
      esac
      shift 2;;
    --fresh-body) BODY_AUTO=0; shift;;
    --body-only) BODY_ONLY=1; BODY_AUTO=0; shift;;
    --all-parts) MODULAR_ALL=1; shift;;
    --outfit-references) OUTFIT_REFERENCES=1; shift;;
    --prototype-all-parts) PROTOTYPE_ALL=1; shift;;
    --experimental-region-mesh) EXPERIMENTAL_REGION_MESH=1; shift;;
    --legacy-full-build) LEGACY_FULL=1; shift;;
    --paint-debug) PAINT_DEBUG=1; shift;;
    --diagnose) DIAGNOSE=1; shift;;
    --thigh-prototype) THIGH_PROTOTYPE=1; shift;;
    --thigh-review) THIGH_PROTOTYPE=1; THIGH_REVIEW=1; shift;;
    --refit) REFIT=1; shift;;
    --force) FORCE=1; REFIT=1; shift;;
    --dry-run) DRY_RUN=1; shift;;
    -h|--help) usage; exit 0;;
    *) die "Unknown option $1 (see --help)";;
  esac
done

if (( PROTOTYPE_ALL && ! PREFIX_SPECIFIED )); then PREFIX="mara_prototype_full_v1"; fi
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
  if (( THIGH_REVIEW )) && [[ "$THIGH_METHOD" != guided ]]; then
    die "--thigh-review requires --thigh-method guided"
  fi
  # Fitting is Mara-only; the Python generator validates range more strictly.
  source_scene="$OUTPUT_DIR/$ASSEMBLY/hole_in_thigh_exposed.blend"
  [[ -s "$source_scene" ]] || die "Missing experimental scene: $source_scene"
  if (( THIGH_REVIEW )); then
    default_thigh_file="thigh_holster_review.blend"
  elif [[ "$THIGH_METHOD" == guided ]]; then
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
  if (( THIGH_REVIEW )); then proto_cmd+=(--review-remnants); fi
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
"$PYTHON" -m ai3d character validate "$CARD"

# An explicit proof-of-pipeline run is intentionally different from the
# review-gated modular workflow. All parts, including region parts, go through
# standalone Qwen -> Hunyuan -> Paint3D -> Blender game GLB and image previews.
if (( PROTOTYPE_ALL )); then
  (( ! LEGACY_FULL && ! BODY_ONLY && ! OUTFIT_REFERENCES && ! DIAGNOSE && ! THIGH_PROTOTYPE )) ||
    die "--prototype-all-parts cannot be combined with legacy, body-only, outfit-references or diagnostics"
  [[ -z "$MODULAR_STAGE" && ${#MODULAR_PARTS[@]} -eq 0 && $MODULAR_ALL -eq 0 ]] ||
    die "--prototype-all-parts cannot be combined with --stage, --part or --all-parts"
  [[ -z "$BODY_SHAPE" && -z "$BODY_IMAGE" ]] ||
    die "--prototype-all-parts does not use single-body reuse flags"
  (( ! EXPERIMENTAL_REGION_MESH )) ||
    die "--experimental-region-mesh is implicit with --prototype-all-parts"
  if (( ! DRY_RUN )); then
    command -v "$BLENDER" >/dev/null || die "Blender not found: $BLENDER"
  fi
  PROTO_ACTION=(--resume)
  if (( FORCE )); then PROTO_ACTION=(--force); fi
  if (( DRY_RUN )); then PROTO_ACTION+=(--dry-run); fi
  PROTO_DEBUG=()
  if (( PAINT_DEBUG )); then PROTO_DEBUG=(--paint-debug); fi
  printf '\n[COMPLETE 3D PROTOTYPE] %s -> all card parts, no inspection pauses\n' "$PREFIX"
  printf 'Qwen -> Hunyuan -> Paint3D -> game GLBs -> 3 rendered views per part -> gallery\n'
  printf 'Includes experimental hair, upper/lower clothing and hands; no assembly or fitting.\n'
  "$PYTHON" -m ai3d character generate "$CARD" \
    --all --include-regions --stop-after game \
    --run-prefix "$PREFIX" --quality "$QUALITY" \
    --output-dir "$OUTPUT_DIR" --blender "$BLENDER" \
    "${PROTO_ACTION[@]}" "${PROTO_DEBUG[@]}"
  GALLERY_ACTION=()
  if (( DRY_RUN )); then GALLERY_ACTION=(--dry-run); fi
  "$PYTHON" -m ai3d.characters.prototype_gallery \
    --card "$CARD" --prefix "$PREFIX" \
    --output-dir "$OUTPUT_DIR" --blender "$BLENDER" \
    "${GALLERY_ACTION[@]}"
  exit 0
fi

# The modular workflow is the safe default. It intentionally cannot infer
# that a reference/mesh/component is approved from the presence of its files.
if (( ! LEGACY_FULL )); then
  if (( BODY_ONLY )); then
    [[ -z "$MODULAR_STAGE" ]] || die "--body-only cannot be combined with --stage"
    MODULAR_STAGE="shape"
    MODULAR_PARTS+=("body")
  fi
  if (( OUTFIT_REFERENCES )); then
    [[ -z "$MODULAR_STAGE" && ${#MODULAR_PARTS[@]} -eq 0 && $MODULAR_ALL -eq 0 ]] ||
      die "--outfit-references cannot be combined with --stage, --part or --all-parts"
    MODULAR_STAGE="reference"
    MODULAR_PARTS=(upper_outfit lower_outfit)
  fi
  MODULAR_STAGE="${MODULAR_STAGE:-plan}"
  case "$MODULAR_STAGE" in
    plan|reference|shape|paint|game|preview) ;;
    *) die "Unknown modular stage: $MODULAR_STAGE";;
  esac
  (( ! FORCE || DRY_RUN == 0 )) || die "Do not combine --force and --dry-run"
  [[ -z "$BODY_SHAPE" && -z "$BODY_IMAGE" ]] || die "--body-shape/--body-image require --legacy-full-build"
  (( ! MODULAR_ALL || ${#MODULAR_PARTS[@]} == 0 )) || die "Use either --all-parts or --part"
  if (( MODULAR_ALL )) && [[ "$MODULAR_STAGE" != reference ]]; then
    die "--all-parts is allowed only for reference generation"
  fi
  if [[ "$MODULAR_STAGE" == "plan" || "$MODULAR_STAGE" == "preview" ]]; then
    (( ${#MODULAR_PARTS[@]} == 0 && ! MODULAR_ALL )) || die "This stage does not accept --part or --all-parts"
  else
    (( ${#MODULAR_PARTS[@]} > 0 || MODULAR_ALL )) || die "Specify --part ID (or --all-parts for references)"
  fi
  # Fail closed on unsupported part IDs and prevent region meshes from being
  # mistaken for fitted wearable items. This check is stdlib-only.
  "$PYTHON" - "$CARD" "$MODULAR_STAGE" "$EXPERIMENTAL_REGION_MESH" "${MODULAR_PARTS[@]}" <<'PY'
import json
import sys
card_path, stage, experimental, *selected = sys.argv[1:]
card = json.load(open(card_path, encoding="utf-8"))
parts = {part["id"]: part for part in card["parts"]}
for part_id in selected:
    if part_id not in parts:
        raise SystemExit(f"ERROR: unknown part {part_id!r}; available: {', '.join(parts)}")
    if stage not in ("plan", "reference") and parts[part_id]["kind"] == "region" and experimental != "1":
        raise SystemExit(
            f"ERROR: {part_id} is a region, not a fitted mesh. "
            "Generate its reference first or explicitly use --experimental-region-mesh."
        )
PY
  if [[ "$MODULAR_STAGE" == plan ]]; then
    "$PYTHON" - "$CARD" "$PREFIX" "$OUTPUT_DIR" <<'PY'
import json
from pathlib import Path
import sys
card_path, prefix, output_dir = sys.argv[1:]
card = json.load(open(card_path, encoding="utf-8"))
root = Path(output_dir)
print(f"\n[MODULAR PLAN] {card['name']} | prefix={prefix}")
print("Master design: card appearance + prompts.master; prompt.txt remains the source brief.")
print("Design first: the complete outfit is specified before individual references.")
print("Note: component images are currently generated independently, not conditioned on a master PNG.")
for part in card["parts"]:
    view = part.get("reference_view") or "front"
    folder = root / f"{prefix}_{part['id']}_{view}"
    outputs = ("01_reference.png", "03_shape.glb", "05_painted.glb", "06_game.glb")
    found = [p.split("_", 1)[1].split(".", 1)[0] for p in outputs if (folder / p).is_file()]
    print(f"  {part['id']:<15} {part['kind']:<11} {' / '.join(found) if found else 'not generated'}")
print("\nReview progression: reference -> shape -> paint -> game (per part).")
print("Regions (upper_outfit, lower_outfit, gloves/hands, hair) are design-only until fitted geometry exists.")
print("Preview: painted body + separately generated head only, reversible and unapproved.")
print("Garment reference command: ./build_character.sh --outfit-references --prefix", prefix)
PY
    exit 0
  fi
  COMMON=(--output-dir "$OUTPUT_DIR" --blender "$BLENDER")
  ACTION=(--resume)
  if (( FORCE )); then ACTION=(--force); fi
  if (( DRY_RUN )); then ACTION+=(--dry-run); fi
  if [[ "$MODULAR_STAGE" == preview ]]; then
    if (( ! DRY_RUN )); then
      command -v "$BLENDER" >/dev/null || die "Blender not found: $BLENDER"
    fi
    (( ! EXPERIMENTAL_REGION_MESH )) || die "--experimental-region-mesh has no effect on preview"
    [[ -z "$BODY_SHAPE" && -z "$BODY_IMAGE" ]] || die "Preview uses generated card components"
    MANIFEST="$OUTPUT_DIR/$ASSEMBLY/assembly.json"
    MEASUREMENTS="$OUTPUT_DIR/$ASSEMBLY/measurements.json"
    if (( DRY_RUN )); then
      printf '[DRY RUN] Would assemble a body+head preview from painted GLBs, auto-fit approximate positions and rebuild.\n'
      printf '           Preview: %s/preview.blend\n' "$OUTPUT_DIR/$ASSEMBLY"
      exit 0
    fi
    # Never launch a partial preview when the chosen prefix is not painted.
    "$PYTHON" - "$CARD" "$PREFIX" "$OUTPUT_DIR" <<'PY'
import json
from pathlib import Path
import sys
card_path, prefix, output_dir = sys.argv[1:]
card = json.load(open(card_path, encoding="utf-8"))
parts = {p["id"]: p for p in card["parts"]}
for part_id in ("body", "head"):
    if part_id not in parts:
        raise SystemExit(f"ERROR: preview requires {part_id} in card")
    view = parts[part_id].get("reference_view") or "front"
    source = Path(output_dir) / f"{prefix}_{part_id}_{view}" / "05_painted.glb"
    if not source.is_file() or source.stat().st_size == 0:
        raise SystemExit(f"ERROR: preview requires approved painted {part_id}: {source}")
PY
    if [[ -f "$MANIFEST" ]]; then
      "$PYTHON" -m ai3d character assemble "$CARD" \
        --run-prefix "$PREFIX" --name "$ASSEMBLY" "${COMMON[@]}" --rebuild
    else
      "$PYTHON" -m ai3d character assemble "$CARD" \
        --run-prefix "$PREFIX" --name "$ASSEMBLY" --layout overlay \
        --source-stage painted "${COMMON[@]}"
    fi
    FIT_ARGS=()
    if (( REFIT )); then FIT_ARGS+=(--refit); fi
    "$PYTHON" -m ai3d.characters.autofit \
      --manifest "$MANIFEST" --measurements "$MEASUREMENTS" "${FIT_ARGS[@]}"
    "$PYTHON" -m ai3d character assemble "$CARD" \
      --run-prefix "$PREFIX" --name "$ASSEMBLY" "${COMMON[@]}" --rebuild
    printf '\n[PREVIEW] %s/preview.blend\n' "$OUTPUT_DIR/$ASSEMBLY"
    printf 'Review neck seam and transforms; this is not an approved final game asset.\n'
    exit 0
  fi
  SELECTOR=()
  if (( MODULAR_ALL )); then
    SELECTOR=(--all)
  else
    for part in "${MODULAR_PARTS[@]}"; do
      SELECTOR+=(--part "$part")
    done
  fi
  EXPERIMENTAL=()
  if (( EXPERIMENTAL_REGION_MESH )); then EXPERIMENTAL=(--include-regions); fi
  DEBUG=()
  if (( PAINT_DEBUG )) && [[ "$MODULAR_STAGE" == paint || "$MODULAR_STAGE" == game ]]; then
    DEBUG=(--paint-debug)
  fi
  if (( ! DRY_RUN )) && [[ "$MODULAR_STAGE" == paint || "$MODULAR_STAGE" == game ]]; then
    command -v "$BLENDER" >/dev/null || die "Blender not found: $BLENDER"
  fi
  printf '\n[MODULAR %s] %s | prefix=%s\n' "$MODULAR_STAGE" "${MODULAR_PARTS[*]:-all references}" "$PREFIX"
  "$PYTHON" -m ai3d character generate "$CARD" \
    "${SELECTOR[@]}" --stop-after "$MODULAR_STAGE" \
    --run-prefix "$PREFIX" --quality "$QUALITY" \
    "${COMMON[@]}" "${ACTION[@]}" "${EXPERIMENTAL[@]}" "${DEBUG[@]}"
  printf '\n[CHECKPOINT] Review component output before advancing to the next stage.\n'
  if [[ "$MODULAR_STAGE" == reference ]]; then
    printf 'Inspect separate garment design references before any experimental reconstruction.\n'
    printf 'Do not reconstruct reference images containing unintended accessories.\n'
  elif [[ "$MODULAR_STAGE" == shape ]]; then
    printf 'Inspect 03_shape.glb in Blender solid mode for anatomy and surface defects.\n'
  elif [[ "$MODULAR_STAGE" == paint ]]; then
    printf 'Inspect 05_painted.glb front/side/back and debug images for paint coverage.\n'
  fi
  exit 0
fi

# Historical full-build operation remains opt-in and is not modular.
[[ -z "$MODULAR_STAGE" && ${#MODULAR_PARTS[@]} -eq 0 && $MODULAR_ALL -eq 0 ]] || die "--legacy-full-build cannot combine with modular stages or parts"
(( ! EXPERIMENTAL_REGION_MESH && ! OUTFIT_REFERENCES )) || die "--experimental-region-mesh and --outfit-references are modular-only"
if (( ! DRY_RUN )); then
  command -v "$BLENDER" >/dev/null || die "Blender not found: $BLENDER"
fi

# Reuse the successful body shape and the exact image used for reconstruction.
# A reference from a different run can paint the wrong surface details.
if (( BODY_AUTO )) && [[ -z "$BODY_SHAPE" && "$CARD" == examples/space_nova/characters/mara_venn.json ]]; then
  candidate="$OUTPUT_DIR/mara_body_shape50"
  if [[ -s "$candidate/03_shape.glb" && -s "$candidate/01_reference.png" ]]; then
    BODY_SHAPE="$candidate/03_shape.glb"
    BODY_IMAGE="$candidate/01_reference.png"
  fi
fi
if (( BODY_ONLY )) && [[ -n "$BODY_SHAPE" || -n "$BODY_IMAGE" ]]; then
  die "--body-only must produce new geometry; use existing ai3d generate --image if reusing an image"
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

if (( BODY_ONLY )); then
  printf '\n[BODY SHAPE] Qwen clean body reference -> Hunyuan shape; pause before painting\n'
  "$PYTHON" -m ai3d character generate "$CARD" \
    --part body --stop-after shape \
    --run-prefix "$PREFIX" "${COMMON[@]}" "${ACTION[@]}"
  if (( DRY_RUN )); then
    printf '\nBODY SHAPE DRY RUN: no output was generated.\n'
  else
    printf '\nBODY SHAPE STAGE FINISHED: %s\n' "$OUTPUT_DIR/${PREFIX}_body_front/"
  fi
  printf 'Inspect 01_reference.png and 03_shape.glb before any painting or assembly.\n'
  exit 0
fi

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
