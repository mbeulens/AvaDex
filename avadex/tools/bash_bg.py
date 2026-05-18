"""Background bash jobs for AvaDex.

A single-process CLI tracks subprocesses launched by the model and lets
the model query their output and lifecycle. Output is pumped from the
subprocess stdout (merged with stderr) into a list by a daemon thread,
so bash_output never blocks on the process. Module-level state — same
philosophy as avadex/tools/todos.py — is fine for a single-user CLI.
"""
from __future__ import annotations

import shlex
import subprocess
import threading
from typing import Optional

from avadex.tools.registry import ToolDefinition, ToolResult


_JOBS: dict[str, dict] = {}
_LOCK = threading.Lock()
_NEXT_ID = [0]


def _next_job_id() -> str:
    with _LOCK:
        _NEXT_ID[0] += 1
        return f"bg{_NEXT_ID[0]}"


def _reset_for_tests() -> None:
    """Test helper — terminate any live jobs and clear the registry."""
    with _LOCK:
        for job in _JOBS.values():
            proc = job.get("proc")
            if proc and proc.poll() is None:
                try:
                    proc.terminate()
                    proc.wait(timeout=2)
                except Exception:
                    try:
                        proc.kill()
                    except Exception:
                        pass
        _JOBS.clear()
        _NEXT_ID[0] = 0


def _pump(job_id: str, proc: subprocess.Popen) -> None:
    assert proc.stdout is not None
    try:
        for line in iter(proc.stdout.readline, ""):
            with _LOCK:
                job = _JOBS.get(job_id)
                if job is None:
                    return
                job["output"].append(line)
                # Soft cap memory: keep last 10000 lines per job
                if len(job["output"]) > 10000:
                    del job["output"][:5000]
    finally:
        try:
            proc.stdout.close()
        except Exception:
            pass


def bash_bg_tool(args: dict) -> ToolResult:
    cmd = args.get("command", "")
    if not cmd:
        return ToolResult(content="missing 'command' argument", is_error=True)
    proc = subprocess.Popen(
        cmd,
        shell=True,
        executable="/bin/bash",
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    job_id = _next_job_id()
    with _LOCK:
        _JOBS[job_id] = {"proc": proc, "command": cmd, "output": []}
    threading.Thread(target=_pump, args=(job_id, proc), daemon=True).start()
    return ToolResult(content=f"started {job_id}: {cmd}")


def _status(proc: subprocess.Popen) -> str:
    rc = proc.poll()
    return "running" if rc is None else f"exited (code {rc})"


def bash_output_tool(args: dict) -> ToolResult:
    job_id = args.get("job_id", "")
    if not job_id:
        return ToolResult(content="missing 'job_id' argument", is_error=True)
    tail = int(args.get("tail_lines", 50))
    with _LOCK:
        job = _JOBS.get(job_id)
        if job is None:
            return ToolResult(content=f"unknown job: {job_id}", is_error=True)
        snapshot = list(job["output"][-tail:])
        proc = job["proc"]
        cmd = job["command"]
    status = _status(proc)
    body = "".join(snapshot) or "(no output yet)"
    return ToolResult(content=f"[{status}] {cmd}\n{body}")


def kill_bash_tool(args: dict) -> ToolResult:
    job_id = args.get("job_id", "")
    if not job_id:
        return ToolResult(content="missing 'job_id' argument", is_error=True)
    with _LOCK:
        job = _JOBS.get(job_id)
        if job is None:
            return ToolResult(content=f"unknown job: {job_id}", is_error=True)
        proc = job["proc"]
    if proc.poll() is not None:
        return ToolResult(content=f"{job_id} already exited (code {proc.returncode})")
    try:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=2)
    except Exception as exc:
        return ToolResult(content=f"failed to terminate {job_id}: {exc}", is_error=True)
    return ToolResult(content=f"terminated {job_id}")


def bash_list_tool(args: dict) -> ToolResult:
    with _LOCK:
        items = [(jid, job) for jid, job in _JOBS.items()]
    if not items:
        return ToolResult(content="(no background jobs)")
    rows = [f"{jid:>6}  {_status(job['proc']):<20}  {job['command'][:80]}" for jid, job in items]
    return ToolResult(content="\n".join(rows))


BASH_BG = ToolDefinition(
    name="bash_bg",
    description="Start a shell command as a background process. Returns a job_id (e.g. 'bg3') you can pass to bash_output / kill_bash / bash_list.",
    input_schema={
        "type": "object",
        "properties": {"command": {"type": "string"}},
        "required": ["command"],
    },
    handler=bash_bg_tool,
)


BASH_OUTPUT = ToolDefinition(
    name="bash_output",
    description="Read the last N lines of output from a background job and its current status. Doesn't block on the process.",
    input_schema={
        "type": "object",
        "properties": {
            "job_id": {"type": "string"},
            "tail_lines": {"type": "integer", "description": "How many trailing lines to return (default 50)"},
        },
        "required": ["job_id"],
    },
    handler=bash_output_tool,
)


KILL_BASH = ToolDefinition(
    name="kill_bash",
    description="Terminate a background job (SIGTERM, falls back to SIGKILL after 5s).",
    input_schema={
        "type": "object",
        "properties": {"job_id": {"type": "string"}},
        "required": ["job_id"],
    },
    handler=kill_bash_tool,
)


BASH_LIST = ToolDefinition(
    name="bash_list",
    description="List all background bash jobs (id, status, command).",
    input_schema={"type": "object", "properties": {}},
    handler=bash_list_tool,
)
