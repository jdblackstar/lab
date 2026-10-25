"""The verifiers v1 taskset and env, run end to end against a scripted model server."""

import asyncio
import json
import subprocess
import sys

import pytest
import verifiers.v1 as vf
from aiohttp import web
from menu_taste import MenuTasteEnv, MenuTasteTaskset
from menu_taste.cloze import SYSTEM_PROMPT
from menu_taste.questions import build, load_question_set, to_row
from menu_taste.scoring import grade, load_run
from menu_taste.taskset import MenuTasteConfig, MenuTasteEnvConfig


def _tasks(**config):
    return list(MenuTasteTaskset(MenuTasteConfig(id="menu-taste", **config)))


def _run(tmp_path, reply, taskset=None, limit=4):
    """Run the eval CLI's runner on the env's defaults; ``reply(prompt)`` scripts the
    model. Returns the traces and every request the model received."""
    from verifiers.v1.cli.eval.runner import run_eval
    from verifiers.v1.configs.cli.eval import EvalConfig
    from verifiers.v1.dialects.chat import ChatDialect

    dialect = ChatDialect()
    requests = []

    async def answer(request: web.Request) -> web.StreamResponse:
        body = await request.json()
        requests.append(body)
        user = next(m["content"] for m in body["messages"] if m["role"] == "user")
        raw = {
            "id": "scripted",
            "object": "chat.completion",
            "created": 0,
            "model": "scripted",
            "choices": [
                {
                    "index": 0,
                    "finish_reason": "stop",
                    "message": {"role": "assistant", "content": reply(user)},
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


def test_validate_runs_locally_and_refuses_hosted_runtimes(tmp_path):
    from menu_taste.validate import main

    with pytest.raises(SystemExit, match="subprocess runtime only, not 'prime'"):
        main(["--runtime.type", "prime", "-o", str(tmp_path)])
    assert not any(tmp_path.iterdir())  # refused before anything ran

    # A config file can't switch it to hosted sandboxes either.
    toml = tmp_path / "hosted.toml"
    toml.write_text('[runtime]\ntype = "prime"\n')
    args = ["@", str(toml), "-n", "2", "-o", str(tmp_path), "--run.dir", "v"]
    code = f"from menu_taste.validate import main; main({[*args, '--rich', 'false']!r})"
    subprocess.run([sys.executable, "-c", code], check=True, capture_output=True)
    run = tmp_path / "v"
    resolved = json.loads((run / "configs" / "resolved" / "validate.json").read_text())
    assert resolved["runtime"]["type"] == "subprocess"
    assert json.loads((run / "summary.json").read_text())["valid_rate"] == 1.0


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
