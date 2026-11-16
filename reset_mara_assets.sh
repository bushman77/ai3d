#!/usr/bin/env bash
set -euo pipefail

cd "$HOME/ai3d"

OUTPUTS="$PWD/outputs"
PREFIX="mara_complete_v1"
BODY="$OUTPUTS/${PREFIX}_body_front"
REF="$BODY/01_reference.png"
ARCHIVE="$PWD/approved_references"
BACKUP="$ARCHIVE/mara_body_front_approved.png"

[[ -d "$OUTPUTS" && ! -L "$OUTPUTS" ]] || {
    echo "Invalid outputs directory"
    exit 1
}
[[ -d "$BODY" && ! -L "$BODY" && -s "$REF" && ! -L "$REF" ]] || {
    echo "Approved reference missing or unsafe"
    exit 1
}

mkdir -p "$ARCHIVE"

# Preserve original image independently of output cleanup.
if [[ -e "$BACKUP" ]]; then
    cmp -s "$REF" "$BACKUP" || {
        echo "Archived reference differs. Refusing to overwrite."
        exit 1
    }
else
    cp -p "$REF" "$BACKUP"
fi

echo "Approved reference protected:"
sha256sum "$BACKUP"

shopt -s nullglob dotglob

echo
echo "Assets selected for removal:"

for dir in "$OUTPUTS"/"${PREFIX}"_*; do
    [[ -d "$dir" && ! -L "$dir" ]] || continue

    if [[ "$dir" == "$BODY" ]]; then
        for file in "$dir"/*; do
            case "${file##*/}" in
                01_reference.png|reference_prompt.txt|reference_manifest.json)
                    continue ;;
            esac
            echo "REMOVE: $file"
        done
    else
        echo "REMOVE DIRECTORY: $dir"
    fi
done

if [[ "${1:-}" != "--apply" ]]; then
    echo
    echo "Preview only. Run with --apply to delete."
    exit 0
fi

for dir in "$OUTPUTS"/"${PREFIX}"_*; do
    [[ -d "$dir" && ! -L "$dir" ]] || continue

    if [[ "$dir" == "$BODY" ]]; then
        for file in "$dir"/*; do
            case "${file##*/}" in
                01_reference.png|reference_prompt.txt|reference_manifest.json)
                    continue ;;
            esac
            rm -rf -- "$file"
        done
    else
        rm -rf -- "$dir"
    fi
done

cmp -s "$REF" "$BACKUP" || {
    echo "ERROR: Reference integrity check failed!"
    exit 1
}

echo
echo "Cleanup complete."
echo "Approved T-pose preserved."
echo "All selected generated assets removed."
