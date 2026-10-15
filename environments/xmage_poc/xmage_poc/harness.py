"""One model call per segment, on exactly the messages the env supplies."""

from __future__ import annotations

import traceback

from openai import APIError, AsyncOpenAI
from verifiers.v1.dialects.chat import message_to_wire
from verifiers.v1.harnesses.null import NullHarness
from verifiers.v1.runtimes import ProgramResult


class XMageHarness(NullHarness):
    """The tool-less `null` chat loop, minus its replay and its per-segment program.

    The default resume replays the accumulated conversation plus the new turn. XMage
    rebuilds each seat's whole prompt per decision (trimmed history, a system glossary
    that grows, private corrections), so every model call must be exactly the audited
    prompt the env recorded in `model-prompts.jsonl`.

    A game makes hundreds of calls, so the call runs in-process instead of launching
    the chat program for each one; it still goes through the rollout's interception
    endpoint, which records the trace.
    """

    async def setup(self, runtime) -> None:
        pass

    async def launch(
        self,
        ctx,
        trace,
        runtime,
        endpoint,
        secret,
        mcp_urls,
        data,
        tool_interception_url=None,
    ) -> ProgramResult:
        if mcp_urls:
            raise ValueError("The xmage-poc harness does not offer tools")
        system, prompt = self.resolve_prompt(data)
        if isinstance(prompt, str):
            messages = [{"role": "user", "content": prompt}]
        else:
            messages = [message_to_wire(message) for message in prompt or []]
        if system:
            messages.insert(0, {"role": "system", "content": system})
        try:
            async with AsyncOpenAI(base_url=endpoint, api_key=secret) as client:
                stream = await client.chat.completions.create(
                    model=ctx.model,
                    messages=messages,
                    stream=True,
                    stream_options={"include_usage": True},
                )
                async for _ in stream:
                    pass
        except APIError:
            # Exit like the chat program would; the rollout reads the cause from
            # the interception record or the stop condition.
            return ProgramResult(exit_code=1, stdout="", stderr=traceback.format_exc())
        return ProgramResult(exit_code=0, stdout="", stderr="")

    async def resume(
        self,
        ctx,
        trace,
        runtime,
        endpoint,
        secret,
        mcp_urls,
        data,
        messages,
        tool_interception_url=None,
    ) -> ProgramResult:
        return await self.launch(
            ctx,
            trace,
            runtime,
            endpoint,
            secret,
            mcp_urls,
            data.model_copy(update={"prompt": list(messages), "system_prompt": None}),
        )
