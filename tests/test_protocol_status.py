"""Synthetic SDK wire shapes; no live result, task acceptance or billing claim.

Wire discriminants verified 2026-10-01 against the official SDK message_parser.py:
https://github.com/anthropics/claude-agent-sdk-python/blob/main/src/claude_agent_sdk/_internal/message_parser.py
RateLimitInfo numeric/status semantics and DeferredToolUse fields:
https://github.com/anthropics/claude-agent-sdk-python/blob/main/src/claude_agent_sdk/types.py
"""
import json

import pytest

from codex_harness_connect.protocols import (
    MAX_DENIAL_COUNT,
    MAX_RATE_LIMIT_EVENTS,
    MAX_TOOL_IDENTIFIER_CHARS,
    ClaudeStreamParser,
)

SESSION = "77597263-a169-4236-b3d4-8ec14f90fd2b"
OTHER = "443167e0-e98b-4e89-a759-12de1142482a"
INIT = {"type": "system", "subtype": "init", "session_id": SESSION}
RESULT = {"type": "result", "subtype": "success", "is_error": False,
          "duration_ms": 1, "duration_api_ms": 1, "num_turns": 1,
          "session_id": SESSION, "result": "synthetic protocol answer"}
RATE = {"type": "rate_limit_event", "uuid": OTHER, "session_id": SESSION,
        "rate_limit_info": {"status": "allowed_warning", "resetsAt": 1790840000,
            "rateLimitType": "five_hour", "utilization": 0.91,
            "overageStatus": "rejected", "overageResetsAt": None,
            "overageDisabledReason": "synthetic account constraint"}}


def wire(*events):
    return "".join(json.dumps(event) + "\n" for event in events)


@pytest.mark.parametrize("denials", [None, [], [{"tool_name": "Write", "tool_input": "PRIVATE"}]])
def test_protocol_success_with_denials_never_accepts_requested_task(denials):
    parser = ClaudeStreamParser()
    events = parser.feed(wire(INIT, {**RESULT, "permission_denials": denials}))
    outcome = parser.finish(0)
    assert outcome["semantic_status"] == "succeeded"
    assert outcome["task_acceptance"] == "requires-parent-verification"
    assert events[-1]["task_acceptance"] == outcome["task_acceptance"]
    assert outcome["permission_denial_count"] == len(denials or [])
    assert not outcome["permission_denials_truncated"]
    assert "PRIVATE" not in json.dumps([events, outcome])


def test_denial_count_is_capped_without_retaining_any_entry():
    parser = ClaudeStreamParser()
    denials = [{"tool_input": {"secret": "PRIVATE"}}] * (MAX_DENIAL_COUNT + 37)
    events = parser.feed(wire(INIT, {**RESULT, "permission_denials": denials}))
    outcome = parser.finish(0)
    assert outcome["permission_denial_count"] == MAX_DENIAL_COUNT
    assert outcome["permission_denials_truncated"]
    assert events[-1]["permission_denials_truncated"]
    assert "PRIVATE" not in json.dumps([events, outcome])


def test_deferred_tool_retains_only_bounded_id_and_name_and_no_task_acceptance():
    parser = ClaudeStreamParser()
    deferred = {"id": "i" * 500, "name": "n" * 600,
                "input": {"command": "PRIVATE", "large": "x" * 10000}}
    events = parser.feed(wire(INIT, {**RESULT, "deferred_tool_use": deferred}))
    outcome = parser.finish(0)
    assert outcome["semantic_status"] == "succeeded"
    assert outcome["task_acceptance"] == "requires-parent-verification"
    assert set(outcome["deferred_tool_use"]) == {"id", "name"}
    assert all(len(value) == MAX_TOOL_IDENTIFIER_CHARS for value in outcome["deferred_tool_use"].values())
    assert outcome["deferred_tool_truncated"]
    assert "PRIVATE" not in json.dumps([events, outcome])


@pytest.mark.parametrize("status", [401, 403, 429, 500, 529])
def test_native_api_http_error_is_failed_even_with_success_subtype(status):
    parser = ClaudeStreamParser()
    events = parser.feed(wire(INIT, {**RESULT, "is_error": True, "api_error_status": status}))
    outcome = parser.finish(0)
    assert outcome["semantic_status"] == "failed"
    assert outcome["api_error_status"] == status == events[-1]["api_error_status"]
    assert outcome["task_acceptance"] == "requires-parent-verification"


@pytest.mark.parametrize("change", [
    {"permission_denials": "denied"}, {"permission_denials": {}},
    {"deferred_tool_use": []}, {"deferred_tool_use": {}},
    {"deferred_tool_use": {"id": "x", "name": "Write", "input": None}},
    {"deferred_tool_use": {"id": 1, "name": "Write", "input": {}}},
    {"api_error_status": True}, {"api_error_status": "429"},
    {"api_error_status": 99}, {"api_error_status": 600}, {"api_error_status": 429},
])
def test_malformed_or_conflicting_tool_status_cannot_establish_success(change):
    parser = ClaudeStreamParser()
    parser.feed(wire(INIT, {**RESULT, **change}))
    outcome = parser.finish(0)
    assert outcome["semantic_status"] == "unknown"
    assert outcome["task_acceptance"] == "requires-parent-verification"
    assert "invalid_result" in {error["code"] for error in outcome["errors"]}


def test_rate_limit_wire_camelcase_is_normalized_without_raw_fields_or_identity_authorization():
    parser = ClaudeStreamParser()
    rate = {**RATE, "rate_limit_info": {**RATE["rate_limit_info"], "raw_secret": "PRIVATE"}}
    event = parser.feed(wire(rate))[0]
    assert parser.native_session_id is None
    assert event["kind"] == "rate_limit"
    assert event["rate_limit_info"]["resets_at"] == RATE["rate_limit_info"]["resetsAt"]
    assert event["rate_limit_info"]["rate_limit_type"] == "five_hour"
    assert event["rate_limit_info"]["overage_status"] == "rejected"
    parser.feed(wire(INIT, RESULT))
    outcome = parser.finish(0)
    assert outcome["semantic_status"] == "succeeded"
    assert outcome["native_session_id"] == SESSION
    assert "PRIVATE" not in json.dumps([event, outcome])
    assert outcome["task_acceptance"] == "requires-parent-verification"


def test_rate_limit_history_and_text_are_bounded_latest_observation_is_retained():
    parser = ClaudeStreamParser()
    parser.feed(wire(INIT))
    for index in range(MAX_RATE_LIMIT_EVENTS + 10):
        info = {**RATE["rate_limit_info"], "resetsAt": index,
                "rateLimitType": "x" * 1000, "overageDisabledReason": "r" * 1000}
        parser.feed(wire({**RATE, "rate_limit_info": info}))
    parser.feed(wire(RESULT))
    outcome = parser.finish(0)
    assert len(outcome["rate_limit_events"]) == MAX_RATE_LIMIT_EVENTS
    assert outcome["rate_limit_events_truncated"]
    assert outcome["rate_limit_events"][-1]["resets_at"] == MAX_RATE_LIMIT_EVENTS + 9
    assert len(outcome["rate_limit_events"][-1]["rate_limit_type"]) == 64
    assert len(outcome["rate_limit_events"][-1]["overage_disabled_reason"]) == 256
    assert outcome["rate_limit_events"][-1]["metadata_truncated"]


@pytest.mark.parametrize("change", [
    {"status": []}, {"status": "future-status"}, {"resetsAt": True},
    {"resetsAt": -1}, {"overageResetsAt": 2**60}, {"utilization": True},
    {"utilization": -0.1}, {"utilization": 1.1}, {"utilization": 10**300},
    {"overageStatus": {}}, {"rateLimitType": []}, {"overageDisabledReason": 1},
])
def test_malformed_rate_metadata_is_unknown_without_echoing_raw_values(change):
    parser = ClaudeStreamParser()
    parser.feed(wire(INIT, {**RATE, "rate_limit_info": {**RATE["rate_limit_info"], **change}}, RESULT))
    outcome = parser.finish(0)
    assert outcome["semantic_status"] == "unknown"
    assert "invalid_rate_limit" in {error["code"] for error in outcome["errors"]}
    assert outcome["native_session_id"] == SESSION


@pytest.mark.parametrize("change", [{"rate_limit_info": []}, {"uuid": "bad"}, {"session_id": OTHER}])
def test_malformed_rate_event_does_not_change_verified_init_identity(change):
    parser = ClaudeStreamParser()
    parser.feed(wire(INIT, {**RATE, **change}, RESULT))
    outcome = parser.finish(0)
    assert outcome["semantic_status"] == "unknown"
    assert outcome["native_session_id"] == SESSION


def test_mutating_returned_status_summaries_cannot_change_finished_outcome():
    parser = ClaudeStreamParser()
    events = parser.feed(wire(INIT, RATE, {**RESULT,
        "deferred_tool_use": {"id": "toolu_synthetic", "name": "Write", "input": {}}}))
    events[1]["rate_limit_info"]["status"] = "forged"
    events[-1]["deferred_tool_use"]["name"] = "forged"
    first = parser.finish(0)
    assert first["rate_limit_events"][0]["status"] == "allowed_warning"
    assert first["deferred_tool_use"]["name"] == "Write"
    first["deferred_tool_use"]["name"] = "forged"
    assert parser.finish(0)["deferred_tool_use"]["name"] == "Write"


def test_new_metadata_cannot_bypass_existing_line_or_uuid_rules():
    parser = ClaudeStreamParser(max_line_bytes=200)
    parser.feed(wire(INIT, {**RESULT, "permission_denials": ["x"] * 1000}))
    assert parser.finish(0)["semantic_status"] == "unknown"
    parser = ClaudeStreamParser()
    parser.feed(wire(INIT, {**RESULT, "session_id": OTHER, "permission_denials": ["x"]}))
    outcome = parser.finish(0)
    assert outcome["semantic_status"] == "unknown" and outcome["native_session_id"] is None
    assert outcome["task_acceptance"] == "requires-parent-verification"
