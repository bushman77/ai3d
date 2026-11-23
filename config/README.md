# Configuration

- `default.json`: every pipeline setting, with notes. Always loaded first.
- `fast_6gb.json`: quickest profile (old Paint3D settings, fewer steps).

Use your own: `cp config/default.json config/mine.json`, edit it, then
`--config config/mine.json`. Keep only the keys you change if you like; it
is merged over the defaults. One-off changes: `--set section.key=value`.
Relative paths are relative to the ai3d folder; `~` works.
