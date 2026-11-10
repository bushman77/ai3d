"""Pure command builder for guarded Qwen image reference generation.

This module does not load image models or import CUDA dependencies.
The defaults preserve the original tested local configuration.
"""

from pathlib import Path

DEFAULT_SD_CLI = Path.home() / "ai-image/stable-diffusion.cpp/build/bin/sd-cli"
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
