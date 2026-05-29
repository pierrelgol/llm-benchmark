#!/usr/bin/env python3
"""Standalone benchmark harness for bench-02."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_MODEL = "lmstudio/unsloth/qwen3.6-27b-mtp"

BENCH_DIR = Path(__file__).resolve().parent
INIT_DIR = BENCH_DIR / "init"
TESTER = BENCH_DIR / "tester" / "evaluate_document.py"
REFERENCE_DOCUMENT = BENCH_DIR / "tester" / "document.md"
ARTIFACT_DIRNAME = ".run"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def require_workspace(path: Path) -> Path:
    return path.expanduser().resolve()


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def write_text(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")


def command_for_metadata(command: list[str]) -> list[str]:
    return [os.fspath(part) for part in command]


def run_capture(command: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=os.fspath(cwd) if cwd else None,
        text=True,
        capture_output=True,
        check=False,
    )


def find_session_id(value: Any) -> str | None:
    if isinstance(value, dict):
        for key in ("sessionID", "sessionId", "session_id"):
            found = value.get(key)
            if isinstance(found, str) and found:
                return found
        for nested in value.values():
            found = find_session_id(nested)
            if found:
                return found
    elif isinstance(value, list):
        for nested in value:
            found = find_session_id(nested)
            if found:
                return found
    return None


def extract_last_session_id(jsonl: str) -> str | None:
    session_id: str | None = None
    for line in jsonl.splitlines():
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        found = find_session_id(payload)
        if found:
            session_id = found
    return session_id


def validate_workspace(workspace: Path) -> None:
    if not workspace.is_dir():
        raise SystemExit(f"workspace does not exist: {workspace}")
    if not (workspace / "prompt.md").is_file():
        raise SystemExit(f"workspace is missing prompt.md: {workspace}")
    if not (workspace / "libgit2").is_dir():
        raise SystemExit(f"workspace is missing libgit2/: {workspace}")
    if not REFERENCE_DOCUMENT.is_file():
        raise SystemExit(f"reference document is missing: {REFERENCE_DOCUMENT}")


def setup_workspace(path: Path) -> int:
    workspace = require_workspace(path)
    if workspace.exists():
        shutil.rmtree(workspace)
    workspace.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(INIT_DIR, workspace)
    print(f"created workspace: {workspace}")
    return 0


def clean_workspace(path: Path) -> int:
    workspace = require_workspace(path)
    validate_workspace(workspace)

    removed: list[str] = []
    artifact_dir = workspace / ARTIFACT_DIRNAME
    if artifact_dir.exists():
        shutil.rmtree(artifact_dir)
        removed.append(ARTIFACT_DIRNAME)

    generated = workspace / "document.md"
    if generated.exists():
        generated.unlink()
        removed.append("document.md")

    if removed:
        print("removed: " + ", ".join(sorted(removed)))
    else:
        print(f"nothing to clean: {workspace}")
    return 0


def export_session(session_id: str | None, artifact_dir: Path, metadata: dict[str, Any]) -> None:
    if not session_id:
        metadata["session_export"] = {"available": False, "reason": "no session id found"}
        return

    command = ["opencode", "export", session_id]
    proc = run_capture(command)
    write_text(artifact_dir / "session_export.json", proc.stdout)
    write_text(artifact_dir / "session_export.stderr", proc.stderr)
    write_text(artifact_dir / "session_export.exit_code", f"{proc.returncode}\n")
    metadata["session_export"] = {
        "available": proc.returncode == 0,
        "command": command_for_metadata(command),
        "stdout_path": os.fspath(artifact_dir / "session_export.json"),
        "stderr_path": os.fspath(artifact_dir / "session_export.stderr"),
        "exit_code": proc.returncode,
    }


def run_tester(workspace: Path, artifact_dir: Path, metadata: dict[str, Any]) -> int:
    candidate = workspace / "document.md"
    prompt = workspace / "prompt.md"
    tester_command = [
        "python3",
        os.fspath(TESTER),
        "--prompt",
        os.fspath(prompt),
        "--reference",
        os.fspath(REFERENCE_DOCUMENT),
        "--candidate",
        os.fspath(candidate),
        "--output-json",
        os.fspath(artifact_dir / "evaluation.json"),
    ]

    tester_started = utc_now()
    tester = run_capture(tester_command, cwd=BENCH_DIR)
    tester_finished = utc_now()
    write_text(artifact_dir / "tester.stdout", tester.stdout)
    write_text(artifact_dir / "tester.stderr", tester.stderr)
    write_text(artifact_dir / "tester.exit_code", f"{tester.returncode}\n")
    metadata["tester"] = {
        "command": command_for_metadata(tester_command),
        "started_at": tester_started,
        "finished_at": tester_finished,
        "exit_code": tester.returncode,
        "stdout_path": os.fspath(artifact_dir / "tester.stdout"),
        "stderr_path": os.fspath(artifact_dir / "tester.stderr"),
        "evaluation_path": os.fspath(artifact_dir / "evaluation.json"),
    }
    return tester.returncode


def launch_workspace(workspace_path: Path, model: str) -> int:
    workspace = require_workspace(workspace_path)
    validate_workspace(workspace)

    artifact_dir = workspace / ARTIFACT_DIRNAME
    if artifact_dir.exists():
        shutil.rmtree(artifact_dir)
    artifact_dir.mkdir(parents=True)

    prompt = read_text(workspace / "prompt.md").rstrip() + "\n"
    write_text(artifact_dir / "prompt.md", prompt)

    command = ["opencode", "run", "--format", "json", "--dir", os.fspath(workspace), "--model", model, prompt]
    metadata: dict[str, Any] = {
        "model": model,
        "workspace": os.fspath(workspace),
        "artifact_dir": os.fspath(artifact_dir),
        "prompt_path": os.fspath(artifact_dir / "prompt.md"),
        "reference_document": os.fspath(REFERENCE_DOCUMENT),
        "started_at": utc_now(),
        "opencode": {
            "command": command_for_metadata(command[:-1] + ["<prompt>"]),
            "stdout_path": os.fspath(artifact_dir / "opencode.stdout.jsonl"),
            "stderr_path": os.fspath(artifact_dir / "opencode.stderr"),
        },
    }

    opencode_started = utc_now()
    opencode = run_capture(command)
    opencode_finished = utc_now()
    write_text(artifact_dir / "opencode.stdout.jsonl", opencode.stdout)
    write_text(artifact_dir / "opencode.stderr", opencode.stderr)
    write_text(artifact_dir / "opencode.exit_code", f"{opencode.returncode}\n")

    session_id = extract_last_session_id(opencode.stdout)
    metadata["session_id"] = session_id
    metadata["opencode"].update(
        {
            "started_at": opencode_started,
            "finished_at": opencode_finished,
            "exit_code": opencode.returncode,
            "session_id": session_id,
        }
    )

    tester_exit = run_tester(workspace, artifact_dir, metadata)
    export_session(session_id, artifact_dir, metadata)

    metadata["finished_at"] = utc_now()
    metadata["exit_code"] = opencode.returncode if opencode.returncode != 0 else tester_exit
    write_text(artifact_dir / "metadata.json", json.dumps(metadata, indent=2, sort_keys=True) + "\n")

    print(f"artifacts: {artifact_dir}")
    return int(metadata["exit_code"] or 0)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="bench-02 standalone benchmark harness")
    subcommands = parser.add_subparsers(dest="command", required=True)

    setup = subcommands.add_parser("setup", help="delete and recreate a benchmark workspace")
    setup.add_argument("path", type=Path)

    launch = subcommands.add_parser("launch", help="run the benchmark once")
    launch.add_argument("--workspace", type=Path, required=True)
    launch.add_argument("--model", default=DEFAULT_MODEL)

    clean = subcommands.add_parser("clean", help="remove benchmark-generated artifacts")
    clean.add_argument("--workspace", type=Path, required=True)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "setup":
        return setup_workspace(args.path)
    if args.command == "launch":
        return launch_workspace(args.workspace, args.model)
    if args.command == "clean":
        return clean_workspace(args.workspace)

    parser.error("unknown command")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
