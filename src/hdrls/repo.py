"""Clone the upstream repository and collect build context for the LLM."""

import subprocess
from pathlib import Path

from . import log

CONTEXT_FILES = [
    "INSTALL*",
    "BUILDING*",
    "CMakeLists.txt",
    "meson.build",
    "meson_options.txt",
    "meson.options",
    "configure.ac",
    "Makefile",
    "GNUmakefile",
    "makefile",
    "Makefile.am",
    "SConstruct",
    "BUILD.bazel",
    "debian/control",
]
MAX_TREE_ENTRIES = 300
MAX_FILE_CHARS = 8000
MAX_TOTAL_CHARS = 60000
MAX_WORKFLOWS = 3


def clone(url: str, dest: Path) -> None:
    if (dest / ".git").exists():
        log(f"reusing existing clone in {dest}")
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    log(f"cloning {url} into {dest}")
    proc = subprocess.run(
        ["git", "clone", "--depth", "1", "--recurse-submodules", "--shallow-submodules", url, str(dest)],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"git clone failed (exit {proc.returncode}):\n{proc.stderr}")


def reset(src: Path) -> None:
    """Return the work tree to the committed state so each attempt starts clean."""
    for args in (
        ["clean", "-ffdx"],
        ["submodule", "foreach", "--recursive", "git clean -ffdx"],
        ["checkout", "--", "."],
    ):
        subprocess.run(["git", "-C", str(src), *args], check=True, capture_output=True)


def _tree(src: Path) -> list[str]:
    entries: list[str] = []
    for top in sorted(src.iterdir()):
        if top.name == ".git":
            continue
        entries.append(top.name + ("/" if top.is_dir() else ""))
        if top.is_dir():
            for child in sorted(top.iterdir()):
                entries.append(f"{top.name}/{child.name}" + ("/" if child.is_dir() else ""))
    return entries[:MAX_TREE_ENTRIES]


def _context_paths(src: Path) -> list[Path]:
    paths: list[Path] = sorted(p for p in src.glob("README*") if p.is_file())
    for pattern in CONTEXT_FILES:
        paths.extend(sorted(p for p in src.glob(pattern) if p.is_file()))
    workflows = src / ".github" / "workflows"
    if workflows.is_dir():
        paths.extend(sorted(p for p in workflows.glob("*.yml") if p.is_file())[:MAX_WORKFLOWS])
    return paths


def gather_context(src: Path) -> str:
    parts = ["File tree (depth 2):", *_tree(src), ""]
    total = 0
    for path in _context_paths(src):
        text = path.read_text(errors="replace")[:MAX_FILE_CHARS]
        if total + len(text) > MAX_TOTAL_CHARS:
            break
        total += len(text)
        parts.append(f"===== {path.relative_to(src)} =====")
        parts.append(text)
    return "\n".join(parts)
