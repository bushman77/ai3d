"""Pure command builder for Hunyuan background removal.

Running the original inline program using python -c with cwd set to the
Hunyuan checkout preserves the original Python import paths. Heavy imports
run only inside the separate Hunyuan Python process.
"""

from pathlib import Path

_REMOVAL_SCRIPT = """from pathlib import Path
from PIL import Image
from hy3dgen.rembg import BackgroundRemover
import sys
im = Image.open(sys.argv[1])
alpha = im.convert('RGBA').getchannel('A')
if alpha.getextrema()[0] < 250 or sys.argv[3] == 'skip':
    out = im.convert('RGBA')
    print('Using existing alpha / bypassing cutout')
else:
    print('Removing opaque background...')
    out = BackgroundRemover()(im.convert('RGB'))
out.save(sys.argv[2])
print('Alpha range:', out.getchannel('A').getextrema(), 'Size:', out.size)
"""


def build_cutout_command(
    python: Path, reference: Path, output: Path, *, skip: bool = False
) -> list[str]:
    """Return a command using the source environment's Python and rembg."""
    return [
        str(python), "-c", _REMOVAL_SCRIPT, str(reference), str(output),
        "skip" if skip else "auto",
    ]
