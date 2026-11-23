"""Pure command builders for Hunyuan shape and prepaint mesh processing."""

from pathlib import Path


def build_shape_command(
    python: Path, script: Path, reference: Path, output: Path, *, steps: int = 20
) -> list[str]:
    """Build the external first_mesh.py shape inference command."""
    if steps < 1:
        raise ValueError("steps must be positive")
    return [
        str(python), str(script), "--input", str(reference),
        "--output", str(output), "--steps", str(steps),
    ]


def build_prepaint_command(
    blender: str, script: Path, input_mesh: Path, output: Path,
    *, target_faces: int = 40000,
) -> list[str]:
    """Build the upstream geometry-only Blender optimizer command."""
    if target_faces < 1:
        raise ValueError("target_faces must be positive")
    return [
        str(blender), "--background", "--factory-startup",
        "--python-exit-code", "1", "--python", str(script),
        "--", "--input", str(input_mesh), "--target-faces",
        str(target_faces), "--output", str(output),
    ]


def build_hunyuan_shape_command(
    python: Path, script: Path, output: Path, *, front: Path,
    left: Path | None = None, back: Path | None = None, right: Path | None = None,
    model: str = "mini", model_path: Path | None = None, steps: int = 30,
    octree_resolution: int = 256, num_chunks: int = 8000,
    guidance_scale: float = 5.0, seed: int = 42, remove_floaters: bool = True,
    low_vram: bool = False,
) -> list[str]:
    """Command for the tracked backends/hunyuan_shape.py (single or multi-view)."""
    if model not in ("mini", "mini-turbo", "mv", "mv-turbo"):
        raise ValueError(f"Unknown Hunyuan model {model!r}")
    views = {"left": left, "back": back, "right": right}
    multiview = model.startswith("mv")
    if multiview and not any(views.values()):
        raise ValueError("Multi-view models need at least one side/back view")
    if not multiview and any(views.values()):
        raise ValueError("Single-view models cannot take side/back views")
    if steps < 1 or octree_resolution < 64 or num_chunks < 1:
        raise ValueError("steps, octree_resolution and num_chunks must be positive")
    cmd = [str(python), str(script), "--front", str(front)]
    for name, path in views.items():
        if path is not None:
            cmd += [f"--{name}", str(path)]
    cmd += ["--output", str(output), "--model", model, "--steps", str(steps),
            "--octree-resolution", str(octree_resolution), "--num-chunks", str(num_chunks),
            "--guidance-scale", str(guidance_scale), "--seed", str(seed)]
    if model_path is not None:
        cmd += ["--model-path", str(model_path)]
    if not remove_floaters:
        cmd.append("--keep-floaters")
    if low_vram:
        cmd.append("--low-vram")
    return cmd
