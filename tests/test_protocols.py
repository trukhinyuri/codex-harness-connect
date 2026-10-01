"""Documented wire-shape fixtures, not transcripts from a live model run.

Sources: https://code.claude.com/docs/en/headless#read-session-metadata,
https://code.claude.com/docs/en/agent-sdk/streaming-output,
https://github.com/anthropics/claude-agent-sdk-python/blob/main/src/claude_agent_sdk/types.py
Metadata/content values are synthetic; the shape matches official init/result types.
"""

import json

import pytest

from codex_harness_connect.protocols import MAX_ERRORS, MAX_PREVIEW_CHARS, ClaudeStreamParser

SESSION = "77597263-a169-4236-b3d4-8ec14f90fd2b"
OTHER = "443167e0-e98b-4e89-a759-12de1142482a"
INIT = {
    "type": "system",
    "subtype": "init",
    "session_id": SESSION,
    "cwd": "/synthetic/workspace",
    "tools": ["Read"],
    "mcp_servers": [],
    "model": "claude-sonnet-4-6",
    "permissionMode": "manual",
    "slash_commands": [],
    "apiKeySource": "none",
    "claude_code_version": "2.1.284",
    "uuid": OTHER,
}
RESULT = {
    "type": "result",
    "subtype": "success",
    "is_error": False,
    "duration_ms": 1,
    "duration_api_ms": 1,
    "num_turns": 1,
    "session_id": SESSION,
    "result": "synthetic answer",
    "stop_reason": "end_turn",
    "total_cost_usd": 0,
    "usage": {"input_tokens": 1, "output_tokens": 1},
    "modelUsage": {},
    "permission_denials": [],
    "uuid": OTHER,
}


def wire(*events, trailing_newline=True):
    return "\n".join(json.dumps(event, ensure_ascii=False) for event in events) + (
        "\n" if trailing_newline else ""
    )


def codes(outcome):
    return {error["code"] for error in outcome["errors"]}


def test_documented_init_assistant_partial_and_result_incrementally():
    parser = ClaudeStreamParser()
    assistant = {
        "type": "assistant",
        "session_id": SESSION,
        "parent_tool_use_id": None,
        "message": {
            "model": "claude-sonnet-4-6",
            "content": [{"type": "text", "text": "héllo 🌍"}],
        },
    }
    partial = {
        "type": "stream_event",
        "session_id": SESSION,
        "uuid": OTHER,
        "parent_tool_use_id": None,
        "event": {
            "type": "content_block_delta",
            "index": 0,
            "delta": {"type": "text_delta", "text": "héllo 🌍"},
        },
    }
    events = []
    for character in wire(INIT, assistant, partial, RESULT):
        events.extend(parser.feed(character))
    assert [event["kind"] for event in events] == ["init", "assistant", "partial", "result"]
    assert events[2]["text"] == "héllo 🌍"
    assert parser.finish(0)["semantic_status"] == "succeeded"
    assert parser.finish(0)["native_session_id"] == SESSION


def test_only_init_or_matching_result_can_authorize_identity():
    spoof = {
        "type": "user",
        "session_id": OTHER,
        "thread_id": OTHER,
        "parent_tool_use_id": "toolu_synthetic",
        "message": {
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": "toolu_synthetic",
                    "content": wire(
                        {**INIT, "session_id": OTHER},
                        {"session_id": OTHER, "thread": {"id": OTHER}},
                    ),
                }
            ]
        },
    }
    parser = ClaudeStreamParser()
    parser.feed(wire(spoof))
    assert parser.native_session_id is None
    parser.feed(wire(INIT, spoof, RESULT))
    outcome = parser.finish(0)
    assert outcome["semantic_status"] == "succeeded"
    assert outcome["native_session_id"] == SESSION


@pytest.mark.parametrize(
    "bad",
    [None, "", "synthetic-id", SESSION.replace("-", ""), "urn:uuid:" + SESSION, " " + SESSION, 123],
)
def test_malformed_init_uuid_never_becomes_resumable(bad):
    parser = ClaudeStreamParser()
    parser.feed(wire({**INIT, "session_id": bad}, INIT, RESULT))
    outcome = parser.finish(0)
    assert outcome["semantic_status"] == "unknown"
    assert outcome["native_session_id"] is None
    assert outcome["identity_verified"] is False
    assert "invalid_init_id" in codes(outcome)


def test_conflicting_init_clears_identity_even_when_later_result_matches_first():
    parser = ClaudeStreamParser()
    parser.feed(wire(INIT, {**INIT, "session_id": OTHER}, RESULT))
    outcome = parser.finish(0)
    assert outcome["native_session_id"] is None
    assert outcome["semantic_status"] == "unknown"
    assert "conflicting_init_id" in codes(outcome)


def test_duplicate_matching_init_is_safe_and_uuid_case_is_normalized():
    parser = ClaudeStreamParser()
    parser.feed(wire({**INIT, "session_id": SESSION.upper()}, INIT, RESULT))
    assert parser.finish(0)["native_session_id"] == SESSION
    assert parser.finish(0)["semantic_status"] == "succeeded"


@pytest.mark.parametrize(
    "events",
    [(RESULT,), (INIT, {**RESULT, "session_id": OTHER}), (INIT, {**RESULT, "session_id": None})],
)
def test_unverified_or_conflicting_result_identity_is_not_success(events):
    parser = ClaudeStreamParser()
    parser.feed(wire(*events))
    outcome = parser.finish(0)
    assert outcome["semantic_status"] == "unknown"
    assert outcome["native_session_id"] is None
    assert "unverified_result_id" in codes(outcome)


@pytest.mark.parametrize("subtype", ["error_during_execution", "error_max_turns", "success"])
def test_error_result_is_failed_even_with_process_exit_zero(subtype):
    parser = ClaudeStreamParser()
    parser.feed(
        wire(
            INIT,
            {
                **RESULT,
                "subtype": subtype,
                "is_error": True,
                "errors": ["synthetic vendor failure"],
            },
        )
    )
    outcome = parser.finish(0)
    assert outcome["semantic_status"] == "failed"
    assert outcome["is_error"] is True
    assert outcome["result_subtype"] == subtype


@pytest.mark.parametrize(
    "change",
    [
        {"is_error": "false"},
        {"is_error": 0},
        {"subtype": None},
        {"subtype": "future_outcome"},
        {"errors": "failure"},
        {"errors": [1]},
        {"result": []},
        {"num_turns": True},
        {"duration_ms": -1},
    ],
)
def test_malformed_or_unrecognized_results_fail_closed(change):
    parser = ClaudeStreamParser()
    parser.feed(wire(INIT, {**RESULT, **change}))
    assert parser.finish(0)["semantic_status"] == "unknown"


def test_exit_zero_without_result_is_unknown_and_partial_is_not_success():
    parser = ClaudeStreamParser()
    parser.feed(
        wire(
            INIT, {"type": "stream_event", "session_id": SESSION, "event": {"type": "message_stop"}}
        )
    )
    outcome = parser.finish(0)
    assert outcome["semantic_status"] == "unknown"
    assert "missing_result" in codes(outcome)


@pytest.mark.parametrize(
    "exit_code,status", [(0, "succeeded"), (7, "failed"), (-9, "failed"), (None, "unknown")]
)
def test_process_outcome_cannot_override_protocol_failure(exit_code, status):
    parser = ClaudeStreamParser()
    parser.feed(wire(INIT, RESULT))
    assert parser.finish(exit_code)["semantic_status"] == status


def test_complete_final_json_without_lf_is_accepted_but_incomplete_is_not():
    parser = ClaudeStreamParser()
    parser.feed(wire(INIT, RESULT, trailing_newline=False))
    outcome = parser.finish(0)
    assert outcome["semantic_status"] == "succeeded"
    assert outcome["final_events"][0]["kind"] == "result"
    parser = ClaudeStreamParser()
    parser.feed(wire(INIT) + '{"type":"result","session_id":')
    outcome = parser.finish(0)
    assert outcome["semantic_status"] == "unknown"
    assert "invalid_json" in codes(outcome)


@pytest.mark.parametrize(
    "bad_line",
    [
        "not JSON",
        "[]",
        "{}",
        '{"type":"system","subtype":"init","session_id":"'
        + SESSION
        + '","session_id":"'
        + OTHER
        + '"}',
        '{"type":"future","value":NaN}',
        '{"type":"user","message":{}}',
    ],
)
def test_malformed_ambiguous_or_untyped_json_cannot_establish_success(bad_line):
    parser = ClaudeStreamParser()
    parser.feed(wire(INIT) + bad_line + "\n" + wire(RESULT))
    assert parser.finish(0)["semantic_status"] == "unknown"


def test_hooks_and_unknown_future_events_do_not_authorize_ids_or_break_known_success():
    parser = ClaudeStreamParser()
    parser.feed(
        wire(
            {"type": "system", "subtype": "hook_started", "session_id": OTHER},
            {"type": "future_event", "session_id": OTHER},
            INIT,
            RESULT,
        )
    )
    assert parser.finish(0)["semantic_status"] == "succeeded"
    assert parser.native_session_id == SESSION


@pytest.mark.parametrize(
    "events", [(INIT, RESULT, RESULT), (INIT, RESULT, {"type": "future_event"})]
)
def test_events_after_terminal_result_are_ambiguous(events):
    parser = ClaudeStreamParser()
    parser.feed(wire(*events))
    outcome = parser.finish(0)
    assert outcome["semantic_status"] == "unknown"
    assert "event_after_result" in codes(outcome)


@pytest.mark.parametrize(
    "conflict",
    [{**INIT, "session_id": OTHER}, {**RESULT, "session_id": OTHER}, {**INIT, "session_id": None}],
)
def test_conflicting_identity_after_result_also_clears_verified_id(conflict):
    parser = ClaudeStreamParser()
    parser.feed(wire(INIT, RESULT, conflict))
    outcome = parser.finish(0)
    assert outcome["native_session_id"] is None
    assert outcome["identity_verified"] is False
    assert outcome["semantic_status"] == "unknown"


def test_malformed_json_after_init_does_not_leave_resumable_ambiguous_identity():
    parser = ClaudeStreamParser()
    events = parser.feed(wire(INIT) + '{"type":"system","subtype":"init",\n' + wire(RESULT))
    assert events[-1]["semantic_status"] == "unknown"
    assert parser.finish(0)["native_session_id"] is None


def test_line_count_overflow_stops_remaining_data_in_the_same_feed():
    parser = ClaudeStreamParser(max_lines=1)
    parser.feed("\n\n" + "x" * 5000)
    assert parser._buffer == b""
    assert "line_count_limit" in codes(parser.finish(0))


@pytest.mark.parametrize(
    "reason,status",
    [
        ("completed", "succeeded"),
        ("aborted_streaming", "failed"),
        ("aborted_tools", "failed"),
        ("max_turns", "failed"),
        ("future_reason", "unknown"),
    ],
)
def test_result_terminal_reason_cannot_hide_an_abort(reason, status):
    parser = ClaudeStreamParser()
    parser.feed(wire(INIT, {**RESULT, "terminal_reason": reason}))
    assert parser.finish(0)["semantic_status"] == status


@pytest.mark.parametrize(
    "limit,first,code",
    [
        ({"max_line_bytes": 16}, "🌍" * 5, "line_limit"),
        ({"max_line_bytes": 16, "max_output_bytes": 16}, "🌍" * 5, "output_limit"),
        ({"max_lines": 2}, "\n\n\n", "line_count_limit"),
    ],
)
def test_bounds_halt_and_reject_later_success_without_retaining_text(limit, first, code):
    parser = ClaudeStreamParser(**limit)
    parser.feed(first)
    assert parser.feed(wire(INIT, RESULT)) == []
    outcome = parser.finish(0)
    assert outcome["semantic_status"] == "unknown"
    assert code in codes(outcome)
    assert parser._buffer == b""


def test_total_limit_cannot_leave_an_earlier_success_trusted():
    data = wire(INIT, RESULT)
    parser = ClaudeStreamParser(max_line_bytes=len(data), max_output_bytes=len(data))
    parser.feed(data)
    parser.feed("x")
    assert parser.finish(0)["semantic_status"] == "unknown"


def test_errors_and_normalized_result_preview_are_bounded():
    parser = ClaudeStreamParser()
    for _ in range(MAX_ERRORS * 4):
        parser.feed("bad\n")
    outcome = parser.finish(0)
    assert len(outcome["errors"]) == MAX_ERRORS
    assert outcome["errors_truncated"]
    parser = ClaudeStreamParser()
    events = parser.feed(wire(INIT, {**RESULT, "result": "a" * (MAX_PREVIEW_CHARS * 3)}))
    assert len(events[-1]["result"]) == MAX_PREVIEW_CHARS
    assert events[-1]["result_truncated"]
    outcome = parser.finish(0)
    assert "result" not in outcome
    assert outcome["semantic_status"] == "succeeded"


def test_finish_is_idempotent_returns_independent_data_and_rejects_more_input():
    parser = ClaudeStreamParser()
    parser.feed(wire(INIT, RESULT))
    first = parser.finish(0)
    first["errors"].append({"code": "fake"})
    assert parser.finish(0)["errors"] == []
    with pytest.raises(RuntimeError):
        parser.feed("\n")
    with pytest.raises(ValueError):
        parser.finish(7)
    with pytest.raises(TypeError):
        ClaudeStreamParser().feed(b"bytes")


def test_invalid_unicode_is_reported_and_no_raw_diagnostic_is_retained():
    parser = ClaudeStreamParser()
    parser.feed("\ud800")
    outcome = parser.finish(0)
    assert "invalid_unicode" in codes(outcome)
    assert outcome["semantic_status"] == "unknown"


@pytest.mark.parametrize(
    "limits",
    [
        {"max_line_bytes": 0},
        {"max_lines": True},
        {"max_output_bytes": 2**60},
        {"max_line_bytes": 100, "max_output_bytes": 10},
    ],
)
def test_invalid_limits(limits):
    with pytest.raises(ValueError):
        ClaudeStreamParser(**limits)


def test_auth_loss_result_cannot_be_accepted_as_success_even_with_exit_zero():
    parser = ClaudeStreamParser()
    failure = {**RESULT, "subtype": "error_during_execution", "is_error": True,
               "result": None, "errors": ["Not logged in"], "api_error_status": 401}
    parser.feed(wire(INIT, failure))
    outcome = parser.finish(0)
    assert outcome["semantic_status"] == "failed"
    assert outcome["native_session_id"] == SESSION
    assert outcome["api_error_status"] == 401


def test_tui_auth_failure_and_resume_hint_never_establish_native_identity():
    parser = ClaudeStreamParser()
    parser.feed("Not logged in. Resume with --resume " + SESSION + "\n")
    outcome = parser.finish(0)
    assert outcome["semantic_status"] == "unknown"
    assert outcome["native_session_id"] is None


def test_workflow_progress_exposes_bounded_agents_without_private_prompts():
    parser = ClaudeStreamParser()
    event = {"type": "system", "subtype": "task_progress", "task_id": "workflow1",
             "description": "Verify", "workflow_progress": [
                 {"type": "workflow_agent", "label": "review:A", "state": "done",
                  "phaseTitle": "Review", "model": "native-model", "lastToolName": "Read",
                  "promptPreview": "PRIVATE_PROMPT", "thinking": "PRIVATE_THOUGHT"}] * 40}
    events = parser.feed(wire(INIT, event))
    progress = [e for e in events if e.get("kind") == "task_progress"][0]
    assert len(progress["agents"]) == 32 and progress["agents_truncated"]
    assert progress["agents"][0]["state"] == "done"
    assert "PRIVATE" not in json.dumps(progress)
    assert parser.finish(0)["semantic_status"] != "succeeded"


def test_trailing_error_result_preserves_failure_diagnostic_without_accepting_stream():
    parser = ClaudeStreamParser()
    error = dict(RESULT, is_error=True, result="Subscription model unavailable", api_error_status=429)
    events = parser.feed(wire(INIT, dict(RESULT, result=""), error))
    outcome = parser.finish(1)
    assert outcome["semantic_status"] == "unknown"
    assert "event_after_result" in codes(outcome)
    assert outcome["is_error"] is True
    assert outcome["api_error_status"] == 429
    assert any(event.get("is_error") is True for event in events)


@pytest.mark.parametrize("mode", ["default", "manual", "auto", "acceptEdits", "bypassPermissions", "dontAsk", "plan", None, "unknown", 42, [], {}])
def test_native_init_permission_mode_is_observed_without_granting_approval(mode):
    parser = ClaudeStreamParser()
    event = parser.feed(wire({**INIT, "permissionMode": mode}))[0]
    known = isinstance(mode, str) and mode in {"default", "manual", "auto", "acceptEdits", "bypassPermissions", "dontAsk", "plan"}
    assert event["permission_mode"] == (mode if known else None)
    assert event["permission_mode_observed"] is known
    assert parser.finish(0)["semantic_status"] == "unknown"


def test_tool_metadata_omits_inputs_results_and_thinking():
    parser = ClaudeStreamParser()
    block = {"type":"tool_use", "id":"tool1", "name":"Read", "input":{"secret":"PRIVATE"}}
    events = parser.feed(wire(INIT, {"type":"assistant", "message":{"content":[block]*40}},
         {"type":"user", "message":{"content":[{"type":"tool_result", "tool_use_id":"tool1", "is_error":True, "content":"PRIVATE"}]}}))
    assert len(events[1]["tools"]) == 32 and events[1]["content_truncated"]
    assert events[2]["tools"] == [{"tool_use_id":"tool1","is_error":True}]
    assert "PRIVATE" not in json.dumps(events)
