"""Podman image build, build run, and a long-lived exec session."""

import hashlib
import secrets
import shlex
import subprocess
import tempfile
from pathlib import Path

from . import log
from .llm import BuildPlan

BASE_IMAGE = "docker.io/library/ubuntu:24.04"
BASE_PACKAGES = ["bear", "ca-certificates", "git"]
OUT_MOUNT = "/hdrls-out"
COMPDB_NAME = "compile_commands.json"


def containerfile(plan: BuildPlan) -> str:
    packages = " ".join(BASE_PACKAGES + sorted(set(plan.apt_packages) - set(BASE_PACKAGES)))
    return (
        f"FROM {BASE_IMAGE}\n"
        "ENV DEBIAN_FRONTEND=noninteractive\n"
        f"RUN apt-get update && apt-get install -y --no-install-recommends {packages}"
        " && rm -rf /var/lib/apt/lists/*\n"
    )


def build_image(plan: BuildPlan) -> tuple[bool, str, str]:
    text = containerfile(plan)
    tag = f"localhost/hdrls-env:{hashlib.sha256(text.encode()).hexdigest()[:12]}"
    if subprocess.run(["podman", "image", "exists", tag]).returncode == 0:
        log(f"image {tag} already exists")
        return True, tag, ""
    log(f"building image {tag}")
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "Containerfile").write_text(text)
        proc = subprocess.run(
            ["podman", "build", "-t", tag, "-f", "Containerfile", tmp],
            cwd=tmp,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            errors="replace",
        )
    return proc.returncode == 0, tag, proc.stdout


def build_script(plan: BuildPlan) -> str:
    lines = ["set -euo pipefail", *plan.setup_commands]
    # Only build_commands run under bear, so configure test programs stay out
    # of the database. The database lives outside /src so a tracked
    # compile_commands.json cannot conflict and git clean cannot remove it.
    for cmd in plan.build_commands:
        lines.append(
            f"bear --append --output {OUT_MOUNT}/{COMPDB_NAME} -- bash -c {shlex.quote(cmd)}"
        )
    return "\n".join(lines) + "\n"


def run_build(tag: str, src: Path, out: Path, plan: BuildPlan, timeout: int) -> tuple[int, str]:
    out.mkdir(parents=True, exist_ok=True)
    (out / COMPDB_NAME).unlink(missing_ok=True)
    args = [
        "podman", "run", "--rm",
        "-v", f"{src}:/src", "-v", f"{out}:{OUT_MOUNT}", "-w", "/src",
        tag, "bash", "-c", build_script(plan),
    ]
    try:
        proc = subprocess.run(
            args,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            errors="replace",
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as e:
        partial = e.stdout.decode(errors="replace") if isinstance(e.stdout, bytes) else (e.stdout or "")
        return 124, f"{partial}\ntimeout after {timeout} s"
    return proc.returncode, proc.stdout


class Session:
    """A detached container that runs commands with `podman exec`."""

    def __init__(self, tag: str, src: Path, out: Path):
        self.tag, self.src, self.out = tag, src, out
        self.name = f"hdrls-{secrets.token_hex(4)}"

    def __enter__(self) -> "Session":
        subprocess.run(
            [
                "podman", "run", "-d", "--rm", "--name", self.name,
                "-v", f"{self.src}:/src", "-v", f"{self.out}:{OUT_MOUNT}",
                self.tag, "sleep", "infinity",
            ],
            check=True,
            stdout=subprocess.DEVNULL,
        )
        return self

    def exec(self, args: list[str], cwd: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["podman", "exec", "-w", cwd, self.name, *args],
            capture_output=True,
            text=True,
            errors="replace",
        )

    def __exit__(self, *exc) -> None:
        subprocess.run(["podman", "rm", "-f", "-t", "0", self.name], capture_output=True)
