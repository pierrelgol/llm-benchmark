#!/usr/bin/env python3
"""Evaluate a generated document.md against the bench-02 reference with opencode."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path


DEFAULT_MODEL = "openai/gpt-5.4"


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def write_text(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")


def strip_code_fence(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```") and stripped.endswith("```"):
        lines = stripped.splitlines()
        if len(lines) >= 3:
            return "\n".join(lines[1:-1]).strip()
    return stripped


def parse_json_response(text: str) -> dict:
    cleaned = strip_code_fence(text)
    return json.loads(cleaned)


def extract_assistant_text_from_jsonl(jsonl: str) -> str:
    chunks: list[str] = []
    for line in jsonl.splitlines():
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if payload.get("type") != "text":
            continue
        part = payload.get("part")
        if not isinstance(part, dict):
            continue
        text = part.get("text")
        if isinstance(text, str):
            chunks.append(text)
    return "".join(chunks).strip()


def build_messages(prompt_text: str, reference_text: str, candidate_text: str) -> list[dict]:
    instructions = textwrap.dedent(
        """
        You are grading a benchmark submission.

        Compare the candidate document against:
        1. the original task prompt
        2. the reference document, which represents the expected quality bar

        Grade the candidate on quality and precision relative to the reference. Be strict.

        Return JSON only with this exact shape:
        {
          "scores": {
            "instruction_following": integer from 0 to 10,
            "coverage": integer from 0 to 10,
            "technical_precision": integer from 0 to 10,
            "reference_alignment": integer from 0 to 10,
            "overall": integer from 0 to 10
          },
          "verdict": "pass" | "borderline" | "fail",
          "summary": string,
          "missing_or_incorrect": [string, ...],
          "notable_strengths": [string, ...]
        }

        Scoring guidance:
        - instruction_following: did it satisfy the task and output the right type of document
        - coverage: did it cover the required implementation areas and edge cases
        - technical_precision: did it stay concrete, specific, and technically accurate
        - reference_alignment: how close it is to the reference document's level of specificity and usefulness
        - overall: holistic benchmark score

        Use "pass" only when the candidate is clearly close to the reference in both quality and precision.
        """
    ).strip()

    user_text = "\n\n".join(
        [
            "## Original Prompt",
            prompt_text,
            "## Reference Document",
            reference_text,
            "## Candidate Document",
            candidate_text,
        ]
    )

    return [
        {"role": "system", "content": instructions},
        {"role": "user", "content": user_text},
    ]


def run_opencode_grader(model: str, message: str, workdir: Path) -> subprocess.CompletedProcess[str]:
    command = [
        "opencode",
        "run",
        "--format",
        "json",
        "--dir",
        os.fspath(workdir),
        "--model",
        model,
        message,
    ]
    return subprocess.run(
        command,
        text=True,
        capture_output=True,
        check=False,
    )


def validate_paths(args: argparse.Namespace) -> None:
    for name in ("prompt", "reference", "candidate"):
        path = getattr(args, name)
        if not path.is_file():
            raise SystemExit(f"{name} file does not exist: {path}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Evaluate bench-02 document quality with opencode")
    parser.add_argument("--prompt", type=Path, required=True)
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--output-json", type=Path, required=True)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    validate_paths(args)

    prompt_text = read_text(args.prompt)
    reference_text = read_text(args.reference)
    candidate_text = read_text(args.candidate)
    if not candidate_text.strip():
        print("candidate document is empty", file=sys.stderr)
        return 1

    messages = build_messages(prompt_text, reference_text, candidate_text)
    grader_input = json.dumps(messages, indent=2)
    grader_prompt = (
        "Evaluate the benchmark submission using the provided conversation payload. "
        "Return only the JSON object requested in the system instructions.\n\n"
        f"{grader_input}"
    )
    response = run_opencode_grader(args.model, grader_prompt, args.candidate.parent)
    raw_jsonl_path = args.output_json.with_suffix(args.output_json.suffix + ".opencode.jsonl")
    raw_stderr_path = args.output_json.with_suffix(args.output_json.suffix + ".opencode.stderr")
    write_text(raw_jsonl_path, response.stdout)
    write_text(raw_stderr_path, response.stderr)

    if response.returncode != 0:
        print(f"opencode grader failed with exit code {response.returncode}", file=sys.stderr)
        if response.stderr.strip():
            print(response.stderr, file=sys.stderr)
        return 2

    output_text = extract_assistant_text_from_jsonl(response.stdout)
    if not output_text:
        print("opencode grader did not produce assistant text output", file=sys.stderr)
        return 2

    try:
        evaluation = parse_json_response(output_text)
    except json.JSONDecodeError as exc:
        print(f"failed to parse evaluator output as JSON: {exc}", file=sys.stderr)
        print(output_text, file=sys.stderr)
        return 2

    result = {
        "model": args.model,
        "prompt_path": os.fspath(args.prompt.resolve()),
        "reference_path": os.fspath(args.reference.resolve()),
        "candidate_path": os.fspath(args.candidate.resolve()),
        "evaluation": evaluation,
        "opencode_stdout_path": os.fspath(raw_jsonl_path.resolve()),
        "opencode_stderr_path": os.fspath(raw_stderr_path.resolve()),
        "grader_exit_code": response.returncode,
    }
    write_text(args.output_json, json.dumps(result, indent=2, sort_keys=True) + "\n")

    scores = evaluation.get("scores", {})
    print(f"verdict: {evaluation.get('verdict', 'unknown')}")
    print(
        "scores: "
        f"instruction_following={scores.get('instruction_following')} "
        f"coverage={scores.get('coverage')} "
        f"technical_precision={scores.get('technical_precision')} "
        f"reference_alignment={scores.get('reference_alignment')} "
        f"overall={scores.get('overall')}"
    )
    summary = evaluation.get("summary")
    if isinstance(summary, str) and summary.strip():
        print(f"summary: {summary.strip()}")

    verdict = evaluation.get("verdict")
    return 0 if verdict in {"pass", "borderline"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
