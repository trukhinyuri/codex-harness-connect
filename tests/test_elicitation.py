import asyncio
import json
from types import SimpleNamespace

import pytest
from mcp import types
from mcp.server.elicitation import (
    AcceptedElicitation,
    CancelledElicitation,
    DeclinedElicitation,
    elicit_with_validation,
)
from pydantic import ValidationError

from codex_harness_connect.elicitation import FormCheckAnswer, check_interaction


def client_params(elicitation=None, *, protocol="2025-11-25", client_info=None):
    capabilities = {} if elicitation is None else {"elicitation": elicitation}
    return types.InitializeRequestParams(
        protocolVersion=protocol,
        capabilities=types.ClientCapabilities.model_validate(capabilities),
        clientInfo=types.Implementation.model_validate(
            client_info or {"name": "fixture-client", "version": "1"}
        ),
    )


class RecordingContext:
    def __init__(self, params, answer=None, error=None):
        self.request_context = SimpleNamespace(session=SimpleNamespace(client_params=params))
        self.answer = answer
        self.error = error
        self.calls = []

    async def elicit(self, message, schema):
        self.calls.append((message, schema))
        if self.error is not None:
            raise self.error
        return self.answer


def assert_no_action(result):
    for key in (
        "authorizes_native_action", "human_attestation_verified", "answer_persisted_by_connector",
    ):
        assert result[key] is False
    assert 0 <= result["elapsed_seconds"] < 2


@pytest.mark.parametrize("capability", [
    None, {"url": {}}, {"form": None}, {"url": None}, {"future": {}}, {"future": None},
])
def test_only_proven_form_support_triggers_elicitation(capability):
    ctx = RecordingContext(client_params(capability))
    result = asyncio.run(check_interaction(ctx))
    assert result["status"] == "unsupported"
    assert result["form_advertised"] is False
    assert result["choice"] is None
    assert ctx.calls == []
    assert_no_action(result)


def test_uninitialized_session_does_not_elicit():
    ctx = RecordingContext(None)
    result = asyncio.run(check_interaction(ctx))
    assert result["status"] == "unsupported"
    assert result["client"] is None
    assert ctx.calls == []
    assert_no_action(result)


@pytest.mark.parametrize("capability", [{}, {"form": {}}, {"form": {}, "future": {}}])
@pytest.mark.parametrize("choice", ["form_visible", "form_not_usable"])
def test_actual_sdk_capability_and_accepted_models_are_observation_only(capability, choice):
    answer = AcceptedElicitation[FormCheckAnswer](data=FormCheckAnswer(choice=choice))
    ctx = RecordingContext(client_params(capability), answer=answer)
    result = asyncio.run(check_interaction(ctx))
    assert result["status"] == "answered"
    assert result["choice"] == choice
    assert result["form_advertised"] is True
    assert len(ctx.calls) == 1
    message, schema = ctx.calls[0]
    assert isinstance(message, str) and message
    form = schema.model_json_schema()
    assert form["required"] == ["choice"]
    assert form["additionalProperties"] is False
    assert set(form["properties"]["choice"]["enum"]) == {
        "form_visible", "form_not_usable",
    }
    assert "default" not in form["properties"]["choice"]
    assert_no_action(result)


@pytest.mark.parametrize("payload", [
    {}, {"choice": "allow_once"}, {"choice": True}, {"choice": 1},
    {"choice": "form_visible", "authorizes_native_action": True},
])
def test_answer_model_requires_exact_enum_and_forbids_extra_fields(payload):
    with pytest.raises(ValidationError):
        FormCheckAnswer.model_validate(payload)


@pytest.mark.parametrize(("content", "status", "choice"), [
    ({"choice": "form_visible"}, "answered", "form_visible"),
    ({"choice": "form_not_usable"}, "answered", "form_not_usable"),
    ({}, "invalid_response", None),
    (None, "invalid_response", None),
])
def test_public_sdk_helper_accepts_wire_schema_and_rejects_empty_accept(content, status, choice):
    class Session:
        client_params = client_params({"form": {}})
        calls = []

        async def elicit_form(self, **kwargs):
            self.calls.append(kwargs)
            return types.ElicitResult(action="accept", content=content)

    class Context:
        def __init__(self):
            self.request_context = SimpleNamespace(session=Session())

        async def elicit(self, message, schema):
            return await elicit_with_validation(self.request_context.session, message, schema)

    ctx = Context()
    result = asyncio.run(check_interaction(ctx))
    assert len(ctx.request_context.session.calls) == 1
    assert result["status"] == status
    assert result["choice"] == choice
    assert_no_action(result)


@pytest.mark.parametrize("data", [
    None, {}, [], "form_visible", {"choice": "ALLOW"}, {"choice": True},
    {"choice": "form_visible", "secret": "response-sentinel"},
    FormCheckAnswer.model_construct(choice="invalid-without-validation"),
])
def test_malformed_accept_never_becomes_a_choice_or_authorization(data):
    ctx = RecordingContext(client_params({"form": {}}),
                           answer=SimpleNamespace(action="accept", data=data))
    result = asyncio.run(check_interaction(ctx))
    assert result["status"] == "invalid_response"
    assert result["choice"] is None
    assert "response-sentinel" not in json.dumps(result)
    assert_no_action(result)


@pytest.mark.parametrize(("answer", "status"), [
    (DeclinedElicitation(), "declined"),
    (CancelledElicitation(), "cancelled"),
    (SimpleNamespace(action="decline", data={"choice": "form_visible"}), "declined"),
    (SimpleNamespace(action="cancel", data={"choice": "form_visible"}), "cancelled"),
    (SimpleNamespace(action="unrecognized", data={"choice": "form_visible"}), "invalid_response"),
    (None, "invalid_response"),
])
def test_non_accept_actions_ignore_any_supplied_choice(answer, status):
    ctx = RecordingContext(client_params({}), answer=answer)
    result = asyncio.run(check_interaction(ctx))
    assert result["status"] == status
    assert result["choice"] is None
    assert_no_action(result)


@pytest.mark.parametrize(("error", "status"), [
    (RuntimeError("transport-secret-sentinel /private/token"), "transport_error"),
    (ValueError("transport-secret-sentinel raw response"), "invalid_response"),
])
def test_exception_contents_are_not_returned(error, status):
    ctx = RecordingContext(client_params({}), error=error)
    result = asyncio.run(check_interaction(ctx))
    assert result["status"] == status
    assert result["choice"] is None
    assert "transport-secret-sentinel" not in json.dumps(result)
    assert "/private/token" not in json.dumps(result)
    assert_no_action(result)


class BlockingContext(RecordingContext):
    def __init__(self):
        super().__init__(client_params({"form": {}}))
        self.entered = asyncio.Event()
        self.cleaned = asyncio.Event()
        self.cancelled = False

    async def elicit(self, message, schema):
        self.calls.append((message, schema))
        self.entered.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            self.cancelled = True
            raise
        finally:
            self.cleaned.set()


def test_timeout_cancels_and_finishes_pending_elicitation():
    async def check():
        ctx = BlockingContext()
        result = await asyncio.wait_for(check_interaction(ctx, timeout_seconds=0.01), timeout=1)
        assert result["status"] == "timed_out"
        assert result["choice"] is None
        assert ctx.entered.is_set() and ctx.cancelled and ctx.cleaned.is_set()
        assert_no_action(result)

    asyncio.run(check())


def test_caller_cancellation_propagates_and_cleans_up_elicitation():
    async def check():
        ctx = BlockingContext()
        task = asyncio.create_task(check_interaction(ctx))
        await asyncio.wait_for(ctx.entered.wait(), timeout=1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, timeout=1)
        assert ctx.cancelled and ctx.cleaned.is_set()

    asyncio.run(check())


def test_accept_returned_after_deadline_is_not_an_answer():
    class LateAnswerContext(BlockingContext):
        async def elicit(self, message, schema):
            self.entered.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                # A transport that resolves while cancellation is unwinding must
                # not turn an expired check into a successful observation.
                return AcceptedElicitation[FormCheckAnswer](
                    data=FormCheckAnswer(choice="form_visible")
                )
            finally:
                self.cleaned.set()

    async def check():
        ctx = LateAnswerContext()
        result = await asyncio.wait_for(check_interaction(ctx, timeout_seconds=0.01), timeout=1)
        assert result["status"] == "timed_out"
        assert result["choice"] is None
        assert ctx.cleaned.is_set()
        assert_no_action(result)

    asyncio.run(check())


def test_metadata_only_exports_bounded_public_identity():
    params = client_params(None, protocol="p" * 200, client_info={
        "name": "n" * 700, "version": "v" * 700,
        "title": "metadata-secret-sentinel", "websiteUrl": "https://private.example",
        "unknown": {"token": "metadata-secret-sentinel"},
    })
    result = asyncio.run(check_interaction(RecordingContext(params)))
    assert set(result["client"]) == {"name", "version", "client_requested_protocol"}
    assert len(result["client"]["name"]) <= 256
    assert len(result["client"]["version"]) <= 256
    assert len(result["client"]["client_requested_protocol"]) <= 64
    assert "metadata-secret-sentinel" not in json.dumps(result)
    assert "private.example" not in json.dumps(result)
    assert_no_action(result)


def test_sdk_valid_integer_protocol_metadata_does_not_raise():
    # mcp 1.30 declares str | int; this is a real validated public params object.
    result = asyncio.run(check_interaction(RecordingContext(client_params(protocol=20250901))))
    assert result["status"] == "unsupported"
    protocol = result["client"]["client_requested_protocol"]
    assert protocol is None or isinstance(protocol, (str, int))
    assert protocol is None or len(str(protocol)) <= 64
    assert_no_action(result)


@pytest.mark.parametrize("timeout", [True, False, 0, -1, 46, float("inf"), float("nan"), "1"])
def test_invalid_timeout_rejected_before_elicitation(timeout):
    ctx = RecordingContext(client_params({"form": {}}))
    with pytest.raises(ValueError):
        asyncio.run(check_interaction(ctx, timeout_seconds=timeout))
    assert ctx.calls == []
