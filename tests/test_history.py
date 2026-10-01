import asyncio
import json
import subprocess

import pytest
from mcp.server.fastmcp.exceptions import ToolError

from codex_harness_connect.history import HISTORY_ORDER, MAX_HISTORY_BYTES, list_history


def job(number, **fields):
    return {"session_id": f"{number:032x}", "created_at": number, "status": "completed",
            "request_id": f"{number + 100:032x}", "native_session_id": None,
            "semantic_status": "unknown", "history_truncated": False, **fields}


class Pool:
    def __init__(self, jobs):
        self.jobs = sorted(jobs, key=lambda item: (item["created_at"], item["session_id"]),
                           reverse=True)
        self.calls = []

    def list_page(self, limit=20, before_session_id=None):
        self.calls.append((limit, before_session_id))
        assert 1 <= limit <= 50
        start = 0
        if before_session_id is not None:
            matches = [i for i, item in enumerate(self.jobs)
                       if item["session_id"] == before_session_id]
            if not matches:
                raise KeyError("private path /sensitive/store.sqlite")
            start = matches[0] + 1
        selected = self.jobs[start:start + limit]
        more = start + limit < len(self.jobs)
        return {"sessions": selected, "has_more": more,
                "next_cursor": selected[-1]["session_id"] if more and selected else None}


def test_default_adapter_order_pages_without_duplicates_or_boundary_skips(monkeypatch):
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: pytest.fail("History launched a process"))
    pools = {"grok": Pool([job(9), job(8)]), "claude": Pool([job(2), job(3)]),
             "agy": Pool([]), "claude-glm": Pool([job(1)])}
    cursor = None
    seen = []
    while True:
        page = list_history(pools, limit=2, cursor=cursor)
        assert page["order"] == HISTORY_ORDER
        seen.extend((item["adapter"], item["session_id"]) for item in page["sessions"])
        assert len(page["sessions"]) <= 2
        if not page["has_more"]:
            assert page["next_cursor"] is None
            break
        assert page["next_cursor"] != cursor
        cursor = page["next_cursor"]
    assert seen == [("claude", f"{3:032x}"), ("claude", f"{2:032x}"),
                    ("claude-glm", f"{1:032x}"), ("grok", f"{9:032x}"),
                    ("grok", f"{8:032x}")]
    assert len(set(seen)) == len(seen)
    assert pools["claude"].calls[0] == (2, None)
    assert pools["claude-glm"].calls[0] == (1, None)


def test_single_adapter_and_equal_timestamp_order():
    pools = {"claude": Pool([job(2, created_at=0), job(1, created_at=0)]),
             "grok": Pool([job(3)])}
    first = list_history(pools, adapter="claude", limit=1)
    assert first["next_cursor"] == f"claude:{2:032x}"
    second = list_history(pools, adapter="claude", cursor=first["next_cursor"])
    assert [item["session_id"] for item in second["sessions"]] == [f"{1:032x}"]
    assert not second["has_more"]
    assert not pools["grok"].calls


@pytest.mark.parametrize("limit", [True, False, 0, -1, 51, "2", 2.0, None])
def test_limit_is_strict(limit):
    pool = Pool([])
    with pytest.raises(ValueError, match="History limit"):
        list_history({"claude": pool}, limit=limit)
    assert not pool.calls


@pytest.mark.parametrize("cursor", [True, 2, "", "claude:" + "A" * 32,
                                     "claude:" + "1" * 31, "../claude:" + "1" * 32,
                                     "a" * 10000])
def test_cursor_is_strict_and_bounded(cursor):
    pool = Pool([])
    with pytest.raises(ValueError, match="Invalid history cursor"):
        list_history({"claude": pool}, cursor=cursor)
    assert not pool.calls


def test_scope_and_missing_cursor_errors_hide_private_details():
    pools = {"claude": Pool([job(1)]), "grok": Pool([job(2)])}
    for args in ({"adapter": "agy"}, {"adapter": True},
                 {"adapter": "grok", "cursor": f"claude:{1:032x}"}):
        with pytest.raises(ValueError, match="scope"):
            list_history(pools, **args)
    with pytest.raises(ValueError) as error:
        list_history(pools, cursor=f"claude:{3:032x}")
    assert str(error.value) == "Session history is unavailable"
    scoped = {"grok": pools["grok"]}
    with pytest.raises(ValueError, match="scope"):
        list_history(scoped, cursor=f"claude:{1:032x}")


def test_complete_response_byte_bound_and_allowlist_preserve_pagination():
    # Escaped characters exercise the bytes actually sent, not character counts.
    pool = Pool([job(i, status="\0" * 2500, cwd="private workspace", error="private error",
                     process_members={"secret": "identity"}) for i in range(1, 51)])
    seen = []
    cursor = None
    while True:
        page = list_history({"claude": pool}, limit=50, cursor=cursor)
        assert len(json.dumps(page, indent=2).encode()) <= MAX_HISTORY_BYTES
        for item in page["sessions"]:
            assert not {"cwd", "error", "process_members"} & item.keys()
        seen.extend(item["session_id"] for item in page["sessions"])
        if not page["has_more"]:
            break
        cursor = page["next_cursor"]
    assert seen == [f"{i:032x}" for i in range(50, 0, -1)]


def test_oversized_first_summary_rejects_without_skipping():
    with pytest.raises(ValueError, match="Session history is unavailable"):
        list_history({"claude": Pool([job(1, status="\0" * MAX_HISTORY_BYTES)])})


def test_empty_noargs_has_explicit_continuation_metadata():
    assert list_history({"claude": Pool([])}) == {
        "sessions": [], "next_cursor": None, "has_more": False, "order": HISTORY_ORDER}


def test_public_server_empty_call_and_strict_parameters(tmp_path, monkeypatch):
    from codex_harness_connect import server as server_module

    class Service(Pool):
        def __init__(self, path):
            super().__init__([])

    monkeypatch.setattr(server_module, "SessionService", Service)
    server = server_module.build_server(tmp_path, profile="claude")

    async def check():
        result = await server.call_tool("list_sessions", {})
        assert json.loads(result[0].text) == list_history({"claude": Pool([])})
        for args in ({"limit": True}, {"limit": "2"}, {"cursor": True},
                     {"adapter": True}, {"adapter": "grok"},
                     {"cursor": f"grok:{1:032x}"}):
            with pytest.raises(ToolError):
                await server.call_tool("list_sessions", args)

    asyncio.run(check())


def test_public_mcp_text_content_respects_serialized_byte_bound(tmp_path, monkeypatch):
    from codex_harness_connect import server as server_module

    class Service(Pool):
        def __init__(self, path):
            super().__init__([job(i, status="\0" * 2500) for i in range(1, 51)])

    monkeypatch.setattr(server_module, "SessionService", Service)
    server = server_module.build_server(tmp_path, profile="claude")

    async def check():
        result = await server.call_tool("list_sessions", {"limit": 50})
        assert len(result[0].text.encode()) <= MAX_HISTORY_BYTES
        page = json.loads(result[0].text)
        assert page["has_more"] and page["next_cursor"]

    asyncio.run(check())
