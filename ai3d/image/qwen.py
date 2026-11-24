"""Pure command builder for guarded Qwen image reference generation.

This module does not load image models or import CUDA dependencies.
Defaults use the AI3D-local dependency path; this may be a real directory or a symlink.
"""

from pathlib import Path

DEFAULT_SD_CLI = Path(__file__).resolve().parents[2] / "stable-diffusion.cpp/build/bin/sd-cli"
DEFAULT_MODEL_DIR = Path.home() / "models/Qwen-Image-2512"


def build_qwen_command(
    sd_cli: Path, model_dir: Path, prompt: str, output: Path,
    *, width: int = 384, height: int = 576, steps: int = 12,
    ram_limit: str = "10G", swap_limit: str = "1G",
) -> list[str]:
    """Return the existing CUDA/systemd-limited sd-cli argument vector."""
    if min(width, height, steps) <= 0:
        raise ValueError("width, height and steps must be positive")
    sd_cli, model_dir = Path(sd_cli), Path(model_dir)
    return [
        "systemd-run", "--user", "--scope", "-p", f"MemoryMax={ram_limit}",
        "-p", f"MemorySwapMax={swap_limit}", str(sd_cli),
        "--diffusion-model", str(model_dir / "qwen-image-2512-Q3_K_M.gguf"),
        "--llm", str(model_dir / "Qwen2.5-VL-7B-Instruct-Q4_K_M.gguf"),
        "--vae", str(model_dir / "qwen_image_vae.safetensors"),
        "--backend", "cuda0", "--params-backend", "disk", "--max-vram", "-1",
        "--diffusion-fa", "--cfg-scale", "2.5", "--sampling-method", "euler",
        "--flow-shift", "3", "--steps", str(steps), "-t", "4",
        "-W", str(width), "-H", str(height),
        "--seed", "42", "-p", prompt, "-o", str(output),
    ]


def split_prompt(text: str) -> tuple[str, str]:
    """Split a prompt file into (prompt, negative prompt).

    Everything after a line starting with "Negative prompt" (markdown bold
    allowed, e.g. "**Negative prompt:**") is the negative prompt. Sending the
    negative list as part of the main prompt would make the model draw what
    it names ("no backpack" -> backpack).
    """
    lines = text.splitlines()
    for i, line in enumerate(lines):
        bare = line.strip().strip("*#_ ").lower()
        if bare.startswith("negative prompt"):
            after = line.split(":", 1)[1].strip().strip("*").strip() if ":" in line else ""
            negative = "\n".join([after, *lines[i + 1:]]).strip()
            return "\n".join(lines[:i]).strip(), negative
    return text.strip(), ""


# --------------------------------------------------------------------------
# Multi-view: side/back views of the SAME character from the front image.

VIEW_PROMPTS = {
    "left": (
        "Show this exact same character from the left side: rotate the camera 90 degrees "
        "around the character so we see a full side profile. Keep the identical face, "
        "hairstyle, outfit, colours, body proportions and the same arm pose."
    ),
    "back": (
        "Rear view of this exact same character, seen from directly behind. Her whole body "
        "is turned away from the camera, not just her head: we see the back of her head, "
        "the back of her neck, her shoulder blades and spine, her buttocks, the backs of her "
        "knees and her heels. Her face, chest and toes are not visible; her feet point away "
        "from the camera. Keep the identical hairstyle, outfit, colours, body proportions "
        "and the same arm pose, arms mirrored as seen from behind."
    ),
    "right": (
        "Show this exact same character from the right side: rotate the camera 90 degrees "
        "the other way around the character so we see the opposite full side profile. Keep "
        "the identical face, hairstyle, outfit, colours, body proportions and the same arm pose."
    ),
}
VIEW_SUFFIX = (
    " Full body from the top of the head to the soles of the feet, centred, orthographic "
    "character turnaround sheet style, no perspective distortion, plain light-gray "
    "background, soft even lighting, nothing else in the image."
)


UPSCALE_PROMPT = (
    "Recreate this exact image at a higher resolution with crisp, sharp detail. Keep the "
    "identical character, pose, framing, proportions, colours, lighting and background. "
    "Sharpen the face, eyes, eyebrows, lips, hair strands, seams and the edges of the "
    "fabric panels. Do not add, remove or move anything."
)


def view_prompt(angle: str) -> str:
    if angle not in VIEW_PROMPTS:
        raise ValueError(f"Unknown view angle {angle!r}; choose from {sorted(VIEW_PROMPTS)}")
    return VIEW_PROMPTS[angle] + VIEW_SUFFIX


def build_qwen_edit_command(
    sd_cli: Path, *, diffusion_model: Path, llm: Path, llm_vision: Path, vae: Path,
    reference: Path, prompt: str, output: Path, size: int = 512, steps: int = 20,
    cfg_scale: float = 2.5, seed: int = 42, ram_limit: str = "10G", swap_limit: str = "1G",
    vae_tiling: bool = True,
) -> list[str]:
    """Qwen-Image-Edit (2509/2511) with the front image as reference (sd-cli -r).

    vae_tiling: encode/decode images in tiles. Without it the VAE needs ~7.8 GB
    in one block at 1024 px, more than a 6 GB card has.
    """
    if min(size, steps) <= 0:
        raise ValueError("size and steps must be positive")
    return [
        "systemd-run", "--user", "--scope", "-p", f"MemoryMax={ram_limit}",
        "-p", f"MemorySwapMax={swap_limit}", str(sd_cli),
        "--diffusion-model", str(diffusion_model),
        "--llm", str(llm), "--llm_vision", str(llm_vision), "--vae", str(vae),
        "-r", str(reference),
        "--backend", "cuda0", "--params-backend", "disk", "--max-vram", "-1",
        "--diffusion-fa", *(["--vae-tiling"] if vae_tiling else []),
        "--cfg-scale", str(cfg_scale), "--sampling-method", "euler",
        "--flow-shift", "3", "--steps", str(steps), "-t", "4",
        "-W", str(size), "-H", str(size), "--seed", str(seed),
        "-p", prompt, "-o", str(output),
    ]
