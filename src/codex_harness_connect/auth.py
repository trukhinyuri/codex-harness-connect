"""Sanitized native Claude auth observations; never a billing or credential broker."""
from __future__ import annotations

import json
import os
import re
import selectors
import signal
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path

from .discovery import file_fingerprint, resolve_executable

MAX_OUTPUT = 64 * 1024
PROBE_TIMEOUT_SECONDS = 10
# Presence is a conservative hold, including empty values. Never clear or print values.
ROUTE_OVERRIDES = frozenset({
    "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL",
    "ANTHROPIC_CUSTOM_HEADERS", "ANTHROPIC_PROFILE", "ANTHROPIC_FEDERATION_RULE_ID",
    "ANTHROPIC_ORGANIZATION_ID", "ANTHROPIC_WORKSPACE_ID", "ANTHROPIC_AWS_API_KEY",
    "ANTHROPIC_AWS_BASE_URL", "ANTHROPIC_AWS_WORKSPACE_ID", "ANTHROPIC_BEDROCK_BASE_URL",
    "ANTHROPIC_BEDROCK_MANTLE_BASE_URL", "CLAUDE_CONFIG_DIR", "CLAUDE_CODE_OAUTH_TOKEN",
    "ANTHROPIC_FOUNDRY_API_KEY", "ANTHROPIC_FOUNDRY_AUTH_TOKEN",
    "ANTHROPIC_FOUNDRY_BASE_URL", "ANTHROPIC_FOUNDRY_RESOURCE",
    "ANTHROPIC_VERTEX_BASE_URL", "ANTHROPIC_VERTEX_PROJECT_ID", "AWS_BEARER_TOKEN_BEDROCK",
    "CLAUDE_CODE_OAUTH_TOKEN_FILE_DESCRIPTOR", "CLAUDE_CODE_USE_BEDROCK",
    "CLAUDE_CODE_USE_VERTEX", "CLAUDE_CODE_USE_FOUNDRY",
    "CLAUDE_CODE_PROVIDER_MANAGED_BY_HOST", "CLAUDE_CODE_SIMPLE",
    "CLAUDE_CODE_API_KEY_HELPER_TTL_MS", "CLAUDE_CODE_PROCESS_WRAPPER",
    "CLAUDE_CODE_SKIP_ANTHROPIC_AWS_AUTH", "CLAUDE_CODE_SKIP_BEDROCK_AUTH",
    "CLAUDE_CODE_SKIP_FOUNDRY_AUTH", "CLAUDE_CODE_SKIP_MANTLE_AUTH", "CLAUDE_CODE_SKIP_VERTEX_AUTH",
    "CLAUDE_CODE_OAUTH_REFRESH_TOKEN", "CLAUDE_CODE_OAUTH_SCOPES",
})
_ENUMS = {
    "authMethod": ("auth_method", {"none", "claude.ai", "api_key"}),
    "apiProvider": ("api_provider", {"firstParty", "bedrock", "vertex", "foundry"}),
    "subscriptionType": ("subscription_type", {"pro", "max", "team", "enterprise"}),
}


class ProbeError(Exception):
    """A fixed, non-sensitive probe failure code."""


def _probe(path: Path, cwd: Path, *, cancel_requested=None) -> tuple[int, bytes]:
    process = subprocess.Popen(
        [str(path), "auth", "status", "--json"], cwd=str(cwd), stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, start_new_session=True,
        close_fds=True,
    )
    raw = bytearray()
    deadline = time.monotonic() + PROBE_TIMEOUT_SECONDS

    def stop(sig):
        try:
            os.killpg(process.pid, sig)
        except ProcessLookupError:
            pass
        except PermissionError:
            if process.poll() is None:
                raise ProbeError("probe_cleanup_failed") from None

    try:
        with selectors.DefaultSelector() as selector:
            os.set_blocking(process.stdout.fileno(), False)
            selector.register(process.stdout, selectors.EVENT_READ)
            output_open = True
            while True:
                if cancel_requested is not None and cancel_requested():
                    raise ProbeError("probe_cancelled")
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise ProbeError("probe_timed_out")
                if not output_open:
                    if process.poll() is not None:
                        break
                    time.sleep(min(remaining, 0.05))
                    continue
                if not selector.select(min(remaining, 0.05)):
                    continue
                try:
                    chunk = os.read(process.stdout.fileno(), min(65536, MAX_OUTPUT + 1 - len(raw)))
                except BlockingIOError:
                    continue
                if not chunk:
                    selector.unregister(process.stdout)
                    output_open = False
                    continue
                raw.extend(chunk)
                if len(raw) > MAX_OUTPUT:
                    raise ProbeError("probe_output_too_large")
    finally:
        try:
            stop(signal.SIGTERM)
            try:
                process.wait(timeout=0.2)
            except subprocess.TimeoutExpired:
                pass
        finally:
            try:
                stop(signal.SIGKILL)
                try:
                    process.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    raise ProbeError("probe_cleanup_failed") from None
            finally:
                process.stdout.close()
    return process.returncode, bytes(raw)


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate field")
        result[key] = value
    return result


def _invalid_constant(_value):
    raise ValueError("non-standard JSON constant")


def observe_auth(executable: str, cwd: str, expected_sha256: str, *, cancel_requested=None) -> dict:
    """Run only a reviewed native status command in the intended launch environment/cwd.

    No shell, model, login, setting change, credential-file read or raw-output persistence.
    Claude handles its own auth internals. Settings/hooks can still change later routing;
    this observation cannot establish quota, usage-credit state or future billing.
    """
    result = {
        "observed_at": datetime.now(UTC).isoformat(), "status": "probe_error",
        "route_eligible": False, "logged_in": None, "auth_method": None,
        "api_provider": None, "subscription_type": None, "reason_codes": [],
        "override_names_present": sorted(ROUTE_OVERRIDES.intersection(os.environ)),
        "binary_sha256": None, "billing_guarantee": False,
        "included_quota_remaining": "not_observed", "usage_credits_status": "not_observed",
    }
    try:
        if not isinstance(expected_sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", expected_sha256):
            raise ProbeError("invalid_expected_identity")
        directory = Path(cwd).resolve(strict=True)
        if not directory.is_dir():
            raise ProbeError("invalid_workspace")
        path = resolve_executable(executable)
        before = file_fingerprint(path)
        if before["sha256"] != expected_sha256:
            raise ProbeError("identity_changed")
        result["binary_sha256"] = expected_sha256
        code, raw = (_probe(path, directory) if cancel_requested is None else
                     _probe(path, directory, cancel_requested=cancel_requested))
        if resolve_executable(executable) != path or file_fingerprint(path) != before:
            raise ProbeError("identity_changed")
        data = json.loads(raw.decode("utf-8", errors="strict"), object_pairs_hook=_unique_object,
                          parse_constant=_invalid_constant)
        if not isinstance(data, dict) or type(data.get("loggedIn")) is not bool:
            raise ProbeError("invalid_auth_schema")
        result["logged_in"] = data["loggedIn"]
        for source, (target, values) in _ENUMS.items():
            value = data.get(source)
            if value is None and source == "subscriptionType":
                continue
            if not isinstance(value, str) or value not in values:
                raise ProbeError("unknown_auth_schema")
            result[target] = value
        if code != (0 if data["loggedIn"] else 1):
            raise ProbeError("inconsistent_auth_exit")
        if result["override_names_present"]:
            result.update(status="held", reason_codes=["auth_or_route_override_present"])
        elif not result["logged_in"]:
            result.update(status="not_authenticated", reason_codes=["native_auth_unavailable"])
        elif (result["auth_method"] == "claude.ai" and result["api_provider"] == "firstParty"
              and result["subscription_type"] in {"pro", "max", "team", "enterprise"}):
            result.update(status="subscription_route_observed", route_eligible=True)
        else:
            result.update(status="held", reason_codes=["own_subscription_route_not_observed"])
    except ProbeError as exc:
        result["reason_codes"] = [str(exc)]
    except (OSError, ValueError, TypeError, RecursionError):
        result["reason_codes"] = ["native_status_unreadable"]
    return result


def require_subscription_route(executable: str, cwd: str, expected_sha256: str,
                               *, cancel_requested=None) -> dict:
    observation = (observe_auth(executable, cwd, expected_sha256) if cancel_requested is None else
                   observe_auth(executable, cwd, expected_sha256, cancel_requested=cancel_requested))
    if not observation["route_eligible"]:
        raise PermissionError("Claude own-subscription launch held: "
                              + ", ".join(observation["reason_codes"]))
    return observation
