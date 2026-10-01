import asyncio
import copy
import json
import threading
import time

import pytest
from pydantic import ValidationError

from codex_harness_connect.waiting import MAX_WAIT_BYTES, WaitTarget, wait_for_sessions

SID = "a" * 32
OTHER = "b" * 32


def status(sid=SID, after=0, *, lifecycle="running", cursor=None, truncated=False):
    return {
        "session": {"session_id": sid, "status": lifecycle, "semantic_status": "unknown",
                    "native_session_id": "native-conversation", "worker_pid": 12,
                    "worker_start": "darwin:123:456", "child_pid": 13,
                    "child_start": "darwin:123:789", "full_process_containment_verified": False},
        "events": [] if cursor is None else [{"cursor": cursor, "session_id": sid,
                                              "data": {"text": "secret raw output"}}],
        "next_cursor": after if cursor is None else cursor,
        "earliest_cursor": cursor, "truncated": truncated,
    }


def run(reader, after=0, timeout=0, targets=None):
    return asyncio.run(wait_for_sessions(targets or [WaitTarget(session_id=SID, after=after)],
                                         reader, timeout))


def test_immediate_snapshot_preserves_native_os_identity_and_acceptance():
    calls = []

    def read(sid, after, limit):
        calls.append((sid, after, limit))
        return status(sid, after)

    result = run(read, after=9)
    assert result["reason"] == "snapshot"
    assert not result["timed_out"]
    summary = result["sessions"][0]
    assert summary["native_session_id"] == "native-conversation"
    assert summary["worker_pid"] == 12
    assert summary["child_start"] == "darwin:123:789"
    assert summary["full_process_containment_verified"] is False
    assert summary["task_acceptance"] == "requires-parent-verification"
    assert summary["after"] == summary["next_cursor"] == 9
    assert calls == [(SID, 9, 1)]


def test_idle_timeout_is_bounded_and_does_not_busy_spin():
    calls = []

    def read(sid, after, limit):
        calls.append(limit)
        return status(sid, after)

    started = time.monotonic()
    result = run(read, timeout=0.055)
    elapsed = time.monotonic() - started
    assert result["reason"] == "timeout" and result["timed_out"]
    assert 0.045 <= elapsed < 0.5
    assert calls == [1]
    assert "events" not in result["sessions"][0]


def test_new_event_wakes_and_keeps_unread_cursor():
    async def scenario():
        calls = []
        ready = False
        entered = asyncio.Event()

        async def read(sid, after, limit):
            calls.append((after, limit))
            entered.set()
            return status(sid, after, cursor=15 if ready else None)

        task = asyncio.create_task(wait_for_sessions([WaitTarget(session_id=SID, after=10)],
                                                     read, 1))
        await asyncio.wait_for(entered.wait(), timeout=5)
        ready = True
        result = await task
        assert result["reason"] == "changes"
        summary = result["sessions"][0]
        assert summary["after"] == summary["next_cursor"] == 10
        assert summary["first_pending_cursor"] == 15 and summary["changes_available"]
        assert len(calls) >= 2 and all(call == (10, 1) for call in calls)

    asyncio.run(scenario())


@pytest.mark.parametrize("lifecycle", ["completed", "failed", "cancelled", "timed_out", "lost"])
def test_all_terminal_states_wake_without_claiming_task_acceptance(lifecycle):
    result = run(lambda sid, after, limit: status(sid, after, lifecycle=lifecycle), timeout=30)
    assert result["reason"] == "terminal"
    assert result["sessions"][0]["terminal"]
    assert result["sessions"][0]["semantic_status"] == "unknown"
    assert result["sessions"][0]["task_acceptance"] == "requires-parent-verification"


def test_retention_gap_takes_precedence_and_exposes_first_available_cursor():
    result = run(lambda sid, after, limit: status(sid, after, cursor=101, truncated=True),
                 after=10, timeout=30)
    assert result["reason"] == "retention_gap"
    summary = result["sessions"][0]
    assert summary["truncated"]
    assert summary["earliest_cursor"] == summary["first_pending_cursor"] == 101
    assert summary["next_cursor"] == 10


def test_unknown_status_is_explicit_and_never_fake_complete():
    result = run(lambda sid, after, limit: status(sid, after, lifecycle="invented"), timeout=30)
    assert result["reason"] == "unknown_status"
    assert result["sessions"][0]["status"] == "unknown"
    assert result["sessions"][0]["observed_status"] == "invented"
    assert not result["sessions"][0]["terminal"]


@pytest.mark.parametrize("exc", [KeyError("outside profile"), PermissionError("secret"),
                                  RuntimeError("noisy private stderr"), OSError("disk"),
                                  ValueError("private callback payload must not escape")])
def test_reader_failure_is_per_target_bounded_and_does_not_leak_exception(exc):
    def read(sid, after, limit):
        if sid == SID:
            raise exc
        return status(sid, after)

    result = run(read, targets=[WaitTarget(session_id=SID), WaitTarget(session_id=OTHER)])
    assert result["reason"] == "error"
    assert result["sessions"][0]["status"] == "unknown"
    assert result["sessions"][1]["status"] == "running"
    assert str(exc) not in json.dumps(result)


def test_session_error_text_is_not_exported_in_compact_summary():
    sentinel = "SYNTHETIC_PRIVATE_ERROR_PAYLOAD"

    def read(sid, after, limit):
        value = status(sid, after, lifecycle="failed")
        value["session"]["error"] = sentinel
        return value

    result = run(read)
    assert result["reason"] == "terminal"
    assert result["sessions"][0]["session_error_present"] is True
    assert sentinel not in json.dumps(result)


@pytest.mark.parametrize("mutate", [
    lambda r: r.update(session=None),
    lambda r: r["session"].update(session_id=OTHER),
    lambda r: r["session"].update(status=None),
    lambda r: r.update(events={}),
    lambda r: r.update(events=[{}, {}]),
    lambda r: r.update(truncated=1),
    lambda r: r.update(earliest_cursor=True),
    lambda r: r.update(events=[{"cursor": True}]),
    lambda r: r.update(events=[{"cursor": 0}]),
    lambda r: r.update(events=[{"cursor": 1, "session_id": OTHER}], next_cursor=1),
    lambda r: r.update(events=[{"cursor": 1}], next_cursor=2),
    lambda r: r.update(next_cursor=False),
])
def test_malformed_or_cross_scope_status_fails_closed(mutate):
    def read(sid, after, limit):
        result = status(sid, after)
        mutate(result)
        return result

    result = run(read)
    assert result["reason"] == "error"
    assert result["sessions"][0]["error"]["code"] == "invalid_status"


@pytest.mark.parametrize("session_id", ["A" * 32, "a" * 31, "a" * 33, "g" * 32, 12, True])
def test_target_id_validation_is_exact(session_id):
    with pytest.raises(ValidationError):
        WaitTarget(session_id=session_id)


@pytest.mark.parametrize("after", [True, False, -1, 1.0, "1", None, 2**63,
                                  pytest.param(10**10000, id="huge")])
def test_target_after_is_strict_nonnegative_integer(after):
    with pytest.raises(ValidationError):
        WaitTarget(session_id=SID, after=after)


@pytest.mark.parametrize("timeout", [True, False, -0.1, 45.1, float("nan"), float("inf"),
                                      -float("inf"), "0", None,
                                      pytest.param(10**10000, id="huge")])
def test_timeout_rejects_bool_coercion_nonfinite_and_range(timeout):
    called = []
    with pytest.raises(ValueError, match="timeout_seconds"):
        run(lambda *args: called.append(args), timeout=timeout)
    assert called == []


@pytest.mark.parametrize("targets", [[], [WaitTarget(session_id=SID)] * 2,
                                      [WaitTarget(session_id=f"{i:032x}") for i in range(9)],
                                      [{"session_id": SID}], (WaitTarget(session_id=SID),)])
def test_target_count_duplicate_and_type_validation(targets):
    with pytest.raises(ValueError):
        asyncio.run(wait_for_sessions(targets, lambda *args: None, 0))


def test_late_events_are_not_skipped_and_independent_readers_share_cursor():
    async def scenario():
        events = [11]
        calls = []

        def read(sid, after, limit):
            calls.append((after, limit))
            return status(sid, after, cursor=next((c for c in events if c > after), None))

        target = WaitTarget(session_id=SID, after=10)
        first, second = await asyncio.gather(wait_for_sessions([target], read, 0),
                                             wait_for_sessions([target], read, 0))
        events.append(12)
        again = await wait_for_sessions([target], read, 0)
        assert first["sessions"][0] == second["sessions"][0] == again["sessions"][0]
        assert again["sessions"][0]["first_pending_cursor"] == 11
        drained = await wait_for_sessions([WaitTarget(session_id=SID, after=11)], read, 0)
        assert drained["sessions"][0]["first_pending_cursor"] == 12
        assert calls == [(10, 1)] * 3 + [(11, 1)]

    asyncio.run(scenario())


@pytest.mark.parametrize("noise", ["🌍漢字", "\x00", "\ud800"])
def test_noisy_unicode_is_bounded_and_raw_payload_members_and_final_text_are_absent(noise):
    payload = noise * 100_000

    def read(sid, after, limit):
        result = status(sid, after, cursor=1)
        for key in ("native_session_id", "worker_start", "child_start", "termination_scope", "error",
                    "status"):
            result["session"][key] = payload
        result["session"]["process_members"] = {str(i): payload for i in range(100)}
        result["session"]["stderr"] = payload
        result["session"]["final_text"] = payload
        result["events"][0]["data"] = {"raw_unique_secret": payload}
        return result

    targets = [WaitTarget(session_id=f"{i:032x}") for i in range(8)]
    result = run(read, targets=targets)
    encoded = json.dumps(result, ensure_ascii=True).encode()
    assert len(encoded) <= MAX_WAIT_BYTES
    assert len(json.dumps(result, ensure_ascii=False).encode()) <= MAX_WAIT_BYTES
    assert all(key not in encoded.decode() for key in
               ("process_members", "stderr", "final_text", "raw_unique_secret", "events"))
    assert len(result["sessions"]) == 8
    assert all(s["summary_truncated"] for s in result["sessions"])


def test_wait_cancellation_only_cancels_observation_and_leaves_reader_state_unchanged():
    async def scenario():
        snapshot = status()
        original = copy.deepcopy(snapshot)
        calls = []
        entered = asyncio.Event()

        async def read(sid, after, limit):
            calls.append((sid, after, limit))
            entered.set()
            await asyncio.Event().wait()
            return snapshot

        waiting = asyncio.create_task(wait_for_sessions([WaitTarget(session_id=SID)], read, 30))
        await asyncio.wait_for(entered.wait(), timeout=5)
        waiting.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiting
        assert snapshot == original
        assert calls == [(SID, 0, 1)]

    asyncio.run(scenario())


def test_slow_async_reader_obeys_deadline_and_is_cancelled():
    async def scenario():
        stopped = asyncio.Event()

        async def read(sid, after, limit):
            try:
                await asyncio.sleep(10)
            finally:
                stopped.set()

        started = time.monotonic()
        result = await wait_for_sessions([WaitTarget(session_id=SID)], read, 0.025)
        assert time.monotonic() - started < 0.2
        assert result["reason"] == "error"
        assert result["sessions"][0]["error"]["code"] == "read_timeout"
        assert stopped.is_set()

    asyncio.run(scenario())


def test_sync_reader_does_not_block_event_loop():
    async def scenario():
        entered = threading.Event()
        release = threading.Event()

        def read(sid, after, limit):
            entered.set()
            assert release.wait(5), "Event loop could not release the synchronous reader"
            return status(sid, after)

        task = asyncio.create_task(wait_for_sessions([WaitTarget(session_id=SID)], read, 0))
        try:
            assert await asyncio.to_thread(entered.wait, 1)
            assert not task.done()
        finally:
            release.set()
        assert (await task)["reason"] == "snapshot"

    asyncio.run(scenario())


def test_later_read_timeout_does_not_reuse_stale_success_as_an_error():
    async def scenario():
        calls = 0

        async def read(sid, after, limit):
            nonlocal calls
            calls += 1
            if calls > 1:
                await asyncio.sleep(10)
            return status(sid, after)

        result = await wait_for_sessions([WaitTarget(session_id=SID)], read, 0.25)
        assert result["reason"] == "error"
        assert result["sessions"][0]["error"]["code"] == "read_timeout"
        assert result["sessions"][0]["status"] == "unknown"

    asyncio.run(scenario())
