#!/usr/bin/env bash
# Reset AI3D's generated Mara runs. Preview by default; --delete requires an
# exact interactive confirmation. Run with bash; do not source into your shell.

if [[ "${BASH_SOURCE[0]}" != "$0" ]]; then
  printf 'ERROR: run this script with bash; do not source it.\n' >&2
  return 1
fi

set -u

MODE="${1:---preview}"
case "$MODE" in
  --preview|--delete) ;;
  *) printf 'Usage: bash %s [--preview|--delete]\n' "$0" >&2; exit 2 ;;
esac
if (( $# > 1 )); then
  printf 'ERROR: too many arguments.\n' >&2
  exit 2
fi

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)" || exit 1
if [[ ! -f "$ROOT/build_character.sh" || ! -f "$ROOT/ai3d/output.py" ]]; then
  printf 'ERROR: this script must live in the AI3D repository root (next to build_character.sh).\n' >&2
  exit 1
fi

# The AI3D build uses outputs/ by default; the other two are legacy/diagnostic
# generated-run locations. Do not touch original references, weights or code.
DIRS=(outputs pipeline_runs diagnostics)
TARGETS=()
for sub in "${DIRS[@]}"; do
  folder="$ROOT/$sub"
  [[ -e "$folder" || -L "$folder" ]] || continue
  if [[ -L "$folder" || ! -d "$folder" ]]; then
    printf 'ERROR: expected a real directory: %s\n' "$folder" >&2
    exit 1
  fi
  while IFS= read -r -d '' item; do
    # Never follow links or allow a target outside the identified folder.
    if [[ -L "$item" ]]; then
      printf 'SKIPPING symbolic link: %s\n' "$item" >&2
      continue
    fi
    [[ -d "$item" || -f "$item" ]] || continue
    TARGETS+=("$item")
  done < <(find "$folder" -mindepth 1 -maxdepth 1 \
      \( -name 'mara_*' -o -name 'mara-*' \) -print0)
done

printf '\nAI3D generated Mara cleanup — %s\n' "$MODE"
printf 'Repository: %s\n' "$ROOT"
printf 'Matched %d top-level generated items:\n' "${#TARGETS[@]}"
if (( ${#TARGETS[@]} == 0 )); then
  printf 'Nothing to remove.\n'
  exit 0
fi

for target in "${TARGETS[@]}"; do
  du -sh -- "$target" 2>/dev/null || printf '  %s\n' "$target"
done

printf '\nNOT included: assets/, images/, models/, source code, model weights,\n'
printf 'Space Nova, and anything without a Mara-prefixed name.\n'
printf 'This DOES include Mara Blender backups inside matching outputs/ folders.\n'

if [[ "$MODE" != '--delete' ]]; then
  printf '\nPreview only. No files were deleted.\n'
  printf 'To delete these exact categories, run: bash %q --delete\n' "$0"
  exit 0
fi

if [[ ! -t 0 ]]; then
  printf 'ERROR: interactive terminal required for deletion.\n' >&2
  exit 1
fi
printf '\nPERMANENT DELETION. Type DELETE MARA GENERATED ASSETS to continue: '
IFS= read -r confirmation || exit 1
if [[ "$confirmation" != 'DELETE MARA GENERATED ASSETS' ]]; then
  printf 'Cancelled. Nothing deleted.\n'
  exit 0
fi

failures=0
for target in "${TARGETS[@]}"; do
  # Revalidate the direct parent and target before every removal.
  parent="$(cd -- "$(dirname -- "$target")" && pwd -P)" || { failures=$((failures+1)); continue; }
  case "$parent" in
    "$ROOT/outputs"|"$ROOT/pipeline_runs"|"$ROOT/diagnostics") ;;
    *) printf 'REFUSED unexpected parent: %s\n' "$target" >&2; failures=$((failures+1)); continue ;;
  esac
  if [[ -L "$target" ]]; then
    printf 'REFUSED symbolic link: %s\n' "$target" >&2
    failures=$((failures+1))
  elif [[ -e "$target" ]]; then
    if rm -rf -- "$target"; then
      printf 'DELETED: %s\n' "$target"
    else
      printf 'FAILED: %s\n' "$target" >&2
      failures=$((failures+1))
    fi
  fi
done

if (( failures > 0 )); then
  printf 'Cleanup completed with %d errors.\n' "$failures" >&2
  exit 1
fi
printf 'Mara generated-run cleanup complete. Source code and model weights untouched.\n'
