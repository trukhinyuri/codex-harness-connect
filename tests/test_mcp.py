import asyncio
import json
import os
import sys
import threading
from pathlib import Path

import pytest
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


def test_stdio_wait_two_readers_reconnect_and_cancel_observation_only(tmp_path):
    async def check():
        state = tmp_path / "state"
        service = SessionService(state / "claude")
        params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "codex_harness_connect", "serve", "--state-root", str(state)],
            env={**os.environ, "PYTHONPATH": str(Path(__file__).parents[1] / "src")},
        )
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as client:
                await client.initialize()
                tools = {tool.name: tool for tool in (await client.list_tools()).tools}
                assert tools["wait_sessions"].annotations.readOnlyHint is True
                job = service.start(
                    [sys.executable, "-u", "-c", "import sys; sys.stdin.readline(); print('WAIT_REAL_MCP')"],
                    str(tmp_path), timeout_seconds=20,
                )
                sid = job["session_id"]
                try:
                    # Drain startup before waiting for any new output. The native child is idle.
                    initial = service.status(sid)
                    startup_deadline = asyncio.get_running_loop().time() + 5
                    while initial["session"]["status"] == "starting":
                        assert asyncio.get_running_loop().time() < startup_deadline
                        await asyncio.sleep(0.01)
                        initial = service.status(sid)
                    cursor = initial["next_cursor"]
                    args = {"targets": [{"session_id": sid, "after": cursor}], "timeout_seconds": 0.05}
                    idle = await client.call_tool("wait_sessions", args)
                    assert not idle.isError
                    assert json.loads(idle.content[0].text)["reason"] == "timeout"
                    waiting = asyncio.create_task(client.call_tool("wait_sessions", {
                        **args, "timeout_seconds": 10,
                    }))
                    await asyncio.sleep(0.03)
                    waiting.cancel()
                    with pytest.raises(asyncio.CancelledError):
                        await waiting
                    await asyncio.sleep(0.03)
                    assert service.status(sid)["session"]["status"] == "running"
                    assert service.status(sid)["session"]["worker_alive"]
                    sent = await client.call_tool("send_input", {"session_id": sid, "text": "go\n"})
                    assert not sent.isError
                    async with stdio_client(params) as (other_read, other_write):
                        async with ClientSession(other_read, other_write) as other:
                            await other.initialize()
                            replies = await asyncio.gather(
                                client.call_tool("wait_sessions", {**args, "timeout_seconds": 5}),
                                other.call_tool("wait_sessions", {**args, "timeout_seconds": 5}),
                            )
                            values = [json.loads(reply.content[0].text) for reply in replies]
                            assert all(not reply.isError for reply in replies)
                            assert all(v["sessions"][0]["next_cursor"] == cursor for v in values)
                            assert values[0]["sessions"][0]["first_pending_cursor"] == (
                                values[1]["sessions"][0]["first_pending_cursor"])
                            # Waiting, including a new MCP connection, has not consumed events.
                            drained = await other.call_tool("session_events", {"session_id": sid, "after": cursor})
                            data = json.loads(drained.content[0].text)
                            # The first unread event may be input_sent before child stdout arrives.
                            events = list(data["events"])
                            output_deadline = asyncio.get_running_loop().time() + 5
                            while not any("WAIT_REAL_MCP" in str(event["data"]) for event in events):
                                assert asyncio.get_running_loop().time() < output_deadline
                                drained_cursor = data["next_cursor"]
                                await other.call_tool("wait_sessions", {
                                    "targets": [{"session_id": sid, "after": drained_cursor}],
                                    "timeout_seconds": 0.1,
                                })
                                drained = await other.call_tool("session_events", {
                                    "session_id": sid, "after": drained_cursor,
                                })
                                data = json.loads(drained.content[0].text)
                                events.extend(data["events"])
                            malformed = await other.call_tool("wait_sessions", {**args, "timeout_seconds": True})
                            assert malformed.isError
                finally:
                    service.cancel(sid)
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
                hidden_wait = await session.call_tool("wait_sessions", {
                    "targets": [{"session_id": job["session_id"], "after": 0}],
                    "timeout_seconds": 0,
                })
                assert hidden_wait.isError is False
                hidden = json.loads(hidden_wait.content[0].text)
                assert hidden["reason"] == "error"
                assert hidden["sessions"][0]["error"]["code"] == "unavailable"
                for tool in ("session_events", "cancel_session", "close_input", "send_input"):
                    args = {"session_id": job["session_id"]}
                    if tool == "send_input":
                        args["text"] = "should not be delivered"
                    result = await session.call_tool(tool, args)
                    assert result.isError is True
    asyncio.run(check())


def test_wait_owner_lookup_is_inside_deadline_and_does_not_block_cancellation(tmp_path, monkeypatch):
    from codex_harness_connect import server as server_module

    entered = threading.Event()
    second_entered = threading.Event()
    release = threading.Event()
    calls = []

    class SlowService:
        def __init__(self, state_root):
            pass

        def status(self, session_id, after=0, limit=100):
            calls.append(session_id)
            entered.set()
            if len(calls) >= 2:
                second_entered.set()
            assert release.wait(5), "Test did not release read-only owner lookup"
            raise KeyError(session_id)

    monkeypatch.setattr(server_module, "SessionService", SlowService)
    server = server_module.build_server(tmp_path / "state", profile="claude")

    async def check():
        args = {"targets": [{"session_id": "a" * 32, "after": 0}], "timeout_seconds": 0.05}
        try:
            result = await asyncio.wait_for(server.call_tool("wait_sessions", args), timeout=1)
            assert entered.is_set() and not release.is_set()
            structured = json.loads(result[0].text)
            assert structured["reason"] == "error"
            assert structured["sessions"][0]["error"]["code"] == "read_timeout"
            # The still-blocked owner reader cannot prevent a second request from cancelling.
            waiting = asyncio.create_task(server.call_tool("wait_sessions", {**args, "timeout_seconds": 10}))
            assert await asyncio.to_thread(second_entered.wait, 1)
            waiting.cancel()
            with pytest.raises(asyncio.CancelledError):
                await waiting
        finally:
            release.set()

    asyncio.run(check())
