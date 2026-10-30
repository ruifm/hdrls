"""Build pinned upstream projects with a mocked LLM and check the header lists.

Each case clones a fixed tag, so the project side of the expected list is
stable. System header paths depend on the ubuntu:24.04 image (GCC 13). The
tests need podman and network access (GitHub and the Ubuntu archive).
Run only the fast tests with `pytest -m "not projects"`.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from hdrls import cli

pytestmark = [
    pytest.mark.projects,
    pytest.mark.skipif(shutil.which("podman") is None, reason="podman not on PATH"),
]

EXPECTED_DIR = Path(__file__).parent / "projects"

# name: (url, tag, mocked LLM plan). The plans cover CMake, plain Make,
# Meson, and Autotools, and both C and C++.
PROJECTS = {
    "zlib": ("https://github.com/madler/zlib", "v1.3.1", {
        "apt_packages": ["cmake", "make", "gcc", "libc6-dev"],
        "setup_commands": ["cmake -S . -B build -DCMAKE_BUILD_TYPE=Release"],
        "build_commands": ["cmake --build build -j$(nproc)"],
    }),
    "lua": ("https://github.com/lua/lua", "v5.4.7", {
        "apt_packages": ["make", "gcc", "libc6-dev", "libreadline-dev"],
        "setup_commands": [],
        "build_commands": ["make -j$(nproc)"],
    }),
    "inih": ("https://github.com/benhoyt/inih", "r58", {
        "apt_packages": ["meson", "ninja-build", "gcc", "g++", "libc6-dev"],
        "setup_commands": ["meson setup build"],
        "build_commands": ["ninja -C build"],
    }),
    "tinyxml2": ("https://github.com/leethomason/tinyxml2", "10.0.0", {
        "apt_packages": ["cmake", "make", "g++", "libc6-dev"],
        "setup_commands": ["cmake -S . -B build"],
        "build_commands": ["cmake --build build -j$(nproc)"],
    }),
    "libyaml": ("https://github.com/yaml/libyaml", "0.2.5", {
        "apt_packages": ["autoconf", "automake", "libtool", "make", "gcc", "libc6-dev"],
        "setup_commands": ["./bootstrap", "./configure"],
        "build_commands": ["make -j$(nproc)"],
    }),
}


@pytest.mark.parametrize("name", sorted(PROJECTS))
def test_project_direct_headers(name, tmp_path):
    url, tag, plan = PROJECTS[name]
    upstream = tmp_path / "upstream"
    subprocess.run(
        ["git", "clone", "-q", "--depth", "1", "--branch", tag, url, str(upstream)], check=True
    )
    reply = json.dumps({**plan, "notes": ""})
    calls = []

    def fake_chat(api_key, model, messages):
        calls.append(messages)
        return reply

    workdir = tmp_path / "work"
    result = cli.run(f"file://{upstream}", workdir, "dummy", "m", 1, 1800, chat_fn=fake_chat)

    assert len(calls) == 1
    assert result == (EXPECTED_DIR / f"{name}.txt").read_text().splitlines()
    entries = json.loads((workdir / "out" / "compile_commands.headers.json").read_text())
    assert entries
    assert all(e["arguments"][-2:] == ["-H", "-fsyntax-only"] for e in entries)
