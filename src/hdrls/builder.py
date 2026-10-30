"""Build loop: ask the LLM for a plan, build, and feed failures back."""

import json
from collections.abc import Callable
from pathlib import Path

from . import container, llm, log, repo

EMPTY_COMPDB_MESSAGE = (
    "build succeeded but bear captured no compile commands; make sure "
    "build_commands actually compile the C/C++ sources (for example, the tree "
    "was already built, or compilation happens in setup_commands)"
)


class BuildFailed(Exception):
    pass


def _load_compdb(path: Path) -> list | None:
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, list) and data else None


def build_until_success(
    url: str,
    src: Path,
    workdir: Path,
    api_key: str,
    model: str,
    max_attempts: int,
    timeout: int,
    chat_fn: Callable[[str, str, list[dict]], str] = llm.chat,
) -> tuple[str, llm.BuildPlan]:
    out = workdir / "out"
    logs = workdir / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    messages = llm.initial_messages(url, repo.gather_context(src))

    for attempt in range(1, max_attempts + 1):
        log(f"attempt {attempt}/{max_attempts}: asking {model} for a build plan")
        reply = chat_fn(api_key, model, messages)
        messages.append({"role": "assistant", "content": reply})

        stage, code, text = _try_plan(reply, src, out, timeout)
        if stage is None:
            plan, tag = text
            (workdir / "plan.json").write_text(json.dumps(plan.to_dict(), indent=2) + "\n")
            log(f"attempt {attempt}: build succeeded with image {tag}")
            return tag, plan

        (logs / f"attempt-{attempt}-{stage}.log").write_text(text)
        log(f"attempt {attempt}: failed at stage {stage} (exit {code})")
        messages.append(llm.fix_message(stage, code, text))

    raise BuildFailed(f"build did not succeed after {max_attempts} attempts; logs in {logs}")


def _try_plan(reply: str, src: Path, out: Path, timeout: int):
    """Return (None, None, (plan, tag)) on success, else (stage, exit_code, log)."""
    try:
        plan = llm.parse_plan(reply)
    except ValueError as e:
        return "invalid-json", None, str(e)
    log(f"plan: apt={plan.apt_packages} setup={plan.setup_commands} build={plan.build_commands}")

    ok, tag, image_log = container.build_image(plan)
    if not ok:
        return "image-build", 1, image_log

    repo.reset(src)
    code, build_log = container.run_build(tag, src, out, plan, timeout)
    if code != 0:
        return "build", code, build_log

    if _load_compdb(out / container.COMPDB_NAME) is None:
        return "empty-compdb", 0, f"{build_log}\n{EMPTY_COMPDB_MESSAGE}"
    return None, None, (plan, tag)
