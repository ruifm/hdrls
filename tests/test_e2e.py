import json
import shutil
import subprocess

import pytest

from hdrls import cli

pytestmark = pytest.mark.skipif(shutil.which("podman") is None, reason="podman not on PATH")

FILES = {
    "main.c": '#include <stdio.h>\n#include "util.h"\nint main(void) { puts(greet()); return 0; }\n',
    "util.c": '#include "util.h"\n#include <string.h>\nconst char *greet(void) { return strchr("hi", \'h\'); }\n',
    "util.h": "#include <stdlib.h>\nconst char *greet(void);\n",
    "Makefile": "all: app\napp: main.o util.o\n\tcc -o app main.o util.o\n",
}


def _plan(packages):
    return json.dumps(
        {"apt_packages": packages, "setup_commands": [], "build_commands": ["make"], "notes": ""}
    )


def test_build_retry_and_direct_headers(tmp_path):
    upstream = tmp_path / "upstream"
    upstream.mkdir()
    for name, text in FILES.items():
        (upstream / name).write_text(text)
    git = [
        "git", "-C", str(upstream),
        "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false",
    ]
    subprocess.run([*git, "init", "-q"], check=True)
    subprocess.run([*git, "add", "."], check=True)
    subprocess.run([*git, "commit", "-qm", "init"], check=True)

    replies = [_plan([]), _plan(["make", "gcc", "libc6-dev"])]
    calls = []

    def fake_chat(api_key, model, messages):
        calls.append(list(messages))
        return replies[len(calls) - 1]

    workdir = tmp_path / "work"
    result = cli.run(f"file://{upstream}", workdir, "dummy", "m", 3, 600, chat_fn=fake_chat)

    assert len(calls) == 2
    assert "stage 'build'" in calls[1][-1]["content"]
    assert result == ["/src/util.h", "/usr/include/stdio.h", "/usr/include/string.h"]
    assert (workdir / "logs" / "attempt-1-build.log").is_file()

    entries = json.loads((workdir / "out" / "compile_commands.headers.json").read_text())
    assert len(entries) == 2
    assert all(e["arguments"][-2:] == ["-H", "-fsyntax-only"] for e in entries)
