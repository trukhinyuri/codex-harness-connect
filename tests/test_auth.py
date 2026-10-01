import hashlib
import json
import os
import signal
import subprocess
import sys
import time
from datetime import datetime

import pytest

from codex_harness_connect import auth

VALID = {
    "loggedIn": True, "authMethod": "claude.ai", "apiProvider": "firstParty",
    "subscriptionType": "max",
}
PRIVATE = "synthetic-private-account-sentinel"


@pytest.fixture(autouse=True)
def isolated_environment(monkeypatch):
    # Replace, rather than enumerate, the host environment; these tests use no native login.
    monkeypatch.setenv("CHC_TEST_INHERITED", "fixture")
    monkeypatch.setattr(os, "environ", {"PATH": os.defpath, "CHC_TEST_INHERITED": "fixture"})


@pytest.fixture
def executable(tmp_path):
    path = tmp_path / "synthetic claude"

    def create(body="pass\n"):
        path.write_text(f"#!{sys.executable}\n" + body)
        path.chmod(0o700)
        return path, hashlib.sha256(path.read_bytes()).hexdigest()

    return create


def observation(monkeypatch, executable, tmp_path, payload=VALID, code=0):
    path, digest = executable()
    raw = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
    monkeypatch.setattr(auth, "_probe", lambda *args, **kwargs: (code, raw))
    return auth.observe_auth(str(path), str(tmp_path), digest)


def assert_private(result):
    assert PRIVATE not in json.dumps(result)
    assert result["billing_guarantee"] is False
    assert result["included_quota_remaining"] == "not_observed"
    assert result["usage_credits_status"] == "not_observed"
    assert datetime.fromisoformat(result["observed_at"]).utcoffset().total_seconds() == 0


@pytest.mark.parametrize("subscription", ["pro", "max", "team", "enterprise"])
def test_known_subscription_routes_are_point_in_time_only(
    monkeypatch, executable, tmp_path, subscription,
):
    result = observation(monkeypatch, executable, tmp_path, {
        **VALID, "subscriptionType": subscription, "email": PRIVATE,
        "organization": {"secret": PRIVATE}, "configDirectory": PRIVATE,
        "accessToken": PRIVATE,
    })
    assert result["status"] == "subscription_route_observed"
    assert result["route_eligible"] is True
    assert result["subscription_type"] == subscription
    assert set(result) == {
        "observed_at", "status", "route_eligible", "logged_in", "auth_method",
        "api_provider", "subscription_type", "reason_codes", "override_names_present",
        "binary_sha256", "billing_guarantee", "included_quota_remaining",
        "usage_credits_status",
    }
    assert_private(result)


@pytest.mark.parametrize("payload,code", [
    ({**VALID, "authMethod": "api_key", "subscriptionType": None}, 0),
    ({**VALID, "apiProvider": "bedrock"}, 0),
    ({**VALID, "apiProvider": "vertex"}, 0),
    ({**VALID, "apiProvider": "foundry"}, 0),
    ({**VALID, "subscriptionType": None}, 0),
    ({"loggedIn": False, "authMethod": "none", "apiProvider": "firstParty"}, 1),
])
def test_api_unknown_and_logged_out_never_authorize(monkeypatch, executable, tmp_path, payload, code):
    result = observation(monkeypatch, executable, tmp_path, payload, code)
    assert result["route_eligible"] is False
    assert result["status"] in {"held", "not_authenticated"}
    assert_private(result)


def test_native_oauth_token_recognized_but_effective_route_unattested(
    monkeypatch, executable, tmp_path,
):
    result = observation(monkeypatch, executable, tmp_path, {
        "loggedIn": True, "authMethod": "oauth_token", "apiProvider": "firstParty",
        "subscriptionType": None, "configDirectory": PRIVATE,
    })
    assert result["status"] == "held"
    assert result["auth_method"] == "oauth_token"
    assert result["api_provider"] == "firstParty"
    assert result["route_eligible"] is False
    assert result["reason_codes"] == ["effective_route_not_attested"]
    assert_private(result)


@pytest.mark.parametrize("raw", [
    b"{}", b"[]", b"null", b"\xff", b"{", b'{"loggedIn":1}',
    json.dumps({**VALID, "loggedIn": "true"}).encode(),
    json.dumps({**VALID, "authMethod": "future-account"}).encode(),
    json.dumps({**VALID, "apiProvider": True}).encode(),
    json.dumps({**VALID, "subscriptionType": "premium"}).encode(),
    b'{"loggedIn":false,"loggedIn":true,"authMethod":"claude.ai",'
    b'"apiProvider":"firstParty","subscriptionType":"max"}',
    json.dumps(VALID).encode()[:-1] + b',"ignored":{"token":1,"token":2}}',
])
def test_malformed_duplicate_and_unknown_types_fail_closed(monkeypatch, executable, tmp_path, raw):
    result = observation(monkeypatch, executable, tmp_path, raw)
    assert result["route_eligible"] is False
    assert result["status"] == "probe_error"
    assert_private(result)


def test_non_json_numeric_constant_in_unknown_field_is_rejected(monkeypatch, executable, tmp_path):
    raw = json.dumps(VALID).encode()[:-1] + b',"ignored":NaN}'
    assert observation(monkeypatch, executable, tmp_path, raw)["route_eligible"] is False


@pytest.mark.parametrize("code", [1, -signal.SIGTERM, 2])
def test_exit_status_cannot_disagree_with_login(monkeypatch, executable, tmp_path, code):
    result = observation(monkeypatch, executable, tmp_path, code=code)
    assert result["route_eligible"] is False
    assert result["reason_codes"] == ["inconsistent_auth_exit"]


@pytest.mark.parametrize("name", [
    "CLAUDE_CONFIG_DIR", "ANTHROPIC_API_KEY", "ANTHROPIC_CUSTOM_HEADERS",
    "ANTHROPIC_PROFILE", "CLAUDE_CODE_PROVIDER_MANAGED_BY_HOST",
    "ANTHROPIC_FOUNDRY_AUTH_TOKEN", "ANTHROPIC_VERTEX_BASE_URL",
    "ANTHROPIC_FOUNDRY_API_KEY", "ANTHROPIC_FOUNDRY_BASE_URL",
    "ANTHROPIC_FOUNDRY_RESOURCE", "ANTHROPIC_VERTEX_PROJECT_ID",
    "AWS_BEARER_TOKEN_BEDROCK", "CLAUDE_CODE_SKIP_ANTHROPIC_AWS_AUTH",
    "CLAUDE_CODE_SKIP_BEDROCK_AUTH", "CLAUDE_CODE_SKIP_FOUNDRY_AUTH",
    "CLAUDE_CODE_SKIP_MANTLE_AUTH", "CLAUDE_CODE_SKIP_VERTEX_AUTH",
    "CLAUDE_CODE_OAUTH_REFRESH_TOKEN", "CLAUDE_CODE_OAUTH_SCOPES",
])
def test_documented_overrides_hold_even_when_empty(monkeypatch, executable, tmp_path, name):
    os.environ[name] = ""
    result = observation(monkeypatch, executable, tmp_path)
    assert result["route_eligible"] is False
    assert result["override_names_present"] == [name]
    assert result["reason_codes"] == ["auth_or_route_override_present"]


def test_override_values_never_appear_or_get_cleared(monkeypatch, executable, tmp_path):
    os.environ["ANTHROPIC_API_KEY"] = PRIVATE
    result = observation(monkeypatch, executable, tmp_path)
    assert result["override_names_present"] == ["ANTHROPIC_API_KEY"]
    assert os.environ["ANTHROPIC_API_KEY"] == PRIVATE
    assert_private(result)


def test_identity_mismatch_stops_before_status_process(monkeypatch, executable, tmp_path):
    path, _ = executable()
    calls = []
    monkeypatch.setattr(auth, "_probe", lambda *args: calls.append(args))
    result = auth.observe_auth(str(path), str(tmp_path), "0" * 64)
    assert calls == []
    assert result["reason_codes"] == ["identity_changed"]
    assert result["route_eligible"] is False


@pytest.mark.parametrize("digest", [None, "A" * 64, "0" * 63])
def test_invalid_review_identity_never_runs_probe(monkeypatch, executable, tmp_path, digest):
    path, _ = executable()

    def forbidden_probe(*args):
        pytest.fail("Probe must not run without the required reviewed identity")

    monkeypatch.setattr(auth, "_probe", forbidden_probe)
    result = auth.observe_auth(str(path), str(tmp_path), digest)
    assert result["reason_codes"] == ["invalid_expected_identity"]
    assert result["route_eligible"] is False


def test_replacement_during_probe_discards_otherwise_valid_login(monkeypatch, executable, tmp_path):
    path, digest = executable()

    def probe(*args):
        path.write_text(path.read_text() + "# replacement\n")
        return 0, json.dumps(VALID).encode()

    monkeypatch.setattr(auth, "_probe", probe)
    result = auth.observe_auth(str(path), str(tmp_path), digest)
    assert result["reason_codes"] == ["identity_changed"]
    assert result["logged_in"] is None
    assert result["route_eligible"] is False


def test_os_exception_details_are_sanitized(monkeypatch, executable, tmp_path):
    path, digest = executable()

    def probe(*args):
        raise OSError(PRIVATE)

    monkeypatch.setattr(auth, "_probe", probe)
    result = auth.observe_auth(str(path), str(tmp_path), digest)
    assert result["reason_codes"] == ["native_status_unreadable"]
    assert_private(result)
    with pytest.raises(PermissionError) as error:
        auth.require_subscription_route(str(path), str(tmp_path), digest)
    assert PRIVATE not in str(error.value)


def test_real_synthetic_probe_has_exact_arguments_cwd_environment_and_no_stdin(
    monkeypatch, executable, tmp_path,
):
    body = (
        "import json, os, sys\n"
        "assert sys.argv[1:] == ['auth', 'status', '--json']\n"
        f"assert os.getcwd() == {str(tmp_path)!r}\n"
        "assert os.environ['CHC_TEST_INHERITED'] == 'fixture'\n"
        "assert sys.stdin.buffer.read() == b''\n"
        f"print(json.dumps({{**{VALID!r}, 'email': {PRIVATE!r}}}))\n"
        f"print({PRIVATE!r}, file=sys.stderr)\n"
    )
    path, digest = executable(body)
    calls = []
    original = subprocess.Popen

    def recording_popen(*args, **kwargs):
        calls.append((args, kwargs))
        return original(*args, **kwargs)

    monkeypatch.setattr(auth.subprocess, "Popen", recording_popen)
    result = auth.observe_auth(str(path), str(tmp_path), digest)
    assert result["route_eligible"] is True
    assert len(calls) == 1
    kwargs = calls[0][1]
    assert kwargs.get("shell", False) is False
    assert "env" not in kwargs
    assert kwargs["stdin"] == subprocess.DEVNULL
    assert kwargs["stderr"] == subprocess.DEVNULL
    assert kwargs["start_new_session"] is True
    assert_private(result)


@pytest.mark.parametrize("failure", ["timeout", "oversize", "cancel_after_eof"])
def test_real_synthetic_failure_reaps_ignoring_child(monkeypatch, executable, tmp_path, failure):
    pid_file = tmp_path / "probe.pid"
    eof_file = tmp_path / "stdout.closed"
    body = (
        "import os, signal, time\n"
        "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
        f"open({str(pid_file)!r}, 'w').write(str(os.getpid()))\n"
    )
    if failure == "oversize":
        body += f"os.write(1, b'x' * {auth.MAX_OUTPUT + 1})\n"
    if failure == "cancel_after_eof":
        body += f"os.close(1)\nopen({str(eof_file)!r}, 'w').close()\n"
    body += "time.sleep(30)\n"
    path, digest = executable(body)
    monkeypatch.setattr(auth, "PROBE_TIMEOUT_SECONDS", 0.75)
    started = time.monotonic()
    kwargs = {}
    if failure == "cancel_after_eof":
        callbacks_after_close = 0

        def cancel_after_eof_read():
            nonlocal callbacks_after_close
            if eof_file.exists():
                callbacks_after_close += 1
            # Let the selector consume EOF before cancelling a still-running process.
            return callbacks_after_close >= 2

        kwargs["cancel_requested"] = cancel_after_eof_read
    result = auth.observe_auth(str(path), str(tmp_path), digest, **kwargs)
    assert time.monotonic() - started < 2
    assert result["route_eligible"] is False
    assert result["reason_codes"] == [{
        "timeout": "probe_timed_out", "oversize": "probe_output_too_large",
        "cancel_after_eof": "probe_cancelled",
    }[failure]]
    pid = int(pid_file.read_text())
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)
    assert_private(result)


@pytest.mark.parametrize("provider", ["bedrock", "vertex", "foundry"])
def test_oauth_token_cannot_authorize_other_providers(monkeypatch, executable, tmp_path, provider):
    result = observation(monkeypatch, executable, tmp_path, {
        **VALID, "authMethod": "oauth_token", "apiProvider": provider,
    })
    assert result["route_eligible"] is False
    assert_private(result)


def test_native_subscription_token_is_not_a_route_override(monkeypatch, executable, tmp_path):
    os.environ["CLAUDE_CODE_OAUTH_TOKEN"] = PRIVATE
    result = observation(monkeypatch, executable, tmp_path, {
        **VALID, "authMethod": "oauth_token", "subscriptionType": None,
    })
    assert result["route_eligible"] is False
    assert result["reason_codes"] == ["effective_route_not_attested"]
    assert result["override_names_present"] == []
    assert_private(result)
    os.environ["ANTHROPIC_API_KEY"] = PRIVATE
    assert observation(monkeypatch, executable, tmp_path)["route_eligible"] is False
