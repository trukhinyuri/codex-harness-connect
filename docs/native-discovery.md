# Claude help transport

Registered Claude and Claude + GLM inventories use a bounded PTY for `--help`. Version and auth
status probes still use pipes. Other registered CLIs and unregistered candidates retain their
reviewed/default pipe transport. This does not change model, authentication, native permissions or
workspace-trust handling. The GLM launch-policy hold remains in effect.

On the observed macOS host, Claude Code 2.1.286 returned exit code 0 with incomplete pipe help:
`subprocess.communicate` received 1,024 bytes and the bounded inventory reader received 512 bytes.
Required stream flags were absent from those partial outputs. Three PTY probes each received the
same 22,664-byte output, containing 72 detected long flags and the Commands section. These are
observations on one version and host, not a claim about every Claude installation or the internal
cause. Separate inventories had also received complete pipe output, so exit code alone cannot
establish completeness.

The fix selects PTY explicitly for the reviewed Claude help contract. It does not retry a model
request, manufacture missing flags, reuse a cached green inventory or fall back to guessed arguments.
Launch still refuses missing required flags and executable-identity drift. Inventory records
`help_transport`, retains raw help for its hash, and removes terminal CSI styling only when extracting
flag tokens. A detected token is still not proof of complete command coverage.

The probe closes stdin, caps output at 256,000 bytes, enforces the existing nominal 15-second deadline
and closes both PTY descriptors. Terminal EOF/EIO is handled explicitly. Cleanup terminates the
probe's process group and adds bounded grace time. The separate full macOS daemon-containment
acceptance test fails, as documented in [the current limits](../README.md#current-verified-limits).
PTY output can differ from pipe output, including line endings. Revalidation therefore invalidates
earlier target-help evidence when its transport or content changes.

Synthetic transport tests and current installed/native outcomes are recorded separately in
[status](status.md). The [CLI reference](https://code.claude.com/docs/en/cli-reference) documents native
help and stream flags; this project's transport choice is an evidence-based adapter correction,
not a vendor endorsement.
