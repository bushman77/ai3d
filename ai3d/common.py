"""Small, dependency-free filesystem helpers shared by AI3D modules."""

from pathlib import Path


def resolve(path: Path) -> Path:
    """Expand the user's home directory and resolve a local filesystem path."""
    return Path(path).expanduser().resolve()


def ensure_file(path: Path, label: str) -> None:
    """Reject missing and empty inputs/outputs without creating any files."""
    path = Path(path)
    if not path.is_file() or path.stat().st_size == 0:
        raise RuntimeError(f"{label} missing/empty: {path}")
