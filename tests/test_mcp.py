import asyncio
import json
import os
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from codex_harness_connect.sessions import SessionService


def test_real_stdio_mcp_handshake_schema_and_policy_error(tmp_path):
    async def check():
        params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "codex_harness_connect", "serve", "--state-root", str(tmp_path / "state")],
            env={**os.environ, "PYTHONPATH": str(Path(__file__).parents[1] / "src")},
        )
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                init = await session.initialize()
                assert init.serverInfo.name == "codex-harness-connect"
                tools = {tool.name: tool for tool in (await session.list_tools()).tools}
                assert {"start_session", "cancel_session", "session_events", "inventory_cli",
                        "revalidate_cli"} <= tools.keys()
                assert tools["start_session"].annotations.readOnlyHint is False
                assert tools["session_events"].annotations.readOnlyHint is True
                assert tools["inventory_candidate"].annotations.readOnlyHint is False
                assert tools["revalidate_cli"].annotations.readOnlyHint is False
                adapter = await session.call_tool("describe_adapter", {"adapter": "agy"})
                assert adapter.isError is False
                assert "vendor-confirmation-required" in str(adapter.content)
                blocked = await session.call_tool("start_session", {
                    "adapter": "agy", "prompt": "must not execute", "cwd": str(tmp_path),
                    "expected_sha256": "bogus", "mode": "batch",
                    "request_id": "0" * 32,
                })
                assert blocked.isError is True
                jobs = await session.call_tool("list_sessions", {})
                assert jobs.isError is False
                invalid = await session.call_tool("cancel_session", {"session_id": "../../invalid"})
                assert invalid.isError is True
    asyncio.run(check())


def test_scoped_profile_cannot_read_or_control_other_adapter(tmp_path):
    state = tmp_path / "state"
    service = SessionService(state / "claude")
    job = service.start([sys.executable, "-c", "print('synthetic other profile')"], str(tmp_path))

    async def check():
        params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "codex_harness_connect", "serve", "--profile", "agy",
                  "--state-root", str(state)],
            env={**os.environ, "PYTHONPATH": str(Path(__file__).parents[1] / "src")},
        )
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools = {tool.name for tool in (await session.list_tools()).tools}
                assert "inventory_candidate" not in tools
                invalid_observation = await session.call_tool("revalidate_cli", {"adapter": "claude"})
                assert invalid_observation.isError is True
                assert not (state / "revalidation").exists()
                result = await session.call_tool("list_sessions", {})
                assert result.isError is False
                assert json.loads(result.content[0].text) == {"sessions": []}
                for tool in ("session_events", "cancel_session", "close_input", "send_input"):
                    args = {"session_id": job["session_id"]}
                    if tool == "send_input":
                        args["text"] = "should not be delivered"
                    result = await session.call_tool(tool, args)
                    assert result.isError is True
    asyncio.run(check())
