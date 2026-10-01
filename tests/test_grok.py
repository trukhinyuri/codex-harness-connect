import json
import unittest

from codex_harness_connect.grok import (
    MAX_ERRORS,
    GrokJsonParser,
    build_grok_argv,
    require_grok_subscription_route,
)

SID = "a584329b-986c-422d-94b2-706b792a34ec"
OTHER_SID = "02628736-a0d7-47dd-b81f-58604d32717a"
EXE = "/native/grok"


def terminal(**updates):
    value = {"text": "completed", "stopReason": "end_turn", "sessionId": SID, "requestId": ""}
    value.update(updates)
    return json.dumps(value)


def parse(raw, code=0, **limits):
    parser = GrokJsonParser(SID, **limits)
    parser.feed(raw)
    return parser.finish(code)


class GrokArgvTests(unittest.TestCase):
    def test_new_batch_uses_owned_uuid_and_native_policy(self):
        argv = build_grok_argv(EXE, "inspect only", "batch", subscription_entitlement_confirmed=True, new_session_id=SID, max_turns=3)
        self.assertEqual(argv, [EXE, f"--session-id={SID}", "--max-turns=3", "--output-format=json", "--single=inspect only"])

    def test_interactive_resume_keeps_native_approval_ui(self):
        argv = build_grok_argv(EXE, "login", "interactive", subscription_entitlement_confirmed=True, native_session_id=SID)
        self.assertEqual(argv, [EXE, f"--resume={SID}", "--", "login"])
        self.assertNotIn("--session-id", " ".join(argv))

    def test_native_permissions_are_not_overridden(self):
        forbidden = ("--permission-mode", "--allow", "--deny", "--always-approve", "--yolo", "--dangerously-skip-permissions", "--trust")
        for mode in ("batch", "interactive"):
            argv = build_grok_argv(EXE, "inspect only", mode, subscription_entitlement_confirmed=True, new_session_id=SID)
            for flag in forbidden:
                with self.subTest(mode=mode, flag=flag):
                    self.assertFalse(any(arg == flag or arg.startswith(flag + "=") for arg in argv))

    def test_prompt_and_value_flags_cannot_become_options(self):
        for mode in ("batch", "interactive"):
            argv = build_grok_argv(EXE, "--always-approve", mode, subscription_entitlement_confirmed=True, new_session_id=SID)
            self.assertNotIn("--always-approve", argv[:-1])
            if mode == "batch":
                self.assertEqual(argv[-1], "--single=--always-approve")
            else:
                self.assertEqual(argv[-2:], ["--", "--always-approve"])

    def test_entitlement_is_explicit_boolean(self):
        for value in (False, None, 1, "true"):
            with self.subTest(value=value), self.assertRaises(PermissionError):
                build_grok_argv(EXE, "prompt", "batch", subscription_entitlement_confirmed=value, new_session_id=SID)

    def test_versions_and_session_identity_are_reviewed(self):
        cases = [
            {"installed_version": "1.0.45", "new_session_id": SID},
            {"new_session_id": SID, "native_session_id": OTHER_SID},
            {},
            {"new_session_id": "--always-approve"},
            {"native_session_id": "same-title"},
        ]
        for options in cases:
            with self.subTest(options=options), self.assertRaises(ValueError):
                build_grok_argv(EXE, "prompt", "batch", subscription_entitlement_confirmed=True, **options)

    def test_invalid_input_and_no_passthrough_surface(self):
        for updates in ({"executable": "grok"}, {"prompt": ""}, {"prompt": "x\x00y"}, {"mode": "automatic"}, {"max_turns": True}, {"max_turns": 0}):
            params = dict(executable=EXE, prompt="prompt", mode="batch", subscription_entitlement_confirmed=True, new_session_id=SID)
            params.update(updates)
            with self.subTest(updates=updates), self.assertRaises(ValueError):
                build_grok_argv(**params)
        for forbidden in ("options", "model", "env", "always_approve", "oauth", "no_auto_update"):
            with self.subTest(forbidden=forbidden), self.assertRaises(TypeError):
                build_grok_argv(EXE, "prompt", "batch", subscription_entitlement_confirmed=True, new_session_id=SID, **{forbidden: True})

    def test_entitlement_or_login_policy_never_proves_effective_route(self):
        for policy in (None, False, True):
            with self.subTest(policy=policy), self.assertRaisesRegex(PermissionError, "route unverified"):
                require_grok_subscription_route(subscription_entitlement_confirmed=True, api_key_auth_disabled=policy)
        with self.assertRaises(PermissionError):
            require_grok_subscription_route(subscription_entitlement_confirmed=False)


class GrokJsonTests(unittest.TestCase):
    def test_chunked_pretty_final_result_and_empty_request_id(self):
        value = terminal(text="done ✓", thought="private reasoning", usage={"inputTokens": 2})
        parser = GrokJsonParser(SID)
        for chunk in (value[:3], value[3:21], value[21:], "\n"):
            parser.feed(chunk)
        result = parser.finish(0)
        self.assertEqual(result["semantic_status"], "succeeded")
        self.assertEqual(result["native_session_id"], SID)
        self.assertTrue(result["identity_verified"])
        self.assertEqual(result["request_id"], "")
        self.assertEqual(result["text_preview"], "done ✓")
        self.assertNotIn("thought", result)
        self.assertEqual(result["errors"], [])

    def test_only_end_turn_with_clean_exit_succeeds(self):
        for reason in ("max_tokens", "max_turn_requests", "refusal", "cancelled"):
            with self.subTest(reason=reason):
                result = parse(terminal(stopReason=reason))
                self.assertEqual(result["semantic_status"], "failed")
                self.assertTrue(result["identity_verified"])
        self.assertEqual(parse(terminal(), code=1)["semantic_status"], "failed")
        self.assertEqual(parse(terminal(), code=-15)["semantic_status"], "failed")

    def test_native_error_has_no_identity_even_on_zero_exit(self):
        for code in (0, 1):
            result = parse(json.dumps({"type": "error", "message": "Not signed in"}), code)
            self.assertEqual(result["semantic_status"], "failed")
            self.assertFalse(result["identity_verified"])
            self.assertIsNone(result["native_session_id"])

    def test_bounded_preview_and_structured_error(self):
        result = parse(terminal(text="abcdefgh", structuredOutput=None, structuredOutputError="bad schema"), max_preview_chars=3)
        self.assertEqual(result["text_preview"], "abc")
        self.assertEqual(result["structured_output_error_preview"], "bad")
        self.assertEqual(result["semantic_status"], "failed")

    def test_schema_identity_and_future_tokens_fail_closed(self):
        cases = [
            "", "[]", "42", "null", "{}", "truncated {", "a warning\n" + terminal(),
            terminal() + "\n" + terminal(),
            terminal(sessionId=OTHER_SID), terminal(sessionId="same-title"),
            terminal(sessionId=None), terminal(text=42), terminal(stopReason="EndTurn"),
            terminal(stopReason="new_stop"), terminal(requestId=None),
            terminal(requestId="x\x00y"), terminal(requestId="x" * 1025),
            terminal(text="\ud800"), terminal(requestId="\ud800"),
            terminal(thought=[]), terminal(structuredOutputError=False),
            terminal(type="result"), terminal(type="error", message="mixed"),
        ]
        for raw in cases:
            with self.subTest(raw=raw[:80]):
                result = parse(raw)
                self.assertEqual(result["semantic_status"], "unknown")
                self.assertFalse(result["identity_verified"])
                self.assertIsNone(result["native_session_id"])
                self.assertGreater(len(result["errors"]), 0)
                self.assertLessEqual(len(result["errors"]), MAX_ERRORS)

    def test_duplicates_nonfinite_and_nested_extra_data_are_rejected(self):
        cases = [
            terminal()[:-1] + ', "sessionId": "' + SID + '"}',
            terminal()[:-1] + ', "usage": {"a": 1, "a": 2}}',
            terminal()[:-1] + ', "usage": NaN}',
            terminal()[:-1] + ', "usage": Infinity}',
            terminal()[:-1] + ', "extra": ' + "[" * 65 + "0" + "]" * 65 + "}",
        ]
        for raw in cases:
            with self.subTest(raw=raw[-80:]):
                self.assertEqual(parse(raw)["semantic_status"], "unknown")

    def test_unrecognized_json_identity_cannot_override_native_uuid(self):
        result = parse(terminal(nativeSessionId=OTHER_SID, session_id=OTHER_SID, nested={"sessionId": OTHER_SID}))
        self.assertEqual(result["native_session_id"], SID)

    def test_byte_limit_handles_unicode_and_latches_truncation(self):
        parser = GrokJsonParser(SID, max_output_bytes=4)
        parser.feed("✓✓")
        parser.feed(terminal())
        result = parser.finish(0)
        self.assertEqual(result["output_bytes"], 6)
        self.assertEqual(result["semantic_status"], "unknown")
        self.assertLessEqual(len(result["errors"]), MAX_ERRORS)
        self.assertEqual(parser._chunks, [])

    def test_json_depth_scan_ignores_brackets_inside_strings(self):
        self.assertEqual(parse(terminal(text="[" * 100 + '"\\'))["semantic_status"], "succeeded")

    def test_many_tiny_feeds_do_not_allocate_a_list_entry_per_character(self):
        parser = GrokJsonParser(SID)
        raw = terminal(text="a" * 40_000)
        for char in raw:
            parser.feed(char)
        self.assertLessEqual(len(parser._chunks), 3)
        self.assertEqual(parser.finish(0)["semantic_status"], "succeeded")

    def test_invalid_unicode_and_invalid_limits(self):
        self.assertEqual(parse("\ud800")["semantic_status"], "unknown")
        for limits in ({"max_output_bytes": 0}, {"max_output_bytes": True}, {"max_preview_chars": -1}, {"max_preview_chars": True}):
            with self.subTest(limits=limits), self.assertRaises(ValueError):
                GrokJsonParser(SID, **limits)
        with self.assertRaises(ValueError):
            GrokJsonParser("bad-id")

    def test_finish_is_defensive_idempotent_and_terminal(self):
        parser = GrokJsonParser(SID)
        parser.feed(terminal())
        result = parser.finish(0)
        result["errors"].append("mutation")
        self.assertEqual(parser.finish(0)["errors"], [])
        with self.assertRaises(RuntimeError):
            parser.feed("more")
        with self.assertRaises(RuntimeError):
            parser.finish(1)
        with self.assertRaises(ValueError):
            parser.finish(True)


if __name__ == "__main__":
    unittest.main()
