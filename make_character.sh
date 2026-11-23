#!/usr/bin/env bash
# Guided character build: views -> model -> rig -> report -> SunRacer.
# Same as: python3 -m ai3d make ...   (see: bash make_character.sh --help)
PYTHONPATH="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)${PYTHONPATH:+:$PYTHONPATH}" \
  python3 -m ai3d make "$@"
