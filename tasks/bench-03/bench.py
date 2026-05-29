#!/usr/bin/env python3
"""Standalone benchmark harness for bench-03."""

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
TOTAL_ROUNDS = 5
TOML_VERSION = "1.1"

BENCH_DIR = Path(__file__).resolve().parent
INIT_DIR = BENCH_DIR / "init"
TESTER_DIR = BENCH_DIR / "tester" / "toml-test"
DECODER_BINARY = "toml"


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


def write_json(path: Path, payload: Any) -> None:
    write_text(path, json.dumps(payload, indent=2, sort_keys=True) + "\n")


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
    validate_workspace(workspace)

    removed: list[str] = []
    for candidate in workspace.glob(".round-*"):
        if candidate.is_dir():
            shutil.rmtree(candidate)
        else:
            candidate.unlink()
        removed.append(candidate.name)

    for candidate in (workspace / "obj", workspace / DECODER_BINARY):
        if candidate.is_dir():
            shutil.rmtree(candidate)
            removed.append(candidate.name)
        elif candidate.exists():
            candidate.unlink()
            removed.append(candidate.name)

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
    score_summary = "No previous score file was found."
    score_path = prior / "score.json"
    if score_path.is_file():
        try:
            score = json.loads(read_text(score_path))
        except json.JSONDecodeError:
            score = {}
        score_summary = (
            "Previous round score summary:\n"
            f"- primary_score: {score.get('primary_score')}\n"
            f"- pass_rate: {score.get('pass_rate')}\n"
            f"- passed_tests: {score.get('passed_tests')}\n"
            f"- failed_tests: {score.get('failed_tests')}\n"
            f"- skipped_tests: {score.get('skipped_tests')}\n"
            f"- passed_valid: {score.get('passed_valid')}\n"
            f"- failed_valid: {score.get('failed_valid')}\n"
            f"- passed_invalid: {score.get('passed_invalid')}\n"
            f"- failed_invalid: {score.get('failed_invalid')}\n"
            f"- passed_encoder: {score.get('passed_encoder')}\n"
            f"- failed_encoder: {score.get('failed_encoder')}"
        )

    parts: list[str] = [score_summary]
    for label, filename in (
        ("build exit code", "build.exit_code"),
        ("build stdout", "build.stdout"),
        ("build stderr", "build.stderr"),
        ("tester exit code", "tester.exit_code"),
        ("tester stdout", "tester.stdout"),
        ("tester stderr", "tester.stderr"),
    ):
        artifact = prior / filename
        if artifact.is_file():
            parts.append(f"## Previous {label}\n\n```text\n{read_text(artifact)}\n```")
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
                f"Original objective reminder: implement a native C TOML v{TOML_VERSION} decoder in this workspace that passes the toml-test decoder suite via `./{DECODER_BINARY}` after `make`.",
                "",
                "Continue from the existing workspace state. Do not restart from scratch. Focus on fixing the remaining failures exposed by the previous round.",
                "",
                previous_results_text(prior),
            ]
        )

    return "\n".join(message).rstrip() + "\n"


def validate_workspace(workspace: Path) -> None:
    if not workspace.is_dir():
        raise SystemExit(f"workspace does not exist: {workspace}")
    for required in ("prompt.md", "spec.md", "Makefile", "src", "include"):
        if not (workspace / required).exists():
            raise SystemExit(f"workspace is missing {required}: {workspace}")
    if not TESTER_DIR.is_dir():
        raise SystemExit(f"tester is missing: {TESTER_DIR}")


def validate_round(workspace: Path, round_number: int) -> None:
    validate_workspace(workspace)
    if round_number < 1 or round_number > TOTAL_ROUNDS:
        raise SystemExit(f"round must be between 1 and {TOTAL_ROUNDS}: {round_number}")
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


def derive_score(tester_report: dict[str, Any]) -> dict[str, Any]:
    passed_valid = int(tester_report.get("passed_valid", 0))
    failed_valid = int(tester_report.get("failed_valid", 0))
    passed_invalid = int(tester_report.get("passed_invalid", 0))
    failed_invalid = int(tester_report.get("failed_invalid", 0))
    passed_encoder = int(tester_report.get("passed_encoder", 0))
    failed_encoder = int(tester_report.get("failed_encoder", 0))
    skipped_tests = int(tester_report.get("skipped", 0))

    passed_tests = passed_valid + passed_invalid + passed_encoder
    failed_tests = failed_valid + failed_invalid + failed_encoder
    total_tests = passed_tests + failed_tests + skipped_tests
    scored_tests = passed_tests + failed_tests
    pass_rate = (passed_tests / scored_tests) if scored_tests else 0.0

    return {
        "toml_version": tester_report.get("toml", TOML_VERSION),
        "total_tests": total_tests,
        "passed_tests": passed_tests,
        "failed_tests": failed_tests,
        "skipped_tests": skipped_tests,
        "pass_rate": pass_rate,
        "primary_score": pass_rate,
        "passed_valid": passed_valid,
        "failed_valid": failed_valid,
        "passed_invalid": passed_invalid,
        "failed_invalid": failed_invalid,
        "passed_encoder": passed_encoder,
        "failed_encoder": failed_encoder,
    }


def write_zero_score(artifact_dir: Path, reason: str) -> dict[str, Any]:
    score = {
        "toml_version": TOML_VERSION,
        "total_tests": 0,
        "passed_tests": 0,
        "failed_tests": 0,
        "skipped_tests": 0,
        "pass_rate": 0.0,
        "primary_score": 0.0,
        "passed_valid": 0,
        "failed_valid": 0,
        "passed_invalid": 0,
        "failed_invalid": 0,
        "passed_encoder": 0,
        "failed_encoder": 0,
        "reason": reason,
    }
    write_json(artifact_dir / "score.json", score)
    return score


def run_tester(workspace: Path, artifact_dir: Path, metadata: dict[str, Any]) -> int:
    build_clean_command = ["make", "clean"]
    build_command = ["make"]
    decoder_command = f"{workspace / DECODER_BINARY}"
    tester_command = [
        "go",
        "run",
        "./cmd/toml-test",
        "test",
        "-json",
        f"-toml={TOML_VERSION}",
        f"-decoder={decoder_command}",
    ]

    clean_started = utc_now()
    cleaned = run_capture(build_clean_command, cwd=workspace)
    clean_finished = utc_now()
    write_text(artifact_dir / "build_clean.stdout", cleaned.stdout)
    write_text(artifact_dir / "build_clean.stderr", cleaned.stderr)
    write_text(artifact_dir / "build_clean.exit_code", f"{cleaned.returncode}\n")

    build_started = utc_now()
    build = run_capture(build_command, cwd=workspace)
    build_finished = utc_now()
    write_text(artifact_dir / "build.stdout", build.stdout)
    write_text(artifact_dir / "build.stderr", build.stderr)
    write_text(artifact_dir / "build.exit_code", f"{build.returncode}\n")

    metadata["build"] = {
        "clean_command": command_for_metadata(build_clean_command),
        "clean_started_at": clean_started,
        "clean_finished_at": clean_finished,
        "clean_exit_code": cleaned.returncode,
        "clean_stdout_path": os.fspath(artifact_dir / "build_clean.stdout"),
        "clean_stderr_path": os.fspath(artifact_dir / "build_clean.stderr"),
        "command": command_for_metadata(build_command),
        "cwd": os.fspath(workspace),
        "started_at": build_started,
        "finished_at": build_finished,
        "exit_code": build.returncode,
        "stdout_path": os.fspath(artifact_dir / "build.stdout"),
        "stderr_path": os.fspath(artifact_dir / "build.stderr"),
    }

    if build.returncode != 0:
        write_text(artifact_dir / "tester.stdout", "")
        write_text(artifact_dir / "tester.stderr", "tester skipped because make failed\n")
        write_text(artifact_dir / "tester.exit_code", "not-run\n")
        metadata["tester"] = {
            "command": command_for_metadata(tester_command),
            "cwd": os.fspath(TESTER_DIR),
            "skipped": True,
            "reason": "make failed",
            "exit_code": None,
            "stdout_path": os.fspath(artifact_dir / "tester.stdout"),
            "stderr_path": os.fspath(artifact_dir / "tester.stderr"),
            "report_path": os.fspath(artifact_dir / "tester.json"),
        }
        metadata["score"] = write_zero_score(artifact_dir, "build failed")
        return build.returncode

    tester_started = utc_now()
    tester = run_capture(tester_command, cwd=TESTER_DIR)
    tester_finished = utc_now()
    write_text(artifact_dir / "tester.stdout", tester.stdout)
    write_text(artifact_dir / "tester.stderr", tester.stderr)
    write_text(artifact_dir / "tester.exit_code", f"{tester.returncode}\n")

    tester_report: dict[str, Any]
    try:
        tester_report = json.loads(tester.stdout)
    except json.JSONDecodeError:
        tester_report = {"raw_stdout": tester.stdout}

    write_json(artifact_dir / "tester.json", tester_report)
    score = derive_score(tester_report) if "raw_stdout" not in tester_report else write_zero_score(artifact_dir, "tester output was not valid JSON")
    if "raw_stdout" not in tester_report:
        write_json(artifact_dir / "score.json", score)

    metadata["tester"] = {
        "command": command_for_metadata(tester_command),
        "cwd": os.fspath(TESTER_DIR),
        "started_at": tester_started,
        "finished_at": tester_finished,
        "skipped": False,
        "exit_code": tester.returncode,
        "stdout_path": os.fspath(artifact_dir / "tester.stdout"),
        "stderr_path": os.fspath(artifact_dir / "tester.stderr"),
        "report_path": os.fspath(artifact_dir / "tester.json"),
    }
    metadata["score"] = score
    return tester.returncode


def test_workspace(workspace_path: Path) -> int:
    workspace = require_workspace(workspace_path)
    validate_workspace(workspace)

    artifact_dir = workspace / ".test-run"
    if artifact_dir.exists():
        shutil.rmtree(artifact_dir)
    artifact_dir.mkdir(parents=True)

    metadata: dict[str, Any] = {
        "workspace": os.fspath(workspace),
        "artifact_dir": os.fspath(artifact_dir),
        "toml_version": TOML_VERSION,
        "decoder_binary": os.fspath(workspace / DECODER_BINARY),
        "started_at": utc_now(),
    }

    exit_code = run_tester(workspace, artifact_dir, metadata)
    metadata["finished_at"] = utc_now()
    metadata["exit_code"] = exit_code
    write_json(artifact_dir / "metadata.json", metadata)

    score = metadata.get("score", {})
    print(f"artifacts: {artifact_dir}")
    print(
        "score: "
        f"passed={score.get('passed_tests', 0)} "
        f"failed={score.get('failed_tests', 0)} "
        f"skipped={score.get('skipped_tests', 0)} "
        f"total={score.get('total_tests', 0)} "
        f"pass_rate={score.get('pass_rate', 0.0)}"
    )
    return exit_code


def launch_round(workspace_path: Path, round_number: int, model: str, resume_session: bool) -> int:
    workspace = require_workspace(workspace_path)
    validate_round(workspace, round_number)

    artifact_dir = round_dir(workspace, round_number)
    if artifact_dir.exists():
        shutil.rmtree(artifact_dir)
    artifact_dir.mkdir(parents=True)

    prompt = assemble_prompt(workspace, round_number)
    write_text(artifact_dir / "prompt.md", prompt)

    session_to_continue = None
    if resume_session and round_number > 1:
        session_to_continue = prior_session_id(round_dir(workspace, round_number - 1))
    command = [
        "opencode",
        "run",
        "--format",
        "json",
        "--dir",
        os.fspath(workspace),
        "--model",
        model,
        "--dangerously-skip-permissions",
    ]
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
        "toml_version": TOML_VERSION,
        "decoder_binary": os.fspath(workspace / DECODER_BINARY),
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
    write_json(artifact_dir / "metadata.json", metadata)

    print(f"round {round_number} artifacts: {artifact_dir}")
    return int(metadata["exit_code"] or 0)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="bench-03 standalone benchmark harness")
    subcommands = parser.add_subparsers(dest="command", required=True)

    setup = subcommands.add_parser("setup", help="delete and recreate a benchmark workspace")
    setup.add_argument("path", type=Path)

    launch = subcommands.add_parser("launch", help="run exactly one benchmark round")
    launch.add_argument("--round", dest="round_number", type=int, required=True)
    launch.add_argument("--workspace", type=Path, required=True)
    launch.add_argument("--model", default=DEFAULT_MODEL)
    launch.add_argument(
        "--resume-session",
        action="store_true",
        help="continue the previous opencode session for later rounds",
    )

    test = subcommands.add_parser("test", help="build and run the tester without launching a model round")
    test.add_argument("--workspace", type=Path, required=True)

    clean = subcommands.add_parser("clean", help="remove benchmark-generated artifacts")
    clean.add_argument("--workspace", type=Path, required=True)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "setup":
        return setup_workspace(args.path)
    if args.command == "launch":
        return launch_round(args.workspace, args.round_number, args.model, args.resume_session)
    if args.command == "test":
        return test_workspace(args.workspace)
    if args.command == "clean":
        return clean_workspace(args.workspace)

    parser.error("unknown command")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
