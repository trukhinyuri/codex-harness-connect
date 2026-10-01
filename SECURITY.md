# Security policy

Report security issues privately to the repository maintainer before publishing exploit details.
Do not include credentials, auth tokens, private transcripts or personal account data in issues.

The connector runs the user's installed native CLI; that CLI executes code and accesses files under
its own policies. MCP annotations are not a process sandbox, and Codex sandbox inheritance is not
asserted. Parent and native policies must both remain effective. Never use bypass/yolo as a compatibility
fix. Do not publish a subscription-backed multi-user service or proxy consumer tokens through this tool.

CLI identity changes require re-inventory. Unknown vendor output and uncertain exits are not success.
Local state must be private; socket/control inputs and event growth must be bounded. No automatic
inference retry, provider fallback, credential extraction, billing changes or background installer.
