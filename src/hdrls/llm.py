"""OpenRouter chat client and build-plan parsing."""

import json
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass

API_URL = "https://openrouter.ai/api/v1/chat/completions"
TIMEOUT = 180
LOG_TAIL_LINES = 300
LOG_TAIL_CHARS = 15000

SYSTEM_PROMPT = """\
You prepare a minimal build environment for an upstream C/C++ project.

Constraints:
- The base image is fixed: ubuntu:24.04. The tool always installs bear, \
ca-certificates and git. Propose the smallest set of extra apt packages \
(they are installed with --no-install-recommends). Start minimal and add \
packages only when they are needed.
- The source is at /src, which is also the working directory. Commands run \
as root in bash with `set -euo pipefail`. Network access is available.
- setup_commands: configure or generate steps (cmake configure, ./configure, \
meson setup, autoreconf). These are NOT run under bear.
- build_commands: the steps that compile the C/C++ sources (make, ninja, \
cmake --build). Each one is run under bear to record the compilation \
database. Prefer an out-of-tree build in /src/build when the build system \
supports it. Do not build tests or docs unless the default target needs \
them. Use -j$(nproc).

Reply with only one JSON object and no other text:
{"apt_packages": [...], "setup_commands": [...], "build_commands": [...], "notes": "..."}
"""


@dataclass
class BuildPlan:
    apt_packages: list[str]
    setup_commands: list[str]
    build_commands: list[str]
    notes: str

    def to_dict(self) -> dict:
        return asdict(self)


def chat(api_key: str, model: str, messages: list[dict]) -> str:
    body = json.dumps({"model": model, "messages": messages, "temperature": 0}).encode()
    req = urllib.request.Request(
        API_URL,
        data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "X-Title": "hdrls",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            data = json.load(resp)
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"OpenRouter HTTP {e.code}: {e.read().decode(errors='replace')}") from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"OpenRouter request failed: {e.reason}") from e
    try:
        return data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as e:
        raise RuntimeError(f"unexpected OpenRouter response: {data}") from e


def _str_list(obj: dict, key: str) -> list[str]:
    value = obj.get(key, [])
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise ValueError(f"{key!r} must be a list of strings")
    return value


def parse_plan(text: str) -> BuildPlan:
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < start:
        raise ValueError("reply contains no JSON object")
    try:
        obj = json.loads(text[start : end + 1])
    except json.JSONDecodeError as e:
        raise ValueError(f"reply is not valid JSON: {e}") from e
    if not isinstance(obj, dict):
        raise ValueError("reply JSON is not an object")
    plan = BuildPlan(
        apt_packages=_str_list(obj, "apt_packages"),
        setup_commands=_str_list(obj, "setup_commands"),
        build_commands=_str_list(obj, "build_commands"),
        notes=str(obj.get("notes", "")),
    )
    if not plan.build_commands:
        raise ValueError("'build_commands' must not be empty")
    return plan


def initial_messages(url: str, context: str) -> list[dict]:
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"Repository: {url}\n\n{context}"},
    ]


def fix_message(stage: str, exit_code: int | None, log: str) -> dict:
    tail = "\n".join(log.splitlines()[-LOG_TAIL_LINES:])[-LOG_TAIL_CHARS:]
    code = "n/a" if exit_code is None else str(exit_code)
    return {
        "role": "user",
        "content": (
            f"The plan failed at stage '{stage}' (exit code {code}).\n"
            f"Log tail:\n```\n{tail}\n```\n"
            "Return a full corrected JSON plan with the same keys, and nothing else."
        ),
    }
