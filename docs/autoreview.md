# Native permission review acceptance

Harness Connect must preserve the native CLI permission mechanism. It must never synthesize approval from a parent task, answer a permission prompt automatically, or replace a native denial with a retry using weaker permissions.

Claude permits explicitly requested `--permission-mode=default` and `--permission-mode=auto` only when advertised by the reviewed installed CLI. Default uses native manual permissions; auto availability depends on native model and organization policy. A supplied flag alone does not prove the classifier ran. Interactive PTY is required for human permission dialogues. Print-mode completion does not establish interactive approval support.

Anthropic documents `setup-token` as subscription authentication for scripts: https://code.claude.com/docs/en/authentication#generate-a-long-lived-token . Native first-party `oauth_token` is recognized without inspecting token values or reconfirming the plan, but is held as `effective_route_not_attested`. Actual acceptance on 2026-10-01 returned firstParty OAuth login status while native init reported `glm-5.3-flashx`; login status alone cannot prove effective request routing. The acceptance job was cancelled and its terminal state verified; autoreview was not established. Billing and available quota remain unobserved. Remote Control and claude.ai connectors require different native authentication; this token must not imply those capabilities.

For every qualified adapter, live acceptance must establish: effective native permission mode; a permitted action; an action requiring review; native denial with no side effect; explicit human approval where required; cancellation during review; resumed-session permissions. Capture only bounded permission/progress events, never hidden reasoning or credentials. A denied action must not silently trigger mode changes or automatic restart.

Claude GLM, Grok and agy remain held pending their own route/policy qualification. Their native autoreview is not verified. Never apply Claude permission-mode flags to another CLI merely because it has a similar option name. No adapter can transfer Codex sandbox or autoreview enforcement automatically.

Current evidence: synthetic auth/adapter/launch/Grok tests pass (138 tests plus 74 subtests); they check route eligibility, forbidden option rejection and pre-launch behavior. Live native auto approval/denial acceptance and Desktop presentation remain pending. This is not a production certification.

## User-selected native default contract (alpha.14)
The user explicitly chose one Claude skill regardless of its configured model. The dedicated GLM plugin is removed. Claude launch/resume no longer calls subscription-route preflights and never injects a model/provider or changes native settings. auth_status is an optional diagnostic only. Native CLI authentication, errors, permission review and approvals remain its responsibility. The prior effective-route hold is historical evidence and no longer a launch gate. This contract does not certify third-party integrations or native auto-mode availability for every configured model.

## Alpha.15 native observation
A no-tool native-default acceptance returned a typed successful READY result on Claude Code 2.1.286,
model claude-opus-5-5. Native init reported bypassPermissions. The connector supplied no model or
permission-mode option. This verifies preservation/observation of native defaults, not autoreview.
Approval/denial acceptance must explicitly select native auto/default for that test; the global profile
must stay unchanged. Do not claim that native defaults necessarily enable autoreview.

An explicit `--permission-mode=auto` resume of that terminal job retained the same typed native
conversation ID and model, returned AUTO_READY, and terminated successfully. Native init reported
`default`, not `auto`. This proves resume continuity and an observed requested/effective mode mismatch;
it does not prove classifier activation or approval/denial behavior. Never retry with weaker permissions
or silently label this outcome as successful auto-review. The reason for native fallback is unestablished.

## Native tool acceptance on 2.1.286
A separate default-mode fixture job executed exactly Read and Edit, changing number.txt from 1 to 2.
Parent diff review and check_number.py validated FIXTURE_ACCEPTED. Native results contained no permission
denials or human approval prompt; existing native rules/hooks may permit tools in default mode. This is
an actual permitted-tool test, not classifier or manual-dialogue proof.

A bounded AskUserQuestion batch probe reported that the tool was unavailable; no call or permission denial
occurred. Unavailable interactive tools must be reported as unsupported, not bridged or answered by the
parent automatically. Native hook output may contain unrelated private context; parent-facing summaries
must exclude it rather than execute or publish it. Interactive approval/denial acceptance remains open.
