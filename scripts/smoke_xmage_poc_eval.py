"""Exercise prime eval run using a local scripted endpoint; no paid model calls."""

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

import verifiers as vf
from xmage_poc import load_environment
from xmage_poc.environment import DECK_CONTEXT_MARKER
from xmage_poc.transport import advance_action, is_pass_only_priority
from xmage_poc.verify import read_lines, verify

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--java-bin", default=os.environ.get("XMAGE_JAVA_BIN"))
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument(
        "--opponent", choices=["self_play", "scripted"], default="self_play"
    )
    parser.add_argument(
        "--pilot-seat", choices=["player_a", "player_b"], default="player_a"
    )
    parser.add_argument(
        "--no-auto-pass-priority",
        action="store_true",
        help="Send pass-only priority prompts to the endpoint too",
    )
    parser.add_argument(
        "--protocol-only",
        action="store_true",
        help="Test the adapter/HTTP boundary locally; not a Prime evaluation",
    )
    parser.add_argument(
        "--inject-invalid-replies",
        action="store_true",
        help="Exercise parse recovery, index recovery, and exhausted-attempt fallback",
    )
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    requests = []
    request_contexts = []
    attempts = {}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_POST(self):
            try:
                assert self.path == "/v1/chat/completions", self.path
                payload = json.loads(
                    self.rfile.read(int(self.headers["Content-Length"]))
                )
                observations = []
                for message in payload["messages"]:
                    if message["role"] != "user":
                        continue
                    content = message["content"]
                    if isinstance(content, list):
                        content = "".join(p.get("text", "") for p in content)
                    value = json.loads(content)
                    if "actions" in value:
                        observations.append(value)
                    else:
                        # Corrections must refer only to the preceding private
                        # observation, never to the other seat's pending choice.
                        assert "error" in value
                        assert value["decision"] == observations[-1]["decision"]
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
                completion = json.dumps({"action": advance_action(observations[-1])})
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
                body = json.dumps(
                    {
                        "id": f"local-{len(requests)}",
                        "object": "chat.completion",
                        "created": int(time.time()),
                        "model": "xmage-scripted-local",
                        "choices": [
                            {
                                "index": 0,
                                "message": {"role": "assistant", "content": completion},
                                "finish_reason": "stop",
                            }
                        ],
                        "usage": {
                            "prompt_tokens": 1,
                            "completion_tokens": 1,
                            "total_tokens": 2,
                        },
                    }
                ).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except (AssertionError, ValueError, KeyError, TypeError, OSError) as exc:
                self.send_error(400, str(exc))

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    env_args = {
        "output_dir": str(output / "games"),
        "seed": args.seed,
        "opponent": args.opponent,
        "pilot_seat": args.pilot_seat,
        "auto_pass_priority": not args.no_auto_pass_priority,
    }
    if args.java_bin:
        env_args["java_bin"] = args.java_bin
    try:
        if args.protocol_only:

            async def exercise_adapter():
                environment = load_environment(**env_args)
                client = vf.ClientConfig(
                    api_base_url=f"http://127.0.0.1:{server.server_port}/v1",
                    api_key_var="XMAGE_LOCAL_API_KEY",
                    max_retries=0,
                )
                state = await environment.rollout(
                    environment.dataset[0],
                    client,
                    "xmage-scripted-local",
                    {"max_tokens": 32},
                )
                assert state.get("error") is None, state.get("error")
                assert state.get("recording_audit", {}).get("privacy_passed")
                await environment.rubric.score_rollout(state)
                assert state["invalid_action_count"] == (
                    5 if args.inject_invalid_replies else 0
                )
                assert state["unparseable_reply_count"] == int(
                    args.inject_invalid_replies
                )
                assert state["fallback_action_count"] == int(
                    args.inject_invalid_replies
                )
                assert state["model_action_attempts"] == len(requests)
                if args.opponent == "self_play":
                    assert state["reward"] == 1.0
                else:
                    outcome = next(
                        p
                        for p in state["game_result"]["players"]
                        if p["name"] == args.pilot_seat
                    )
                    assert state["reward"] == float(outcome["won"])

            os.environ["XMAGE_LOCAL_API_KEY"] = "local-scripted-smoke"
            asyncio.run(exercise_adapter())
        else:
            # Explicit localhost URL overrides the registry alias's default port.
            subprocess.run(
                [
                    "prime",
                    "eval",
                    "run",
                    "xmage-poc",
                    "-e",
                    "configs/endpoints.toml",
                    "-m",
                    "xmage-scripted-local",
                    "-b",
                    f"http://127.0.0.1:{server.server_port}/v1",
                    "-k",
                    "XMAGE_LOCAL_API_KEY",
                    "-n",
                    "1",
                    "-r",
                    "1",
                    "-c",
                    "1",
                    "-t",
                    "32",
                    "-a",
                    json.dumps(env_args),
                    "-o",
                    str(output / "eval"),
                    "--disable-env-server",
                    "--disable-tui",
                    "-A",
                    "--timeout",
                    "300",
                ],
                cwd=ROOT,
                env={**os.environ, "XMAGE_LOCAL_API_KEY": "local-scripted-smoke"},
                check=True,
            )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
    games = list((output / "games").iterdir())
    assert len(games) == 1
    audit = verify(games[0])
    decisions = read_lines(games[0] / "internal/decisions.jsonl")
    if args.opponent == "scripted":
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
    audit["driver"] = "protocol_test" if args.protocol_only else "prime_eval"
    audit["opponent"] = args.opponent
    audit["pilot_seat"] = args.pilot_seat if args.opponent == "scripted" else None
    (output / "audit.json").write_text(json.dumps(audit, indent=2) + "\n")
    print(json.dumps(audit, indent=2))


if __name__ == "__main__":
    main()
