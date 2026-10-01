# Native permission review acceptance

Harness Connect must preserve the native CLI permission mechanism. It must never synthesize approval from a parent task, answer a permission prompt automatically, or replace a native denial with a retry using weaker permissions.

Claude permits explicitly requested `--permission-mode=default` and `--permission-mode=auto` only when advertised by the reviewed installed CLI. Default uses native manual permissions; auto availability depends on native model and organization policy. A supplied flag alone does not prove the classifier ran. Interactive PTY is required for human permission dialogues. Print-mode completion does not establish interactive approval support.

Claude launch and resume use the current native model, provider and settings. They do not require subscription or route diagnostics. Optional `auth_status` cannot attest to effective routing, quota or billing. The connector never changes authentication or introduces a paid fallback. A historical alpha.12 test observed first-party OAuth status alongside a `glm-5.3-flashx` native init; its later effective-route hold was explicitly superseded by the user's single-Claude contract in alpha.14. That historical hold must not be applied to current launches.

For every qualified adapter, live acceptance must establish: effective native permission mode; a permitted action; an action requiring review; native denial with no side effect; explicit human approval where required; cancellation during review; resumed-session permissions. Capture only bounded permission/progress events, never hidden reasoning or credentials. A denied action must not silently trigger mode changes or automatic restart.

The separate Claude GLM plugin has been removed. Grok and agy retain their own route/policy holds; their native autoreview is not verified. Never apply Claude permission-mode flags to another CLI merely because it has a similar option name. No adapter can transfer Codex sandbox or autoreview enforcement automatically.

Alpha.17 synthetic validation passed 554 tests and 74 subtests. These tests cover connector behavior, including forbidden option rejection and preservation of other adapters' holds; they do not establish live native classifier decisions. Live native auto approval/denial acceptance and Desktop presentation remain pending. This is not a production certification.

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

A subsequent interactive PTY probe selected native default permissions in the user's explicitly trusted
fixture. After the existing workspace trust was acknowledged, native Claude returned API 429 / 1311
and retried before presenting the requested question. The connector cancelled the job and verified
`cancelled`, `live=false` and `worker_alive=false`. This is a vendor/runtime error observation, not an
autoreview denial or proof of interactive approval support. No model, login or subscription was changed.
