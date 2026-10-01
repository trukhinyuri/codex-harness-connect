import asyncio
import json
import os
import sys
from pathlib import Path

import pytest
from mcp import ClientSession, StdioServerParameters, types
from mcp.client.stdio import stdio_client


@pytest.mark.parametrize(("action", "content", "status", "choice"), [
    ("accept", {"choice": "form_visible"}, "answered", "form_visible"),
    ("accept", {"choice": "form_not_usable"}, "answered", "form_not_usable"),
    ("decline", None, "declined", None),
    ("cancel", None, "cancelled", None),
    ("accept", {}, "invalid_response", None),
])
def test_stdio_form_wire_and_no_native_effects(tmp_path, action, content, status, choice):
    async def check():
        requests = []

        async def answer(ctx, params):
            assert isinstance(params, types.ElicitRequestFormParams)
            schema = params.requestedSchema
            assert schema["required"] == ["choice"]
            assert schema["additionalProperties"] is False
            assert "default" not in schema["properties"]["choice"]
            assert schema["properties"]["choice"]["enum"] == ["form_visible", "form_not_usable"]
            requests.append(ctx.request_id)
            return types.ElicitResult(action=action, content=content)

        state = tmp_path / "state"
        params = StdioServerParameters(command=sys.executable, args=[
            "-m", "codex_harness_connect", "serve", "--state-root", str(state),
        ], env={**os.environ, "PYTHONPATH": str(Path(__file__).parents[1] / "src")})
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write, elicitation_callback=answer) as client:
                await client.initialize()
                tools = {t.name: t for t in (await client.list_tools()).tools}
                assert "ctx" not in tools["check_interaction"].inputSchema["properties"]
                assert tools["check_interaction"].annotations.readOnlyHint is True
                reply = await client.call_tool("check_interaction", {"timeout_seconds": 1.0})
                assert not reply.isError
                result = json.loads(reply.content[0].text)
                assert result["status"] == status and result["choice"] == choice
                assert result["form_advertised"] is True
                assert result["authorizes_native_action"] is False
                assert result["human_attestation_verified"] is False
                assert result["answer_persisted_by_connector"] is False and len(requests) == 1
                history = await client.call_tool("list_sessions", {})
                assert json.loads(history.content[0].text)["sessions"] == []
    asyncio.run(check())


def test_stdio_client_without_form_support_returns_without_prompt(tmp_path):
    async def check():
        params = StdioServerParameters(command=sys.executable, args=[
            "-m", "codex_harness_connect", "serve", "--profile", "claude",
            "--state-root", str(tmp_path / "state"),
        ], env={**os.environ, "PYTHONPATH": str(Path(__file__).parents[1] / "src")})
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as client:
                await client.initialize()
                reply = await client.call_tool("check_interaction", {"timeout_seconds": 0.01})
                assert not reply.isError
                result = json.loads(reply.content[0].text)
                assert result["status"] == "unsupported" and not result["form_advertised"]
                assert result["choice"] is None and not result["authorizes_native_action"]
                invalid = await client.call_tool("check_interaction", {"timeout_seconds": True})
                assert invalid.isError
    asyncio.run(check())
