"""The verifiers v1 taskset and env, run end to end against a scripted model server."""

import asyncio
import json
import shutil
import sys

import pytest
import verifiers.v1 as vf
from aiohttp import web
from menu_taste import MenuTasteEnv, MenuTasteTaskset, results
from menu_taste.cloze import SYSTEM_PROMPT
from menu_taste.questions import build, load_question_set, to_row
from menu_taste.scoring import grade, load_run
from menu_taste.taskset import MenuTasteConfig, MenuTasteEnvConfig


def _tasks(**config):
    return list(MenuTasteTaskset(MenuTasteConfig(id="menu-taste", **config)))


def _run(tmp_path, reply, taskset=None, limit=4):
    """Run the eval CLI's runner on the env's defaults; ``reply(prompt)`` scripts the
    model (``None`` fails the request). Returns the traces and every request the
    model received."""
    from verifiers.v1.cli.eval.runner import run_eval
    from verifiers.v1.configs.cli.eval import EvalConfig
    from verifiers.v1.dialects.chat import ChatDialect

    dialect = ChatDialect()
    requests = []

    async def answer(request: web.Request) -> web.StreamResponse:
        body = await request.json()
        requests.append(body)
        user = next(m["content"] for m in body["messages"] if m["role"] == "user")
        content = reply(user)
        if content is None:
            return web.json_response({"error": {"message": "refused"}}, status=400)
        raw = {
            "id": "scripted",
            "object": "chat.completion",
            "created": 0,
            "model": "scripted",
            "choices": [
                {
                    "index": 0,
                    "finish_reason": "stop",
                    "message": {"role": "assistant", "content": content},
                }
            ],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        }
        if not dialect.streaming(body):
            return web.json_response(raw)
        response = web.StreamResponse(headers={"Content-Type": "text/event-stream"})
        await response.prepare(request)
        for event in dialect.stream_events(raw):
            await response.write(event)
        await response.write_eof()
        return response

    async def _go():
        app = web.Application()
        app.router.add_post("/{tail:.*}", answer)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        port = site._server.sockets[0].getsockname()[1]
        try:
            config = EvalConfig(
                env={"taskset": {"id": "menu-taste", **(taskset or {})}},
                select={"limit": limit},
                client={
                    "base_url": f"http://127.0.0.1:{port}/v1",
                    "api_key_var": "MENU_TASTE_SCRIPTED_KEY",
                },
                model="scripted",
                rich=None,
                push=False,
                output_dir=tmp_path,
                run={"dir": "run"},
            )
            records = await run_eval(config)
        finally:
            await runner.cleanup()
        return [trace for record in records for trace in record.traces]

    return asyncio.run(_go()), requests


@pytest.fixture(autouse=True)
def _key(monkeypatch):
    monkeypatch.setenv("MENU_TASTE_SCRIPTED_KEY", "scripted")


def test_one_plain_chat_turn_per_question_scored_on_the_letter(tmp_path):
    keys = {t.data.prompt: t.data.answer for t in _tasks()}
    wrong = {k: "A" if v != "A" else "B" for k, v in keys.items()}

    traces, requests = _run(
        tmp_path, lambda p: f"Fits best.\n<answer>({keys[p]})</answer>"
    )
    assert len(traces) == len(requests) == 4  # one model call each
    for body in requests:
        assert "tools" not in body
        assert [m["role"] for m in body["messages"]] == ["system", "user"]
        assert body["messages"][0]["content"] == SYSTEM_PROMPT
    assert all(t.errors == [] for t in traces)
    assert [t.reward for t in traces] == [1.0] * 4
    assert all(t.metrics["answered"] == 1.0 for t in traces)

    traces, _ = _run(tmp_path, lambda p: f"<answer>{wrong[p]}</answer>")
    assert [t.reward for t in traces] == [0.0] * 4
    assert all(t.metrics["answered"] == 1.0 for t in traces)

    traces, _ = _run(tmp_path, lambda p: keys[p])  # no tags
    assert [(t.reward, t.metrics["answered"]) for t in traces] == [(0.0, 0.0)] * 4


def test_frozen_set_with_rotation_is_served_and_scored_from_traces(tmp_path):
    questions = tmp_path / "questions.jsonl"
    build("menu_taste/data/sample_menus.jsonl", str(questions))
    records = {r["id"]: r for r in load_question_set(questions)}
    by_prompt = {
        to_row(r, 2)["question"]: to_row(r, 2)["answer"] for r in records.values()
    }

    traces, _ = _run(
        tmp_path,
        lambda p: f"<answer>{by_prompt[p]}</answer>",
        taskset={"questions_path": str(questions), "rotation": 2},
    )
    assert [t.reward for t in traces] == [1.0] * 4
    assert {t.task.data.id for t in traces} <= set(records)

    # menu-taste-score reads the run's traces.jsonl against the question set.
    graded = grade(records, load_run(tmp_path / "run" / "traces.jsonl"))
    assert len(graded) == 4 and all(g["correct"] for g in graded)


def test_every_task_validates_and_the_key_names_the_hidden_dish():
    tasks = _tasks()
    assert len({t.data.id for t in tasks}) == len(tasks)
    for task in tasks:
        assert asyncio.run(task.validate(None))
        assert task.data.target in task.data.prompt
        assert f"{task.data.answer}. {task.data.target}" in task.data.prompt


def test_env_pins_a_plain_chat_and_refuses_code_running_harnesses():
    config = MenuTasteEnvConfig(taskset={"id": "menu-taste"})
    assert config.agent.harness.id == "null"
    assert config.agent.runtime.type == "subprocess"
    assert config.agent.max_turns == 1
    with pytest.raises(ValueError, match="answer key"):
        MenuTasteEnv(
            MenuTasteEnvConfig(
                taskset={"id": "menu-taste"}, agent={"harness": {"id": "bash"}}
            )
        )


def test_missing_corpus_is_a_clear_error(tmp_path):
    empty = tmp_path / "menus.jsonl"
    empty.write_text("")
    with pytest.raises(ValueError, match="No questions"):
        _tasks(menus_path=str(empty))


def test_trace_data_round_trips(tmp_path):
    traces, _ = _run(tmp_path, lambda p: "<answer>A</answer>", limit=1)
    line = (tmp_path / "run" / "traces.jsonl").read_text().splitlines()[0]
    data = json.loads(line)["task"]["data"]
    assert data["answer"] == traces[0].task.data.answer
    assert (
        vf.Trace.model_validate(json.loads(line)["traces"][0]).last_reply
        == "<answer>A</answer>"
    )


FAKE_RUNNER = """#!{python}
# Stands in for scripts/prime_rl_eval.sh: lays out a recorded episode file the way
# prime-rl's eval does (monitors/file/traces/stream/*.jsonl.zst) and exits 0.
import subprocess, sys
from pathlib import Path
args = sys.argv[1:]
model = args[args.index("-m") + 1]
run = Path(args[args.index("--output-dir") + 1]) / args[args.index("--run.name") + 1]
stream = run / "monitors/file/traces/stream"
stream.mkdir(parents=True, exist_ok=True)
src = Path({episodes!r}) / f"{{run.name}}.jsonl"
subprocess.run(["zstd", "-qf", str(src), "-o", str(stream / "00000.jsonl.zst")], check=True)
with open(Path({episodes!r}) / "calls.txt", "a") as f:
    f.write(model + "\\n")
"""


@pytest.mark.skipif(not shutil.which("zstd"), reason="needs the zstd CLI")
def test_results_command_scores_each_model_and_fails_on_errored_rollouts(
    tmp_path, monkeypatch
):
    questions = tmp_path / "questions.jsonl"
    build("menu_taste/data/sample_menus.jsonl", str(questions))
    records = load_question_set(questions)
    keys = {to_row(r)["question"]: to_row(r)["answer"] for r in records}
    episodes = tmp_path / "episodes"
    episodes.mkdir()
    refused = set()

    def flaky(prompt):  # right, but the provider refuses the first question it sees
        if not refused:
            refused.add(prompt)
        return None if prompt in refused else f"<answer>{keys[prompt]}</answer>"

    for model, reply in [
        ("good", lambda p: f"<answer>{keys[p]}</answer>"),
        ("flaky", flaky),
    ]:
        _run(tmp_path / model, reply, taskset={"questions_path": str(questions)})
        shutil.copy(
            tmp_path / model / "run" / "traces.jsonl", episodes / f"{model}.jsonl"
        )
    runner = tmp_path / "prime_rl_eval.sh"
    runner.write_text(FAKE_RUNNER.format(python=sys.executable, episodes=str(episodes)))
    runner.chmod(0o755)
    monkeypatch.setattr(results, "RUNNER", runner)

    out = tmp_path / "out"
    argv = [str(questions), "-m", "good", "-m", "flaky", "-r", "1", "-n", "4"]
    assert results.main([*argv, "--out", str(out)]) == 1  # the eval itself exited 0
    text = (out / "results.md").read_text()
    n = len(records)
    assert f"| good | 4 of {n} | 100.0% | 100.0%–100.0% | 0 | 0 |" in text
    assert f"| flaky | 3 of {n} | 100.0% | 100.0%–100.0% | 0 | 1 |" in text
    assert "| baseline: most words shared with the menu | all |" in text
    assert "| answer shares no words with the menu |" in text

    # A complete run is reused; only the run with an error is evaluated again.
    assert results.main([*argv, "--out", str(out)]) == 1
    assert (episodes / "calls.txt").read_text().split() == ["good", "flaky", "flaky"]

    # Same rollout count (4), different settings: the cached run isn't reused, and
    # 4 questions answered once don't pass for 2 questions answered twice.
    argv = [str(questions), "-m", "good", "-r", "2", "-n", "2", "--out", str(out)]
    assert results.main(argv) == 1
    assert (episodes / "calls.txt").read_text().split()[-1] == "good"
    assert "| good | 4 of" in (out / "results.md").read_text()

    # A failed rerun leaves no stamp, so the old traces aren't reused next time; and
    # a model whose id shares the slug doesn't reuse another model's run.
    argv = [str(questions), "-r", "1", "-n", "4", "--out", str(out)]
    assert results.main([*argv, "-m", "good"]) == 0
    calls = len((episodes / "calls.txt").read_text().split())
    runner.write_text("#!/bin/sh\nexit 3\n")
    assert results.main([*argv, "-m", "good", "--", "--seed", "1"]) == 1
    runner.write_text(FAKE_RUNNER.format(python=sys.executable, episodes=str(episodes)))
    assert results.main([*argv, "-m", "good", "--", "--seed", "1"]) == 0
    assert results.main([*argv, "-m", "good/", "--", "--seed", "1"]) == 0
    assert len((episodes / "calls.txt").read_text().split()) == calls + 2
