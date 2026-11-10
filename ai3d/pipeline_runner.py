"""Dependency-free subprocess runner and resumable pipeline-stage executor.

This is intentionally a behavior-preserving extraction of the original
Space Nova Runner. Stage caching uses input path, size, mtime and options;
this is not content-addressed caching. In dry-run mode run() does not invoke
an arbitrary action (to avoid accidentally executing side effects).
"""

import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import time

from ai3d.common import ensure_file, resolve


class Runner:
    """Execute stages in a per-run directory, with logs and resume manifests."""

    def __init__(self, root: Path, resume: bool, force: bool, dry: bool):
        self.root = Path(root)
        self.logs = self.root / "logs"
        self.meta = self.root / ".stages"
        self.resume = resume
        self.force = force
        self.dry = dry
        if not dry:
            self.logs.mkdir(parents=True, exist_ok=True)
            self.meta.mkdir(parents=True, exist_ok=True)
        self.timing: dict[str, dict] = {}

    @staticmethod
    def fingerprint(paths: list[Path], config: dict) -> str:
        data = {"config": config, "paths": []}
        for path in paths:
            path = resolve(path)
            if path.exists():
                stat = path.stat()
                data["paths"].append([str(path), stat.st_size, stat.st_mtime_ns])
            else:
                data["paths"].append([str(path), "missing"])
        return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()

    def run(self, label: str, inputs: list[Path], outputs: list[Path], config: dict, action) -> None:
        token = self.fingerprint(inputs, config)
        stamp = self.meta / f"{label}.json"
        if self.resume and not self.force and stamp.is_file() and all(
            output.is_file() and output.stat().st_size for output in outputs
        ):
            try:
                previous = json.loads(stamp.read_text())
                if previous.get("fingerprint") == token:
                    print(f"[SKIP] {label}: validated cached outputs", flush=True)
                    self.timing[label] = {"cached": True, "seconds": 0}
                    return
            except (OSError, ValueError):
                pass
        print(f"\n[RUN] {label}", flush=True)
        start = time.monotonic()
        if not self.dry:
            action()
            for output in outputs:
                ensure_file(output, label + " output")
            stamp.write_text(json.dumps({
                "fingerprint": token,
                "outputs": [str(output) for output in outputs],
            }, indent=2))
        self.timing[label] = {"cached": False, "seconds": round(time.monotonic() - start, 1)}

    def command(self, label: str, cmd: list[str], cwd: Path | None = None, env: dict | None = None) -> None:
        print("$ " + subprocess.list2cmdline(cmd), flush=True)
        if self.dry:
            return
        log = self.logs / f"{label}.log"
        with log.open("w") as output:
            process = subprocess.Popen(
                cmd, cwd=str(cwd) if cwd else None,
                env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, errors="replace", bufsize=1,
            )
            assert process.stdout is not None
            try:
                for line in process.stdout:
                    output.write(line)
                    output.flush()
                    print(line, end="", flush=True)
            finally:
                process.stdout.close()
            status = process.wait()
        if status:
            raise RuntimeError(f"{label} failed (exit {status}). Full log: {log}")

    def copy(self, source: Path, target: Path) -> None:
        print(f"copy {source} -> {target}", flush=True)
        if not self.dry and source != target:
            shutil.copy2(source, target)
