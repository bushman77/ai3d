# Space Nova AI3D — Dependency Inventory

This is an inventory of the *currently working local generator*, not a reproducible lockfile yet. The launcher currently expects fixed paths in `~/ai-image` and `~/ai3d`. Record tested versions/commits before attempting a clean-machine installation.

## 1. System / build prerequisites

| Component | Purpose | Required? |
|---|---|---|
| Linux (tested on Pop!_OS 24.04) | Host environment and shell scripts | Yes for current launcher |
| NVIDIA GPU and working driver | Qwen CUDA inference and Hunyuan/Paint3D GPU inference | Yes for current launcher |
| CUDA toolkit (`nvcc`, headers and libraries) | Compiling CUDA `stable-diffusion.cpp` and GPU extensions such as `nvdiffrast` | Build-time; verify compatibility with driver/PyTorch |
| `git`, `git-lfs` | Source checkout; optional model download via Git LFS | Git required; LFS optional |
| `build-essential` (GCC/G++/make), `cmake`, `ninja-build` | Native C++ and Python/CUDA extensions | Required for source builds |
| Python, `venv`, `pip` | Separate ML tool environments | Yes |
| `blender` with glTF 2.0 import/export | Mesh decimation, GLB export, rig authoring | Yes |
| `systemd-run` (`systemd` user service) | Launcher Qwen memory limits | Yes for existing launcher |
| Core utilities (`sha256sum`, `cut`, `find`, `tee`, `date`) | Pipeline caching, logs, backups | Yes; commonly already installed |
| `libgl1`, `libglib2.0-0` | Common OpenCV/Python graphics runtime dependencies | Frequently required on fresh systems |
| `gh` | Creating/publishing GitHub repo | Development only |

Suggested Ubuntu/Pop!_OS prerequisite packages (do not reinstall already functioning drivers):

```bash
sudo apt update
sudo apt install -y \
  git git-lfs build-essential cmake ninja-build \
  python3 python3-venv python3-pip \
  blender libgl1 libglib2.0-0
```

`gh` and a **compatible CUDA toolkit** may require separate installation depending on apt sources. `nvidia-smi` reports driver CUDA compatibility, not necessarily the presence of the CUDA compiler; check `nvcc --version` separately.

## 2. Source repositories and tools

| Component | Upstream | Local launcher expectation | Purpose |
|---|---|---|---|
| `stable-diffusion.cpp` | https://github.com/leejet/stable-diffusion.cpp | `~/ai-image/stable-diffusion.cpp/build/bin/sd-cli` | Qwen image reference generation; build with `-DSD_CUDA=ON` |
| Hunyuan3D-2 | https://github.com/Tencent-Hunyuan/Hunyuan3D-2 | `~/ai3d/Hunyuan3D-2` | Background removal and Hunyuan3D-2mini shape generation |
| AiGameKit / Paint3D | https://github.com/maikramer/AiGameKit | `~/ai3d/AiGameKit/Paint3D` | Multi-view texture inference, UV atlas and PBR baking |
| Blender | https://www.blender.org/ | `blender` on PATH | GLB prepaint mesh decimation, final optimization, rig tooling |
| Local Space Nova AI3D repository | `bushman77/space-nova-ai3d` | `~/space-nova-ai3d` | Our orchestration scripts, documentation, testing |

Use upstream install instructions. In particular:

```bash
# stable-diffusion.cpp (CUDA example)
git clone --recursive https://github.com/leejet/stable-diffusion.cpp
cmake -S stable-diffusion.cpp -B stable-diffusion.cpp/build -DSD_CUDA=ON
cmake --build stable-diffusion.cpp/build --config Release -j 4

# AiGameKit provides an official Paint3D installer from its repository root:
./install.sh paint3d
```

The snippets above are examples in their respective working directories, not a complete copy-paste bootstrap. Pin source commit SHAs before making an automated installation script.

## 3. Python dependencies — **separate virtual environments**

### Hunyuan3D-2 `.venv`

Launcher: `~/ai3d/Hunyuan3D-2/.venv/bin/python`

- Core inference: **torch**, **torchvision**, **diffusers**, **transformers**, **accelerate**, **safetensors**, **einops**, **omegaconf**, **tqdm**.
- Image and background removal: **Pillow**, **rembg**, **onnxruntime**, **opencv-python**.
- Mesh processing / formats: **numpy**, **trimesh**, **pymeshlab**, **pygltflib**, **xatlas**.
- Builds/extensions as required by upstream: **ninja**, **pybind11**.
- Install from upstream `requirements.txt`, then `pip install -e .` using a PyTorch wheel compatible with your GPU/driver. Some upstream requirements are for demos or optional texturing and may be unnecessary for the shape-only workflow.

### AiGameKit Paint3D `.venv`

Launcher: `~/ai3d/AiGameKit/Paint3D/.venv/bin/python`

- **aigamekit-shared** (from the AiGameKit `Shared` directory).
- **paint3d** editable package and its declared dependencies.
- **torch**, **torchvision** with CUDA-capable builds.
- **nvdiffrast** compiled GPU rasterizer.
- **xatlas**, **pymeshlab**, **omegaconf** for UV and texture/mesh pipeline.
- **Hunyuan3D-Paint 2.1** vendored inference code; model weights downloaded separately/on demand.
- **Real-ESRGAN** support for texture/image upscaling where enabled; **spandrel** is an optional extra.
- Prefer the official AiGameKit `./install.sh paint3d` rather than attempting to combine these dependencies with Hunyuan's `.venv`.
- Current AiGameKit upstream documents Python **3.13** for its tool packages. The working machine's *actual* Python/PyTorch versions must be recorded before upgrading or recreating environments.

### Blender scripts and rigging

- Blender includes its own Python and `bpy` API; our current launcher uses Blender in `--background --python` mode.
- Our procedural **51-bone male/female rig scripts** are Blender-based, not dependent on a separate AI rigging service.
- For mesh audits outside Blender, Python **trimesh** and **numpy** suffice for our existing checks.
- **Node.js** and **three** are optional for Three.js/glTF validation in Space Nova, not required to generate or paint a mesh.

## 4. Model weights / inference assets (not installable with `apt`)

These are *downloaded separately*, sometimes automatically by the upstream tools. Do not commit them to GitHub.

| Asset | Expected path or source | Used for |
|---|---|---|
| Qwen Image diffusion GGUF | `~/models/Qwen-Image-2512/qwen-image-2512-Q3_K_M.gguf` | Stage 1 reference generation |
| Qwen2.5-VL text encoder / LLM GGUF | `~/models/Qwen-Image-2512/Qwen2.5-VL-7B-Instruct-Q4_K_M.gguf` | Stage 1 prompt/conditioning |
| Qwen image VAE | `~/models/Qwen-Image-2512/qwen_image_vae.safetensors` | Stage 1 image decoding |
| Hunyuan3D-2mini | `~/ai3d/models/Hunyuan3D-2mini/hunyuan3d-dit-v2-mini/model.fp16.safetensors` (with supporting model config files) | Stage 3 shape generation |
| Background remover checkpoint | `rembg`/Hunyuan model cache | Stage 2 cutout |
| Paint3D / Hunyuan3D-Paint 2.1 weights | AiGameKit / Hugging Face cache according to upstream installer | Stage 5 texturing |
| Upscale weights, where enabled | AiGameKit cache / Real-ESRGAN assets | Enhanced texture views |

Model licensing must be reviewed separately from source-code licensing, especially before commercial distribution.

## 5. Current pipeline dependencies by stage

| Stage | Required components | Result |
|---|---|---|
| 1. Reference | `sd-cli` + Qwen weights + CUDA + `systemd-run` | `01_reference.png` |
| 2. Cutout | Hunyuan Python environment, `Pillow`, `rembg` and model | `02_cutout.png` |
| 3. Shape | Hunyuan Python environment, PyTorch/CUDA, Hunyuan3D-2mini weights, trimesh | `03_shape.glb` |
| 4. Prepaint | Blender glTF import/export + decimation | `04_paint_mesh.glb` |
| 4B. Connect | Hunyuan Python, `numpy`, `trimesh` | `04_paint_connected.glb` |
| 5. Paint | Paint3D environment, CUDA/PyTorch, `nvdiffrast`, `xatlas`, Paint3D weights | `05_painted.glb` |
| 6. Game export | Blender glTF import/export, decimation | `06_game.glb` |

## 6. Verification commands for the **existing working laptop**

```bash
nvidia-smi
nvcc --version  # may be missing even when driver and PyTorch CUDA work
blender --version | head -n 2
python3 --version
~/ai3d/Hunyuan3D-2/.venv/bin/python --version
~/ai3d/AiGameKit/Paint3D/.venv/bin/python --version
~/ai3d/Hunyuan3D-2/.venv/bin/python -m pip freeze > hunyuan-freeze.txt
~/ai3d/AiGameKit/Paint3D/.venv/bin/python -m pip freeze > paint3d-freeze.txt
~/ai-image/stable-diffusion.cpp/build/bin/sd-cli --help | head
```

The `pip freeze` outputs are **machine snapshots**, not automatically portable universal requirements files. Review/edit them before pinning versions or adding them to the repository.

## 7. Still needed for a truly reproducible setup

1. Record exact git commit of each upstream repository (`git rev-parse HEAD`).
2. Record Python version, PyTorch version, CUDA toolkit version and Blender version.
3. Preserve one verified dependency lock or constraints file **per environment**.
4. Implement a bootstrap/check script that **detects existing installations before downloading**.
5. Document exact model sources, filenames, checksums and licensing; keep weights outside Git.
6. Move path configuration out of the Bash launcher into a config file without breaking existing installations.

## Primary upstream documentation

- stable-diffusion.cpp build: https://github.com/leejet/stable-diffusion.cpp/blob/master/docs/build.md
- Hunyuan3D-2 install and requirements: https://github.com/Tencent-Hunyuan/Hunyuan3D-2/blob/main/README.md
- Hunyuan3D-2 Python dependencies: https://github.com/Tencent-Hunyuan/Hunyuan3D-2/blob/main/requirements.txt
- AiGameKit installation: https://github.com/maikramer/AiGameKit/blob/main/README.md
- AiGameKit Paint3D: https://github.com/maikramer/AiGameKit/blob/main/Paint3D/README.md
