#!/usr/bin/env python3
"""Standalone benchmark harness for bench-01."""

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
TOTAL_ROUNDS = 3

BENCH_DIR = Path(__file__).resolve().parent
INIT_DIR = BENCH_DIR / "init"
TESTER = BENCH_DIR / "tester" / "tests" / "cli_behavior_suite.py"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def require_workspace(path: Path) -> Path:
    return path.expanduser().resolve()


def round_dir(workspace: Path, round_number: int) -> Path:
    return workspace / f".round-{round_number}"


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
    if not workspace.exists():
        raise SystemExit(f"workspace does not exist: {workspace}")

    removed: list[str] = []
    for candidate in workspace.glob(".round-*"):
        if candidate.is_dir():
            shutil.rmtree(candidate)
        else:
            candidate.unlink()
        removed.append(candidate.name)

    target = workspace / "rust" / "target"
    if target.exists():
        shutil.rmtree(target)
        removed.append("rust/target")

    if removed:
        print("removed: " + ", ".join(sorted(removed)))
    else:
        print(f"nothing to clean: {workspace}")
    return 0


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


def prior_session_id(prior: Path) -> str | None:
    metadata_path = prior / "metadata.json"
    if metadata_path.is_file():
        try:
            metadata = json.loads(read_text(metadata_path))
        except json.JSONDecodeError:
            metadata = {}
        session_id = metadata.get("session_id")
        if isinstance(session_id, str) and session_id:
            return session_id

    jsonl_path = prior / "opencode.stdout.jsonl"
    if jsonl_path.is_file():
        return extract_last_session_id(read_text(jsonl_path))
    return None


def previous_results_text(prior: Path) -> str:
    parts: list[str] = []
    for label, filename in (
        ("build exit code", "build.exit_code"),
        ("build stdout", "build.stdout"),
        ("build stderr", "build.stderr"),
        ("tester exit code", "tester.exit_code"),
        ("tester stdout", "tester.stdout"),
        ("tester stderr", "tester.stderr"),
    ):
        path = prior / filename
        if path.is_file():
            parts.append(f"## Previous {label}\n\n```text\n{read_text(path)}\n```")
    if not parts:
        return "No previous tester result files were found."
    return "\n\n".join(parts)


def assemble_prompt(workspace: Path, round_number: int) -> str:
    base_prompt = read_text(workspace / "prompt.md").strip()
    message = [
        base_prompt,
        "",
        f"Benchmark round: {round_number} of {TOTAL_ROUNDS}.",
        "",
        "Run only this round's work. Keep working in the current copied workspace.",
    ]

    if round_number > 1:
        prior = round_dir(workspace, round_number - 1)
        message.extend(
            [
                "",
                "Original objective reminder: reimplement `ini2json/` as a fully native Rust CLI in `rust/`, with behavior matching the original CLI exactly and a release executable named `ini2json`.",
                "",
                "Continue from the existing workspace state. Do not restart the implementation from scratch. Use the previous tester output below to fix remaining failures only.",
                "",
                previous_results_text(prior),
            ]
        )

    return "\n".join(message).rstrip() + "\n"


def validate_round(workspace: Path, round_number: int) -> None:
    if round_number < 1 or round_number > TOTAL_ROUNDS:
        raise SystemExit(f"round must be between 1 and {TOTAL_ROUNDS}: {round_number}")
    if not workspace.is_dir():
        raise SystemExit(f"workspace does not exist: {workspace}")
    if not (workspace / "prompt.md").is_file():
        raise SystemExit(f"workspace is missing prompt.md: {workspace}")
    if not (workspace / "rust" / "Cargo.toml").is_file():
        raise SystemExit(f"workspace is missing rust/Cargo.toml: {workspace}")
    if round_number > 1 and not round_dir(workspace, round_number - 1).is_dir():
        raise SystemExit(f"round {round_number} requires prior artifact: {round_dir(workspace, round_number - 1)}")


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
    rust_dir = workspace / "rust"
    binary = rust_dir / "target" / "release" / "ini2json"
    build_command = ["cargo", "build", "--release"]
    tester_command = ["python3", os.fspath(TESTER), os.fspath(binary)]

    build_started = utc_now()
    build = run_capture(build_command, cwd=rust_dir)
    build_finished = utc_now()
    write_text(artifact_dir / "build.stdout", build.stdout)
    write_text(artifact_dir / "build.stderr", build.stderr)
    write_text(artifact_dir / "build.exit_code", f"{build.returncode}\n")

    metadata["build"] = {
        "command": command_for_metadata(build_command),
        "cwd": os.fspath(rust_dir),
        "started_at": build_started,
        "finished_at": build_finished,
        "exit_code": build.returncode,
        "stdout_path": os.fspath(artifact_dir / "build.stdout"),
        "stderr_path": os.fspath(artifact_dir / "build.stderr"),
    }

    if build.returncode != 0:
        write_text(artifact_dir / "tester.stdout", "")
        write_text(artifact_dir / "tester.stderr", "tester skipped because cargo build failed\n")
        write_text(artifact_dir / "tester.exit_code", "not-run\n")
        metadata["tester"] = {
            "command": command_for_metadata(tester_command),
            "skipped": True,
            "reason": "cargo build failed",
            "exit_code": None,
            "stdout_path": os.fspath(artifact_dir / "tester.stdout"),
            "stderr_path": os.fspath(artifact_dir / "tester.stderr"),
        }
        return build.returncode

    tester_started = utc_now()
    tester = run_capture(tester_command)
    tester_finished = utc_now()
    write_text(artifact_dir / "tester.stdout", tester.stdout)
    write_text(artifact_dir / "tester.stderr", tester.stderr)
    write_text(artifact_dir / "tester.exit_code", f"{tester.returncode}\n")
    metadata["tester"] = {
        "command": command_for_metadata(tester_command),
        "started_at": tester_started,
        "finished_at": tester_finished,
        "skipped": False,
        "exit_code": tester.returncode,
        "stdout_path": os.fspath(artifact_dir / "tester.stdout"),
        "stderr_path": os.fspath(artifact_dir / "tester.stderr"),
    }
    return tester.returncode


def launch_round(workspace_path: Path, round_number: int, model: str) -> int:
    workspace = require_workspace(workspace_path)
    validate_round(workspace, round_number)

    artifact_dir = round_dir(workspace, round_number)
    if artifact_dir.exists():
        shutil.rmtree(artifact_dir)
    artifact_dir.mkdir(parents=True)

    prompt = assemble_prompt(workspace, round_number)
    write_text(artifact_dir / "prompt.md", prompt)

    session_to_continue = prior_session_id(round_dir(workspace, round_number - 1)) if round_number > 1 else None
    command = ["opencode", "run", "--format", "json", "--dir", os.fspath(workspace), "--model", model]
    if session_to_continue:
        command.extend(["--session", session_to_continue])
    command.append(prompt)

    metadata: dict[str, Any] = {
        "round": round_number,
        "total_rounds": TOTAL_ROUNDS,
        "model": model,
        "workspace": os.fspath(workspace),
        "artifact_dir": os.fspath(artifact_dir),
        "prompt_path": os.fspath(artifact_dir / "prompt.md"),
        "started_at": utc_now(),
        "opencode": {
            "command": command_for_metadata(command[:-1] + ["<prompt>"]),
            "continued_from_session_id": session_to_continue,
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

    print(f"round {round_number} artifacts: {artifact_dir}")
    return int(metadata["exit_code"] or 0)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="bench-01 standalone benchmark harness")
    subcommands = parser.add_subparsers(dest="command", required=True)

    setup = subcommands.add_parser("setup", help="delete and recreate a benchmark workspace")
    setup.add_argument("path", type=Path)

    launch = subcommands.add_parser("launch", help="run exactly one benchmark round")
    launch.add_argument("--round", dest="round_number", type=int, required=True)
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
        return launch_round(args.workspace, args.round_number, args.model)
    if args.command == "clean":
        return clean_workspace(args.workspace)

    parser.error("unknown command")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
