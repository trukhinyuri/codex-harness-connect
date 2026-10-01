# Repeated connection and compatibility maintenance

`connect_harness_cli` is the display label; `connect-harness-cli` is the skill identifier.
Package IDs and MCP server names remain stable. Alpha.3 adds `revalidate_cli(adapter)` to each scoped
server and the router, and `codex-harness-connect revalidate <adapter> --state-root <private-directory>`.
The skill requires fresh observation on every invocation, even if a previous invocation succeeded.
These instructions govern the parent agent; MCP observation alone does not execute the full acceptance
workflow or enforce completion. Direct start_session still checks the native binary and launch flags.

The observation checks target executable identity, version/help, PATH Codex, discovered Desktop bundle
and bundled Codex, and connector files on disk plus dependency version metadata. These fingerprints do not prove the
loaded Python code, every native launcher payload dependency or the whole Desktop app resource tree;
a fresh installed server and host schema/tool invocation are separate required evidence. It compares a bounded private
snapshot with the previous observation. A changed, missing or unknown identity invalidates prior
qualification. Version/help probes must describe one unchanged executable; a binary or symlink update
mid-probe rejects the inventory. No automatic retry launches another probe or model task.

The fingerprint is evidence binding, not a compatibility certificate. An unchanged fingerprint does
not confirm current terms, available updates, live UI behavior or native feature coverage. The returned
qualification remains incomplete until the parent performs and records the acceptance workflow.
The observation neither runs inference nor reads credentials, imports vendor configuration, installs,
updates or logs in. Native version commands can have their own vendor-defined side effects.

## Required maintenance procedure

1. Preserve the original outcome tree, destination, R1–R16 gates and user defaults/budget. Read the fresh
   observation and check the native Desktop updater separately when available. Distinguish installed,
   running and available versions. Do not claim the installed binary is the newest release from --version.
2. Review current official docs, release notes, terms and source as available. Inspect recursive commands,
   interactive features, output/control schemas, native auth/billing route and version constraints.
   Retain contradictory evidence and applicable vendor holds.
3. Bind the capability dossier to observation fingerprint, versions, date and actual test host. Compare
   old evidence, implement affected API/protocol fixes and supported improvements, and review changes.
   Use staged package replacement and rollback; generation itself refuses existing files.
4. Run affected tests and required regression checks. On a permitted existing subscription route, verify
   real final results, denial/approval, resume, long tasks, cancellation/descendants, MCP reconnect,
   uncertain-request recovery, parallel worktrees, native teams and CLI customizations as applicable.
   An unavailable feature needs an official source and limitation, not a fabricated passing test.
5. Verify installed tools from current Codex CLI and Desktop. Check progress, questions, approvals, stop,
   continuation and file review in the host UI through a permitted interface. Check skills/AGENTS.md,
   context, memory, plugins/MCP, worktrees and permissions individually: automatic preservation in the
   parent is different from explicit context passed to a child. Cloud requires its own deployment/tests.
6. Re-observe after fixes/install. If identity changed during validation, repeat affected qualification.
   Report documented capability, research inference, synthetic tests and actual acceptance separately.
   Full task completion requires original gates; expose missing evidence and next actions.

## Supported mechanisms and limits

Use the [documented marketplace mechanism](https://developers.openai.com/plugins/build/plugins)
and the commands actually exposed by the installed CLI. The current
[app-server documentation](https://learn.chatgpt.com/docs/app-server) marks plugin/list, plugin/read,
plugin/install and plugin/uninstall as under development and unsuitable for production clients.
Earlier bounded alpha diagnostics are not a production dependency or official endorsement.

Desktop bundle metadata does not prove the foreground app or UI compatibility. A denied computer-use
interface must not be bypassed. Installing a local plugin does not deploy its process into Cloud.
The existing Grok/agy policy holds and failed full macOS containment gate remain. This release
improves drift observation and the maintenance workflow; it does not solve these independent gates.

The current [MCP Events documentation](https://developers.openai.com/plugins/build/mcp-events) describes
ChatGPT webhook subscriptions requiring MCP 2.0 and outbound HTTPS. It does not establish a supported
local stdio streaming-progress UI for this connector. Adding remote callbacks/secrets merely to imitate
native agent events would introduce a different deployment and security contract; it is not included in
this local alpha. Native host UX needs its own measured acceptance through supported interfaces.
