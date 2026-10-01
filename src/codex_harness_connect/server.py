"""Codex-facing MCP tools; process lifetime is owned by the independent session worker."""
from __future__ import annotations

from pathlib import Path
from typing import Annotated

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import Field

from .adapters import ADAPTERS, get_adapter, launch_contract
from .discovery import inventory
from .history import list_history
from .revalidation import revalidate
from .sessions import SessionService
from .waiting import WaitTarget, wait_for_sessions
from .worktrees import create_worktree

READ = ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False)
WRITE = ToolAnnotations(readOnlyHint=False, destructiveHint=True, openWorldHint=True)


def build_server(state_root: Path, profile: str | None = None) -> FastMCP:
    if profile:
        get_adapter(profile)
    # Each scoped plugin can control only its own harness. The universal plugin can
    # coordinate the same per-harness stores; a native id never crosses namespaces.
    pools = {name: SessionService(state_root / name) for name in ([profile] if profile else ADAPTERS)}
    server = FastMCP("codex-harness-connect", log_level="WARNING", instructions=(
        "Local native CLI orchestration. Inventory is not permission or full feature proof. "
        "Use only authorized task context. Keep native permissions; never bypass or change auth. "
        "Policy-held adapters cannot launch. Start once, wait with cursors and drain events; cancel explicitly and "
        "verify terminal state. A failed MCP call does not prove the worker stopped. "
        "Codex memory, sandbox and native subagent UI are not automatically inherited."
    ))

    def selected(adapter: str) -> str:
        if profile and adapter != profile:
            raise ValueError("This plugin is scoped to another harness")
        get_adapter(adapter)
        return adapter

    def owner(session_id: str) -> SessionService:
        for service in pools.values():
            try:
                service.status(session_id, limit=1)
                return service
            except KeyError:
                continue
        raise KeyError("Session is absent from this plugin's harness scope")

    @server.tool(annotations=READ)
    def describe_adapter(adapter: str) -> dict:
        """Read native adapter scope, policy and primary-source links. No model request."""
        item = get_adapter(selected(adapter))
        return {"name": item.name, "executable": item.executable, "policy": item.policy,
                "sources": list(item.sources), "notes": item.notes,
                "production_verified": False, "desktop_parity": "not established"}

    @server.tool(annotations=READ)
    def inventory_cli(adapter: str) -> dict:
        """Probe a registered trusted CLI's --version/--help. No authentication or model call."""
        return inventory(get_adapter(selected(adapter)).executable)

    @server.tool(annotations=WRITE)
    def revalidate_cli(adapter: str) -> dict:
        """Fresh CLI/host/runtime observation and drift invalidation; no model or auth call.

        Writes a private observation ledger. Full policy and native/Desktop acceptance remain
        required even when identities are unchanged. This does not certify latest versions.
        """
        return revalidate(selected(adapter), state_root)

    if profile is None:
        @server.tool(annotations=WRITE)
        def inventory_candidate(executable: str) -> dict:
            """Read --help/--version of an explicitly user-designated trusted installed CLI.

            Executing an unknown binary is not safe merely because its argument is --help.
            Obtain user designation first. This probe neither registers nor launches an adapter.
            """
            return inventory(executable)

    @server.tool(annotations=WRITE)
    def start_session(adapter: str, prompt: str, cwd: str, expected_sha256: str, request_id: str,
                      mode: str = "interactive", native_options: list[str] | None = None,
                      timeout_seconds: int = 3600,
                      batch_workspace_confirmation: str | None = None) -> dict:
        """Start authorized native work; this is not a Codex subagent.

        Batch skips Claude's workspace trust dialog. Only supply its exact resolved path after
        explicit user authorization that this directory is trusted for native hooks/settings.
        The field is an acknowledgement, not an enforced filesystem sandbox or tool approval.
        """
        contract = launch_contract(selected(adapter), prompt, cwd, mode, expected_sha256,
                                   options=native_options,
                                   batch_workspace_confirmation=batch_workspace_confirmation)
        job = pools[adapter].start(contract["argv"], contract["cwd"], contract["mode"],
                             timeout_seconds=timeout_seconds, request_id=request_id,
                             protocol=contract["protocol"])
        return {"job": job, "adapter": adapter, "permissions": contract["permissions"],
                "native_session_id": None, "readiness": "running does not mean task complete"}

    @server.tool(annotations=WRITE)
    def resume_session(adapter: str, source_session_id: str, prompt: str, cwd: str,
                       expected_sha256: str, request_id: str, mode: str = "interactive",
                       timeout_seconds: int = 3600,
                       batch_workspace_confirmation: str | None = None) -> dict:
        """Resume a verified native conversation id in a new OS job. No 'most recent' guessing."""
        selected(adapter)
        source = pools[adapter].status(source_session_id)["session"]
        native_session_id = source["native_session_id"]
        if not native_session_id or source["protocol"] != "claude-stream-json":
            raise ValueError("Source job has no verified native conversation ID")
        if source["status"] not in {"completed", "failed", "cancelled", "timed_out"}:
            raise ValueError("Source job must have a recorded terminal state before resuming")
        if source["cwd"] != str(Path(cwd).resolve(strict=True)):
            raise ValueError("Resume must use the source job's workspace")
        c = launch_contract(selected(adapter), prompt, cwd, mode, expected_sha256, native_session_id,
                            batch_workspace_confirmation=batch_workspace_confirmation)
        return pools[adapter].start(c["argv"], c["cwd"], c["mode"], timeout_seconds=timeout_seconds,
                                   request_id=request_id, protocol=c["protocol"])

    @server.tool(annotations=READ)
    def lookup_request(adapter: str, request_id: str) -> dict:
        """Recover a start/resume job after an uncertain response, without another model request."""
        selected(adapter)
        return pools[adapter].lookup_request(request_id)

    @server.tool(annotations=READ)
    def session_events(session_id: str, after: int = 0, limit: int = 100) -> dict:
        """Read live state plus a durable bounded event page; retain next_cursor for reconnect."""
        return owner(session_id).status(session_id, after, limit)

    @server.tool(annotations=READ)
    async def wait_sessions(
        targets: list[WaitTarget],
        timeout_seconds: Annotated[float, Field(strict=True, ge=0, le=45, allow_inf_nan=False)] = 30,
    ) -> dict:
        """Wait up to 45s for existing jobs to change; no model launch or job cancellation.

        Supply each acknowledged event cursor. The compact response does not consume events;
        drain session_events using that cursor before advancing it. Cancelling this wait leaves
        the native jobs running; stopping a job requires explicit cancel_session and verification.
        """
        if not 1 <= len(targets) <= 8:
            raise ValueError("Wait requires 1..8 existing jobs")
        services = {}

        def read_status(session_id, after, limit):
            # Ownership probes are read-only and run inside the wait's thread/deadline,
            # so a blocked filesystem cannot block the MCP event loop or cancellation.
            if session_id not in services:
                services[session_id] = owner(session_id)
            return services[session_id].status(session_id, after=after, limit=limit)

        return await wait_for_sessions(targets, read_status, timeout_seconds=timeout_seconds)

    @server.tool(annotations=READ)
    def list_sessions(
        adapter: Annotated[str | None, Field(strict=True, max_length=32)] = None,
        limit: Annotated[int, Field(strict=True, ge=1, le=50)] = 20,
        cursor: Annotated[str | None, Field(strict=True, max_length=65)] = None,
    ) -> dict:
        """List at most 50 compact connector jobs in at most 64 KiB; no model request.

        Adapters sort alphabetically; jobs sort by created_at/session_id descending
        within an adapter. Pass next_cursor unchanged for continuation. Selecting
        an adapter requires a cursor from that adapter. Cursors name existing jobs.
        """
        return list_history(pools, adapter=adapter, limit=limit, cursor=cursor)

    @server.tool(annotations=READ)
    def storage_status(adapter: str) -> dict:
        """Read capacity, logical event budgets and measured DB/WAL bytes; no cleanup."""
        return pools[selected(adapter)].storage_status()

    @server.tool(annotations=WRITE)
    def send_input(session_id: str, text: str) -> dict:
        """Send explicitly authorized native TUI input, including user answers; never auto-approve."""
        return owner(session_id).send(session_id, text)

    @server.tool(annotations=WRITE)
    def close_input(session_id: str) -> dict:
        """Request EOF; this is not cancellation and an active turn may continue."""
        return owner(session_id).close_input(session_id)

    @server.tool(annotations=WRITE)
    def cancel_session(session_id: str) -> dict:
        """Cancel a connector worker and its child process group; read final state to verify."""
        return owner(session_id).cancel(session_id)

    @server.tool(annotations=WRITE)
    def new_worktree(repository: str, name: str, base: str = "HEAD") -> dict:
        """Create a user-owned git worktree for an explicitly authorized parallel task."""
        return create_worktree(repository, name, base)

    @server.resource("harness://capabilities")
    def capabilities() -> dict:
        return {"adapters": [profile] if profile else list(ADAPTERS),
                "native_picker": False, "automatic_memory_transfer": False,
                "automatic_sandbox_inheritance": False, "hosted_cloud": "not verified",
                "external_native_teams": "interactive CLI only where supported and enabled"}

    return server
