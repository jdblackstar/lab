"""Run models on a frozen question set and write the results section.

    menu-taste-results private/questions-v1.jsonl -m <model> -m <model> -r 3

For each model this runs the environment through prime-rl's eval
(``scripts/prime_rl_eval.sh``), decompresses its traces, and scores every run together
with ``menu-taste-score``: accuracy with intervals resampled by menu, the question set's
no-taste baselines, accuracy by course and by whether shared words give the answer away,
position bias, and how often models chose the same dish. The section is written to
``<out>/results.md``.

Runs land in ``<out>/evals/<model>``. A run made with the same question set and
settings that answered every question ``-r`` times without errors is reused, so
re-running the command after a failure only redoes the models that failed. Arguments after ``--`` go to the eval unchanged (for example
``-- --client.base-url http://localhost:8000/v1``). The command exits 1 when any run
failed, errored, or is incomplete; prime-rl's eval exits 0 even then.
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import re
import shlex
import shutil
import subprocess
import sys
from collections import Counter
from pathlib import Path

from .questions import load_meta, load_question_set
from .scoring import load_run, report

ENV_DIR = Path(__file__).resolve().parents[1]
RUNNER = ENV_DIR.parents[1] / "scripts" / "prime_rl_eval.sh"


def slug(model: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", model).strip("-")


def decompress(run_dir: Path, out: Path) -> bool:
    """Concatenate the run's trace stream (zstd chunks and a plain live chunk) into
    ``out``. False when the run wrote no traces."""
    chunks = sorted((run_dir / "monitors/file/traces/stream").glob("*.jsonl*"))
    if not chunks:
        return False
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "wb") as f:
        subprocess.run(["zstd", "-dcfq", *map(str, chunks)], stdout=f, check=True)
    return True


def problems(rows: list[dict], asked: int, repeats: int) -> list[str]:
    errored = sum(r["error"] for r in rows)
    out = [f"{errored} rollout(s) errored"] if errored else []
    counts = Counter(r["id"] for r in rows)
    if len(counts) != asked or set(counts.values()) - {repeats}:
        out.append(
            f"{len(rows)} rollouts over {len(counts)} questions, "
            f"expected {repeats} on each of {asked}"
        )
    return out


def run_model(
    model: str, questions: Path, evals: Path, eval_args: list[str]
) -> subprocess.CompletedProcess:
    cmd = [
        str(RUNNER),
        str(ENV_DIR),
        "menu-taste",
        "-m",
        model,
        "--env.taskset.questions-path",
        str(questions),
        "--output-dir",
        str(evals),
        "--run.name",
        slug(model),
        "--clean",
        "True",
        "--dashboard",
        "False",
        *eval_args,
    ]
    print(f"==> {model}: {shlex.join(cmd)}", file=sys.stderr, flush=True)
    return subprocess.run(cmd, stdout=sys.stderr)  # stdout carries only the results


def header(questions: Path, models: list[str], repeats: int, command: str) -> str:
    meta = load_meta(questions)
    built = []
    if meta.get("created"):
        built.append(f"built {meta['created']}")
    if meta.get("corpus_sha256"):
        built.append(f"corpus sha256 {meta['corpus_sha256'][:12]}")
    if meta.get("menus_shown"):
        built.append(f"{meta['menus_shown']} menus shown")
    return "\n".join(
        [
            "## Results",
            "",
            f"{len(models)} model(s) on the frozen question set `{questions.name}`"
            + (f" ({', '.join(built)})" if built else "")
            + f", {repeats} answer(s) per question, through the menu-taste environment "
            f"with prime-rl's eval, scored {datetime.date.today().isoformat()}. "
            "Intervals resample whole menus. Errored rollouts are counted, not scored.",
            "",
            f"Generated with `{command}`.",
            "",
            "",
        ]
    )


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    command = shlex.join(["menu-taste-results", *argv])
    eval_args = []
    if "--" in argv:
        split = argv.index("--")
        argv, eval_args = argv[:split], argv[split + 1 :]
    parser = argparse.ArgumentParser(
        prog="menu-taste-results",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "questions", help="Frozen question set (menu-taste-questions build)"
    )
    parser.add_argument(
        "-m",
        "--model",
        action="append",
        required=True,
        help="Model id; repeat for more",
    )
    parser.add_argument(
        "-r", "--repeats", type=int, default=3, help="Answers per question"
    )
    parser.add_argument("-c", "--concurrency", type=int, default=8)
    parser.add_argument(
        "-n", "--limit", type=int, default=None, help="Ask only the first N questions"
    )
    parser.add_argument(
        "--out", default=None, help="Default: results/<set> next to the question set"
    )
    args = parser.parse_args(argv)
    if any(a.startswith("--monitors.prime") for a in eval_args):
        parser.error("--monitors.prime uploads traces, which contain whole menus")
    if len(set(map(slug, args.model))) != len(args.model):
        parser.error(f"models must be distinct: {args.model}")
    if not RUNNER.exists():
        parser.error(f"{RUNNER} not found; run from a checkout of the lab repository")
    if not shutil.which("zstd"):
        parser.error("zstd is required to read prime-rl's traces")

    questions = Path(args.questions).resolve()
    total = len(load_question_set(questions))
    asked = min(args.limit or total, total)
    out = (
        Path(args.out) if args.out else questions.parent / "results" / questions.stem
    ).resolve()
    # What a cached run must match to be reused (concurrency doesn't change results).
    settings = {
        "questions_sha256": hashlib.sha256(questions.read_bytes()).hexdigest(),
        "repeats": args.repeats,
        "limit": args.limit,
        "eval_args": eval_args,
    }
    eval_args = (
        ["-r", str(args.repeats), "-c", str(args.concurrency)]
        + (["-n", str(args.limit)] if args.limit else [])
        + eval_args
    )

    runs, failed = [], {}
    for model in args.model:
        run_dir = out / "evals" / slug(model)
        run_file = out / "runs" / f"{slug(model)}.jsonl"
        stamp = run_file.with_suffix(".settings.json")
        if (
            stamp.exists()
            and json.loads(stamp.read_text()) == {**settings, "model": model}
            and decompress(run_dir, run_file)
            and not problems(load_run(run_file), asked, args.repeats)
        ):
            print(f"==> {model}: reusing {run_dir}", file=sys.stderr)
        else:
            stamp.unlink(missing_ok=True)
            code = run_model(model, questions, out / "evals", eval_args).returncode
            if not decompress(run_dir, run_file):
                failed[model] = [f"eval exited {code} without traces"]
                continue
            found = problems(load_run(run_file), asked, args.repeats)
            if code:
                found.insert(0, f"eval exited {code}")
            if found:
                failed[model] = found + [f"see {run_dir}/logs"]
            else:  # only a run that passed may be reused
                stamp.write_text(
                    json.dumps({**settings, "model": model}, indent=2) + "\n"
                )
        runs.append((model, run_file))

    if not runs:
        print("no model produced traces: " + repr(failed), file=sys.stderr)
        return 1
    text = header(questions, [m for m, _ in runs], args.repeats, command) + report(
        str(questions), [str(f) for _, f in runs], [m for m, _ in runs]
    )
    (out / "results.md").write_text(text + "\n")
    print(text)
    print(f"\nwrote {out / 'results.md'}", file=sys.stderr)
    for model, found in failed.items():
        print(f"FAILED {model}: {'; '.join(found)}", file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
