import asyncio
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
import verifiers.v1 as vf


@pytest.fixture
def stub_bridge_runtime(tmp_path, monkeypatch):
    """Opt-in placeholder for tests that never launch Java; not for integration."""
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    (runtime / "xmage-poc.jar").touch()
    monkeypatch.setattr("xmage_poc.environment.ROOT", tmp_path)


@pytest.fixture
def endpoint():
    """A local streaming chat endpoint: `reply(messages) -> str` answers each request."""
    state = {"reply": None, "requests": []}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_POST(self):
            payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            messages = [
                {"role": m["role"], "content": m["content"]}
                for m in payload["messages"]
            ]
            state["requests"].append(messages)
            try:
                content = state["reply"](messages)
            except Exception as exc:  # noqa: BLE001 - surface test failures on the trace
                self.send_error(400, repr(exc))
                return
            chunks = [
                {"delta": {"role": "assistant", "content": content}},
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
                        "id": "local",
                        "object": "chat.completion.chunk",
                        "created": int(time.time()),
                        "model": "local",
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

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    state["url"] = f"http://127.0.0.1:{server.server_port}/v1"
    yield state
    server.shutdown()
    server.server_close()
    thread.join(timeout=5)


@pytest.fixture
def play(tmp_path, monkeypatch, stub_bridge_runtime, endpoint):
    """Play one episode through Verifiers against a fake engine session.

    `session` replaces GameSession/PilotSession; `reply(messages)` is the model.
    Returns the episode and the messages each model request carried.
    """
    from xmage_poc.environment import XMageEnv, XMageEnvConfig

    monkeypatch.setenv("XMAGE_LOCAL_API_KEY", "local")
    monkeypatch.setattr(
        "xmage_poc.environment.verify", lambda _: {"privacy_passed": True}
    )

    def run(session, reply, *, taskset=None, **config):
        monkeypatch.setattr("xmage_poc.environment.GameSession", session)
        monkeypatch.setattr("xmage_poc.environment.PilotSession", session)
        endpoint["reply"] = reply
        endpoint["requests"].clear()
        env = XMageEnv(
            XMageEnvConfig(
                taskset={"id": "xmage-poc", **(taskset or {})},
                java_bin="/bin/false",
                output_dir=tmp_path / "games",
                **config,
            )
        )
        ctx = vf.ModelContext(
            model="local",
            client=vf.EvalClientConfig(
                base_url=endpoint["url"], api_key_var="XMAGE_LOCAL_API_KEY"
            ),
            sampling=vf.SamplingConfig(max_tokens=64),
        )

        async def episode():
            async with env.serving():
                return await env.run_episode(next(iter(env.taskset)), ctx)

        return asyncio.run(episode()), list(endpoint["requests"])

    return run
