"""Exercise prime-rl's eval using a local scripted endpoint; no paid model calls."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import verifiers.v1 as vf
from xmage_poc.environment import DECK_CONTEXT_MARKER, XMageEnv, XMageEnvConfig
from xmage_poc.render import render_observation
from xmage_poc.transport import advance_action, is_pass_only_priority
from xmage_poc.verify import read_lines, verify

ROOT = Path(__file__).resolve().parents[1]


def prime_rl_episode(monitor: Path) -> dict:
    """The run's only episode, after requiring every planned episode landed cleanly.

    `uv run eval` exits 0 even when every rollout errors, so read its file monitor:
    an errored episode can report num_errors=0 with ok=false.
    """
    plan = json.loads((monitor / "plan.json").read_text())
    planned = sum(n for groups in plan.values() for n in groups.values())
    index = read_lines(monitor / "traces/stream.index.jsonl")
    bad = [e for e in index if not e["ok"] or e["num_errors"]]
    assert len(index) == planned == 1 and not bad, (
        f"prime-rl eval: {len(index)}/{planned} episodes landed; errored: {bad}"
    )
    episodes = [
        json.loads(line)
        for chunk in sorted((monitor / "traces/stream").glob("*.jsonl.zst"))
        for line in subprocess.run(
            ["zstd", "-dc", str(chunk)], check=True, capture_output=True, text=True
        ).stdout.splitlines()
        if line
    ]
    assert [e["id"] for e in episodes] == [index[0]["id"]], "Trace stream != index"
    return episodes[0]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--java-bin", default=os.environ.get("XMAGE_JAVA_BIN"))
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument(
        "--observation-format", choices=["json", "text"], default="text"
    )
    parser.add_argument(
        "--recording-mode", choices=["full_audit", "benchmark"], default="full_audit"
    )
    parser.add_argument(
        "--opponent",
        choices=["self_play", "scripted", "scripted_v1", "random", "xmage_mad"],
        default="self_play",
    )
    parser.add_argument(
        "--pilot-seat", choices=["player_a", "player_b"], default="player_a"
    )
    parser.add_argument("--pilot-deck", choices=["deck_a", "deck_b"], default="deck_a")
    parser.add_argument("--pilot-play-order", choices=["play", "draw"], default="play")
    parser.add_argument(
        "--no-auto-pass-priority",
        action="store_true",
        help="Send pass-only priority prompts to the endpoint too",
    )
    parser.add_argument(
        "--protocol-only",
        action="store_true",
        help="Run one episode in-process instead of through prime-rl's eval",
    )
    parser.add_argument(
        "--inject-invalid-replies",
        action="store_true",
        help="Exercise parse recovery, index recovery, and exhausted-attempt fallback",
    )
    args = parser.parse_args()
    other_seat = "player_b" if args.pilot_seat == "player_a" else "player_a"
    starter = args.pilot_seat if args.pilot_play_order == "play" else other_seat
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    requests = []
    http_messages = []
    request_contexts = []
    attempts = {}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_GET(self):
            # prime-rl's eval waits for /health and checks /v1/models first.
            models = {"data": [{"id": "xmage-scripted-local", "object": "model"}]}
            body = json.dumps(models if self.path == "/v1/models" else {}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            try:
                assert self.path == "/v1/chat/completions", self.path
                payload = json.loads(
                    self.rfile.read(int(self.headers["Content-Length"]))
                )
                # The eval's sampling is authoritative; harness requests always stream.
                assert payload["max_tokens"] == 4096
                assert "max_completion_tokens" not in payload
                assert payload["stream"] is True
                observations = []
                for message in payload["messages"]:
                    if message["role"] != "user":
                        continue
                    content = message["content"]
                    if isinstance(content, list):
                        content = "".join(p.get("text", "") for p in content)
                    try:
                        value = json.loads(content)
                    except ValueError:
                        value = None
                    if isinstance(value, dict) and "error" in value:
                        # Corrections must refer only to the preceding private
                        # observation, never to the other seat's pending choice.
                        assert value["decision"] == observations[-1]["decision"]
                        continue
                    if args.observation_format == "json":
                        obs = value
                    else:
                        # The scripted endpoint isn't an LLM/parser benchmark.
                        # Resolve the decision to its public player transcript,
                        # then verify the actual HTTP text before choosing.
                        header = content.splitlines()[0]
                        number, seat = header.removeprefix("Decision ").split(
                            " | You: "
                        )
                        game = next((output / "games").iterdir())
                        obs = next(
                            o
                            for o in read_lines(game / "players" / f"{seat}.jsonl")
                            if o["decision"] == int(number)
                        )
                        assert content == render_observation(
                            obs,
                            pilot_play_order="play" if seat == starter else "draw",
                            starting_player=starter,
                        )
                    observations.append(obs)
                http_messages.append(
                    [
                        {"role": m["role"], "content": m["content"]}
                        for m in payload["messages"]
                    ]
                )
                actor = observations[-1]["player_id"]
                systems = [m for m in payload["messages"] if m["role"] == "system"]
                assert len(systems) == 1
                context = json.loads(
                    systems[0]["content"].split(DECK_CONTEXT_MARKER, 1)[1]
                )
                assert context["player"] == observations[-1]["player"]
                request_contexts.append(context)
                if not args.no_auto_pass_priority:
                    assert not any(
                        is_pass_only_priority(obs) for obs in observations
                    ), "Automatic priority pass leaked into model history"
                assert all(obs["player_id"] == actor for obs in observations), (
                    "Other seat leaked into model history"
                )
                assert len(observations) <= 4
                requests.append(observations)
                action_json = json.dumps({"action": advance_action(observations[-1])})
                # Exercise instruct, hidden-reasoning, and visible-reasoning replies.
                completion = (
                    action_json,
                    f"```json\n{action_json}\n```",
                    f"I will advance the game.\n<answer>{action_json}</answer>",
                    (
                        f"<think>I will advance the game.</think>\n"
                        f"<answer>```json\n{action_json}\n```</answer>"
                    ),
                )[(len(requests) - 1) % 4]
                decision = observations[-1]["decision"]
                attempts[decision] = attempts.get(decision, 0) + 1
                if args.inject_invalid_replies:
                    number = list(attempts).index(decision)
                    attempt = attempts[decision]
                    if number == 0 and attempt == 1:
                        completion = "not-json"
                    elif (number == 1 and attempt == 1) or number == 2:
                        completion = json.dumps(
                            {"action": len(observations[-1]["actions"])}
                        )
                chunks = [
                    {"delta": {"role": "assistant", "content": completion}},
                    {"delta": {"reasoning_content": "Choose the scripted action."}},
                    {"delta": {}, "finish_reason": "stop"},
                ]
                events = [
                    {"choices": [{"index": 0, "finish_reason": None, **chunk}]}
                    for chunk in chunks
                ] + [
                    {
                        "choices": [],
                        "usage": {
                            "prompt_tokens": 1,
                            "completion_tokens": 1,
                            "total_tokens": 2,
                        },
                    }
                ]
                body = b"".join(
                    b"data: "
                    + json.dumps(
                        {
                            "id": f"local-{len(requests)}",
                            "object": "chat.completion.chunk",
                            "created": int(time.time()),
                            "model": "xmage-scripted-local",
                            **event,
                        }
                    ).encode()
                    + b"\n\n"
                    for event in events
                )
                body += b"data: [DONE]\n\n"
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except (AssertionError, ValueError, KeyError, TypeError, OSError) as exc:
                self.send_error(400, str(exc))

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    taskset_args = {
        "seed": args.seed,
        "pilot_seat": args.pilot_seat,
        "pilot_deck": args.pilot_deck,
        "pilot_play_order": args.pilot_play_order,
    }
    env_args = {
        "output_dir": str(output / "games"),
        "opponent": args.opponent,
        "auto_pass_priority": not args.no_auto_pass_priority,
        "observation_format": args.observation_format,
        "recording_mode": args.recording_mode,
    }
    if args.java_bin:
        env_args["java_bin"] = args.java_bin
    url = f"http://127.0.0.1:{server.server_port}/v1"
    os.environ["XMAGE_LOCAL_API_KEY"] = "local-scripted-smoke"
    try:
        if args.protocol_only:

            async def exercise():
                env = XMageEnv(
                    XMageEnvConfig(
                        taskset={"id": "xmage-poc", **taskset_args}, **env_args
                    )
                )
                ctx = vf.ModelContext(
                    model="xmage-scripted-local",
                    client=vf.EvalClientConfig(
                        base_url=url, api_key_var="XMAGE_LOCAL_API_KEY"
                    ),
                    sampling=vf.SamplingConfig(max_tokens=4096),
                )
                async with env.serving():
                    return await env.run_episode(next(iter(env.taskset)), ctx)

            episode = asyncio.run(exercise()).model_dump(mode="json")
        else:

            def flags(prefix, values):
                return [
                    item
                    for key, value in values.items()
                    for item in (f"--{prefix}{key.replace('_', '-')}", str(value))
                ]

            subprocess.run(
                [
                    "bash",
                    str(ROOT / "scripts/prime_rl_eval.sh"),
                    str(ROOT / "environments/xmage_poc"),
                    "xmage-poc",
                    "-m",
                    "xmage-scripted-local",
                    "--client.base-url",
                    url,
                    "--client.api-key-var",
                    "XMAGE_LOCAL_API_KEY",
                    "-n",
                    "1",
                    "-r",
                    "1",
                    "-c",
                    "1",
                    "--sampling.max-tokens",
                    "4096",
                    *flags("env.taskset.", taskset_args),
                    *flags("env.", env_args),
                    "--env.timeout.episode",
                    "300",
                    "--output-dir",
                    str(output),
                    "--run.name",
                    "eval",
                    "--no-dashboard",
                ],
                cwd=ROOT,
                check=True,
            )
            episode = prime_rl_episode(output / "eval/monitors/file")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
    assert not episode["errors"], episode["errors"]
    traces = episode["traces"]
    seats = {trace["info"]["seat"]: trace for trace in traces}
    assert set(seats) == (
        {"player_a", "player_b"} if args.opponent == "self_play" else {args.pilot_seat}
    )
    for trace in traces:
        data, info = trace["task"]["data"], trace["info"]
        assert not trace["errors"], trace["errors"]
        assert info["recording_audit"]["privacy_passed"]
        assert data["pilot_deck"] == args.pilot_deck
        assert data["pilot_play_order"] == args.pilot_play_order
        assert (data["starting_player"] == args.pilot_seat) == (
            args.pilot_play_order == "play"
        )
        assert info["game_result"]["starting_player"] == data["starting_player"]
        if args.opponent == "self_play":
            assert trace["rewards"]["recording_validity"]["score"] == 1.0
        else:
            outcome = next(
                p
                for p in info["game_result"]["players"]
                if p["name"] == args.pilot_seat
            )
            assert trace["rewards"]["pilot_win"]["score"] == float(outcome["won"])

    def total(metric):
        # Counters are per seat; the injected replies may land on either seat.
        return sum(trace["metrics"][metric] for trace in traces)

    assert total("invalid_action_count") == (5 if args.inject_invalid_replies else 0)
    assert total("unparseable_reply_count") == int(args.inject_invalid_replies)
    assert total("fallback_action_count") == int(args.inject_invalid_replies)
    assert total("model_action_attempts") == len(requests)
    games = list((output / "games").iterdir())
    assert len(games) == 1
    audit = verify(games[0])
    assert http_messages == [
        p["messages"] for p in read_lines(games[0] / "model-prompts.jsonl")
    ], "Recorded prompts differ from actual HTTP model inputs"
    decisions = read_lines(games[0] / "internal/decisions.jsonl")
    if args.opponent != "self_play":
        decisions = [
            d for d in decisions if d["observation"]["player"] == args.pilot_seat
        ]
    automatic = (
        [d for d in decisions if is_pass_only_priority(d["observation"])]
        if not args.no_auto_pass_priority
        else []
    )
    automatic_path = games[0] / "automatic-priority.jsonl"
    automatic_log = read_lines(automatic_path) if automatic_path.exists() else []
    assert automatic_log == [
        {
            "decision": d["decision"],
            "player": d["observation"]["player"],
            "action": d["selected"]["index"],
        }
        for d in automatic
    ], "Automatic passes differ from recorded engine decisions"
    if not args.no_auto_pass_priority:
        decisions = [
            d for d in decisions if not is_pass_only_priority(d["observation"])
        ]
    assert len(requests) == len(decisions) + (4 if args.inject_invalid_replies else 0)
    by_decision = {}
    for request, context in zip(requests, request_contexts, strict=True):
        by_decision.setdefault(request[-1]["decision"], []).append((request, context))
    assert list(by_decision) == [d["decision"] for d in decisions], (
        "CLI did not drive every model decision in the same game"
    )
    if args.inject_invalid_replies:
        assert list(attempts.values())[:3] == [2, 2, 3]
        obs = decisions[2]["observation"]
        expected = next(
            (
                a["index"]
                for kind in ("pass", "no", "cancel")
                for a in obs["actions"]
                if a["kind"] == kind
            ),
            obs["actions"][0]["index"],
        )
        assert decisions[2]["response"]["action"] == expected
    histories = {}
    for decision in decisions:
        obs = decision["observation"]
        history = histories.setdefault(obs["player_id"], [])
        history.append(obs)
        for request, context in by_decision[obs["decision"]]:
            assert request == history[-4:], (
                "HTTP inputs differ from their seat's engine observations"
            )
            seat = obs["player"]
            assert context == json.loads(
                (games[0] / "players" / f"{seat}.context.json").read_text()
            ), "Endpoint received a different seat's deck or a modified deck context"
    audit["endpoint_requests"] = len(requests)
    audit["auto_passed_priority"] = len(automatic)
    audit["model_history_isolation_passed"] = True
    audit["own_deck_context_passed"] = True
    if args.inject_invalid_replies:
        audit["invalid_reply_recovery_passed"] = True
    audit["driver"] = "protocol_test" if args.protocol_only else "prime_rl_eval"
    audit["opponent"] = args.opponent
    audit["pilot_seat"] = args.pilot_seat if args.opponent != "self_play" else None
    audit["pilot_deck"] = args.pilot_deck
    audit["pilot_play_order"] = args.pilot_play_order
    (output / "audit.json").write_text(json.dumps(audit, indent=2) + "\n")
    print(json.dumps(audit, indent=2))


if __name__ == "__main__":
    main()
