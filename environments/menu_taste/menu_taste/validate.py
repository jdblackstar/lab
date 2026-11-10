"""``vf-validate menu-taste`` on the local subprocess runtime, and only there.

    menu-taste-validate [vf-validate options]
    menu-taste-validate --taskset.questions-path private/questions-v1.jsonl -o private/validate

``vf-validate`` checks a taskset, not the env, so it never sees the env's pinned
subprocess runtime and defaults to hosted Prime sandboxes, two per question (gold and
noop checks). verifiers 0.4 has no taskset-level runtime default and no task hook that
sees the runtime before its sandbox starts, so this entry point sets the runtime itself
and refuses any other. The checks only compare each question's key with its options.
"""

from __future__ import annotations

import sys

from verifiers.v1.cli.validate import main as vf_validate

RUNTIME = "subprocess"


def main(argv: list[str] | None = None) -> None:
    argv = list(sys.argv[1:] if argv is None else argv)
    for i, arg in enumerate(argv):
        if arg == "--runtime.type":
            value = argv[i + 1] if i + 1 < len(argv) else ""
        elif arg.startswith("--runtime.type="):
            value = arg.split("=", 1)[1]
        else:
            continue
        if value != RUNTIME:
            raise SystemExit(
                f"menu-taste validates on the {RUNTIME} runtime only, not {value!r}: "
                "every question carries a whole menu, and the checks need no sandbox."
            )
    # Last, so it overrides a runtime set in a `@ file.toml`.
    vf_validate(["--taskset.id", "menu-taste", *argv, "--runtime.type", RUNTIME])
