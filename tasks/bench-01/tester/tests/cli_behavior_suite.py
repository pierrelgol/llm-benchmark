#!/usr/bin/env python3
"""Standalone behavioral test suite for the ini2json CLI.

Usage:
    python tests/cli_behavior_suite.py /path/to/ini2json
    python tests/cli_behavior_suite.py --binary /path/to/ini2json -v
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path
from typing import Iterable


BINARY_PATH: Path | None = None


class CompletedRun:
    def __init__(self, proc: subprocess.CompletedProcess[str]) -> None:
        self.returncode = proc.returncode
        self.stdout = proc.stdout
        self.stderr = proc.stderr


def case(name: str):
    def decorator(func):
        func._case_name = name
        return func

    return decorator


class NamedTextTestResult(unittest.TextTestResult):
    def getDescription(self, test: unittest.case.TestCase) -> str:
        description = test.shortDescription()
        if description:
            return description
        return super().getDescription(test)


class NamedTextTestRunner(unittest.TextTestRunner):
    resultclass = NamedTextTestResult

    def __init__(self, *args, **kwargs) -> None:
        kwargs.setdefault("verbosity", 2)
        kwargs.setdefault("descriptions", True)
        super().__init__(*args, **kwargs)


def iter_test_cases(suite: unittest.TestSuite) -> Iterable[unittest.case.TestCase]:
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from iter_test_cases(item)
        else:
            yield item


class Ini2JsonCliTests(unittest.TestCase):
    maxDiff = None

    def shortDescription(self) -> str | None:
        method = getattr(self, self._testMethodName)
        return getattr(method, "_case_name", None)

    def run_cli(self, *args: str, input_text: str | None = None) -> CompletedRun:
        self.assertIsNotNone(BINARY_PATH, "binary path was not configured")
        proc = subprocess.run(
            [os.fspath(BINARY_PATH), *args],
            input=input_text,
            text=True,
            capture_output=True,
            check=False,
        )
        return CompletedRun(proc)

    def write_ini(self, directory: Path, name: str, content: str) -> Path:
        path = directory / name
        path.write_text(content, encoding="utf-8", newline="")
        return path

    def assert_failure(self, run: CompletedRun, needle: str) -> None:
        self.assertEqual(run.returncode, 1, f"expected failure containing {needle!r}")
        self.assertIn(needle, run.stderr)
        self.assertIn("Usage: ini2json", run.stderr)
        self.assertEqual(run.stdout, "")

    def assert_json_output(self, run: CompletedRun, expected: object) -> None:
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertEqual(run.stderr, "")
        self.assertEqual(json.loads(run.stdout), expected)

    @case("help: both help flags print usage on stdout and exit zero")
    def test_help_prints_usage_to_stdout_and_exits_zero(self) -> None:
        for flag in ("-h", "--help"):
            with self.subTest(flag=flag):
                run = self.run_cli(flag)
                self.assertEqual(run.returncode, 0)
                self.assertIn("Usage: ini2json", run.stdout)
                self.assertIn("Convert an INI file to JSON or generate random INI files.", run.stdout)
                self.assertEqual(run.stderr, "")

    @case("cli: missing input file is reported as a usage error")
    def test_missing_input_file_is_reported(self) -> None:
        self.assert_failure(self.run_cli(), "ini2json: missing input file")

    @case("cli: unknown options are rejected with usage text")
    def test_unknown_option_is_reported(self) -> None:
        self.assert_failure(self.run_cli("--wat"), "ini2json: unknown option: --wat")

    @case("cli: more than one positional input file is rejected")
    def test_multiple_input_files_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            left = self.write_ini(tmpdir, "left.ini", "a = 1\n")
            right = self.write_ini(tmpdir, "right.ini", "b = 2\n")
            self.assert_failure(
                self.run_cli(os.fspath(left), os.fspath(right)),
                "ini2json: expected exactly one input file",
            )

    @case("parser: valid ini maps to the expected json structure")
    def test_valid_file_round_trips_to_expected_json_structure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = self.write_ini(
                Path(tmp),
                "config.ini",
                textwrap.dedent(
                    """
                    ; comment
                    global = root
                    path = /tmp/example

                    [ section one ]
                    key = value
                    another = second

                    [two]
                    enabled = true
                    """
                ).lstrip(),
            )
            self.assert_json_output(
                self.run_cli(os.fspath(path)),
                {
                    "global": "root",
                    "path": "/tmp/example",
                    "section one": {"another": "second", "key": "value"},
                    "two": {"enabled": "true"},
                },
            )

    @case("parser: whitespace is trimmed, inline comment text is preserved, empty values survive")
    def test_parser_trims_whitespace_preserves_inline_comment_text_and_handles_empty_values(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = self.write_ini(
                Path(tmp),
                "trim.ini",
                "   key   =   value ; not a comment   \nblank =    \n[  sec  ]\n nested =  x=y=z  \n",
            )
            self.assert_json_output(
                self.run_cli(os.fspath(path)),
                {
                    "blank": "",
                    "key": "value ; not a comment",
                    "sec": {"nested": "x=y=z"},
                },
            )

    @case("parser: crlf files and empty sections are accepted")
    def test_parser_accepts_crlf_line_endings_and_empty_sections(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = self.write_ini(Path(tmp), "windows.ini", "a = 1\r\n[empty]\r\n[sec]\r\nb = 2\r\n")
            self.assert_json_output(
                self.run_cli(os.fspath(path)),
                {"a": "1", "empty": {}, "sec": {"b": "2"}},
            )

    @case("formatting: compact mode emits single-line json")
    def test_compact_output_is_single_line_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = self.write_ini(Path(tmp), "compact.ini", "alpha = beta\n[sec]\nkey = value\n")
            run = self.run_cli("--compact", os.fspath(path))
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertEqual(run.stderr, "")
            self.assertEqual(run.stdout, '{"alpha":"beta","sec":{"key":"value"}}\n')

    @case("formatting: indent, tab, and compact flags control pretty-print output exactly")
    def test_indent_and_tab_flags_control_pretty_printing_exactly(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = self.write_ini(Path(tmp), "pretty.ini", "alpha = beta\n[sec]\nkey = value\n")

            with self.subTest(case="spaces"):
                run = self.run_cli("--indent", "4", os.fspath(path))
                self.assertEqual(run.returncode, 0, run.stderr)
                self.assertEqual(
                    run.stdout,
                    '{\n    "alpha": "beta",\n    "sec": {\n        "key": "value"\n    }\n}\n',
                )

            with self.subTest(case="tabs-default-width"):
                run = self.run_cli("--tab", os.fspath(path))
                self.assertEqual(run.returncode, 0, run.stderr)
                self.assertEqual(
                    run.stdout,
                    '{\n\t"alpha": "beta",\n\t"sec": {\n\t\t"key": "value"\n\t}\n}\n',
                )

            with self.subTest(case="tabs-explicit-width"):
                run = self.run_cli("--tab", "--indent", "4", os.fspath(path))
                self.assertEqual(run.returncode, 0, run.stderr)
                self.assertEqual(
                    run.stdout,
                    '{\n\t\t\t\t"alpha": "beta",\n\t\t\t\t"sec": {\n\t\t\t\t\t\t\t\t"key": "value"\n\t\t\t\t}\n}\n',
                )

            with self.subTest(case="compact-wins-over-pretty-flags"):
                run = self.run_cli("--tab", "--indent", "4", "--compact", os.fspath(path))
                self.assertEqual(run.returncode, 0, run.stderr)
                self.assertEqual(run.stdout, '{"alpha":"beta","sec":{"key":"value"}}\n')

    @case("filesystem: invalid extension, missing path, and directory path produce distinct parse failures")
    def test_invalid_extension_missing_path_and_directory_are_distinguished(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            bad_ext = tmpdir / "config.txt"
            bad_ext.write_text("a = 1\n", encoding="utf-8")
            missing = tmpdir / "missing.ini"
            directory = tmpdir / "folder.ini"
            directory.mkdir()

            self.assertEqual(
                self.run_cli(os.fspath(bad_ext)).stderr,
                f"ini2json: input file must have a .ini extension: {bad_ext}\n",
            )
            self.assertEqual(
                self.run_cli(os.fspath(missing)).stderr,
                f"ini2json: file not found: {missing}\n",
            )
            self.assertEqual(
                self.run_cli(os.fspath(directory)).stderr,
                f"ini2json: file not found: {directory}\n",
            )

    @case("parser: syntax errors and duplicate declarations map to their specific error messages")
    def test_invalid_syntax_duplicate_section_and_duplicate_variable_have_specific_errors(self) -> None:
        cases = {
            "unterminated": ("[broken\n", "invalid INI syntax"),
            "missing-separator": ("broken_key_without_separator\n", "invalid INI syntax"),
            "empty-key": (" = value\n", "invalid INI syntax"),
            "empty-section": ("[]\n", "invalid INI syntax"),
            "duplicate-section": ("[dup]\na = 1\n[dup]\nb = 2\n", "duplicated section"),
            "duplicate-global-key": ("a = 1\na = 2\n", "duplicated variable"),
            "duplicate-section-key": ("[sec]\na = 1\na = 2\n", "duplicated variable"),
        }

        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            for name, (content, message) in cases.items():
                with self.subTest(case=name):
                    path = self.write_ini(tmpdir, f"{name}.ini", content)
                    run = self.run_cli(os.fspath(path))
                    self.assertEqual(run.returncode, 1)
                    self.assertEqual(run.stdout, "")
                    self.assertEqual(run.stderr, f"ini2json: {message}: {path}\n")

    @case("parser: the same key name may exist globally and inside a section")
    def test_same_key_name_in_global_and_section_scope_is_allowed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = self.write_ini(Path(tmp), "scopes.ini", "name = global\n[sec]\nname = local\n")
            self.assert_json_output(
                self.run_cli(os.fspath(path)),
                {"name": "global", "sec": {"name": "local"}},
            )

    @case("cli: flags that require values fail cleanly when the value is omitted")
    def test_options_with_missing_values_fail_cleanly(self) -> None:
        for args, message in (
            (("--indent",), "ini2json: missing value for --indent"),
            (("--generate",), "ini2json: missing value for --generate"),
            (("--seed",), "ini2json: missing value for --seed"),
            (("--sections",), "ini2json: missing value for --sections"),
            (("--keys",), "ini2json: missing value for --keys"),
        ):
            with self.subTest(args=args):
                self.assert_failure(self.run_cli(*args), message)

    @case("cli: numeric bounds and enum validation reject malformed option values")
    def test_option_value_validation_and_bounds(self) -> None:
        cases = (
            (("--indent", "33"), "ini2json: indent must be an integer from 0 to 32"),
            (("--indent=-1",), "ini2json: indent must be an integer from 0 to 32"),
            (("--indent=abc",), "ini2json: indent must be an integer from 0 to 32"),
            (("--sections", "33"), "ini2json: sections must be an integer from 0 to 32"),
            (("--sections=-1",), "ini2json: sections must be an integer from 0 to 32"),
            (("--keys", "65"), "ini2json: keys must be an integer from 0 to 64"),
            (("--keys=abc",), "ini2json: keys must be an integer from 0 to 64"),
            (("--generate", "maybe"), "ini2json: generate kind must be valid or invalid"),
            (("--seed", "-1"), "ini2json: seed must be an unsigned 64-bit integer"),
            (("--seed=18446744073709551616",), "ini2json: seed must be an unsigned 64-bit integer"),
            (("--seed=abc",), "ini2json: seed must be an unsigned 64-bit integer"),
        )
        for raw_args, message in cases:
            with self.subTest(args=raw_args):
                self.assert_failure(self.run_cli(*raw_args), message)

    @case("generator: valid mode is deterministic for a fixed seed")
    def test_generate_valid_is_deterministic_and_seeded(self) -> None:
        first = self.run_cli("--generate", "valid", "--seed", "123", "--sections", "2", "--keys", "3")
        second = self.run_cli("--generate=valid", "--seed=123", "--sections=2", "--keys=3")

        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertEqual(first.stderr, "")
        self.assertEqual(first.stdout, second.stdout)
        self.assertTrue(first.stdout.startswith("; seed: 123\n"))
        self.assertIn("[", first.stdout)
        self.assertIn(" = ", first.stdout)

    @case("generator: valid output parses back and honors requested section and key counts")
    def test_generated_valid_output_parses_and_honors_section_and_key_counts(self) -> None:
        generated = self.run_cli("--generate", "valid", "--seed", "9", "--sections", "2", "--keys", "3")
        self.assertEqual(generated.returncode, 0, generated.stderr)

        with tempfile.TemporaryDirectory() as tmp:
            path = self.write_ini(Path(tmp), "generated.ini", generated.stdout)
            parsed = self.run_cli(os.fspath(path))
            payload = json.loads(parsed.stdout)

        global_keys = {key: value for key, value in payload.items() if not isinstance(value, dict)}
        sections = {key: value for key, value in payload.items() if isinstance(value, dict)}
        self.assertEqual(len(global_keys), 3)
        self.assertEqual(len(sections), 2)
        self.assertTrue(all(len(section) == 3 for section in sections.values()))

    @case("generator: valid mode allows the zero-sections zero-keys boundary")
    def test_generated_valid_allows_zero_sections_and_zero_keys(self) -> None:
        generated = self.run_cli("--generate", "valid", "--seed", "5", "--sections", "0", "--keys", "0")
        self.assertEqual(generated.returncode, 0, generated.stderr)
        self.assertEqual(generated.stdout, "; seed: 5\n")

    @case("generator: invalid mode is deterministic and emits ini the parser rejects")
    def test_generate_invalid_is_deterministic_and_produces_rejected_ini(self) -> None:
        first = self.run_cli("--generate", "invalid", "--seed", "42", "--sections", "2", "--keys", "3")
        second = self.run_cli("--generate=invalid", "--seed=42", "--sections=2", "--keys=3")

        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertEqual(first.stderr, "")
        self.assertEqual(first.stdout, second.stdout)
        self.assertTrue(first.stdout.startswith("; seed: 42\n"))

        with tempfile.TemporaryDirectory() as tmp:
            path = self.write_ini(Path(tmp), "invalid.ini", first.stdout)
            parsed = self.run_cli(os.fspath(path))
            self.assertEqual(parsed.returncode, 1)
            self.assertRegex(parsed.stderr, r"^ini2json: (invalid INI syntax|duplicated section|duplicated variable): .+invalid\.ini\n$")

    @case("generator: generate mode rejects an extra positional input file")
    def test_generate_mode_rejects_input_file_argument(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = self.write_ini(Path(tmp), "config.ini", "a = 1\n")
            self.assert_failure(
                self.run_cli("--generate", "valid", os.fspath(path)),
                "ini2json: generate mode does not accept an input file",
            )

    @case("generator: implicit random seed still appears on the first comment line")
    def test_generate_without_explicit_seed_still_emits_a_seed_comment(self) -> None:
        run = self.run_cli("--generate", "valid")
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertEqual(run.stderr, "")
        self.assertRegex(run.stdout.splitlines()[0], r"^; seed: \d+$")

    @case("parser: comments with leading whitespace and hash prefixes are ignored")
    def test_parser_ignores_indented_semicolon_and_hash_comments(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = self.write_ini(
                Path(tmp),
                "comments.ini",
                "   ; full line comment\n\t# another comment\nreal = value\n[sec]\n# comment\nnested = here\n",
            )
            self.assert_json_output(
                self.run_cli(os.fspath(path)),
                {"real": "value", "sec": {"nested": "here"}},
            )

    @case("parser: keys that appear after a section header remain in that current section")
    def test_keys_after_a_section_header_stay_in_that_section(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = self.write_ini(Path(tmp), "scope-flow.ini", "[alpha]\none = 1\ntwo = 2\n")
            self.assert_json_output(
                self.run_cli(os.fspath(path)),
                {"alpha": {"one": "1", "two": "2"}},
            )

    @case("parser: no trailing newline is accepted")
    def test_parser_accepts_file_without_trailing_newline(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = self.write_ini(Path(tmp), "no-newline.ini", "alpha = beta\n[sec]\nkey = value")
            self.assert_json_output(
                self.run_cli(os.fspath(path)),
                {"alpha": "beta", "sec": {"key": "value"}},
            )

    @case("formatting: indent zero keeps multiline json with no leading indentation")
    def test_indent_zero_preserves_multiline_output_without_left_padding(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = self.write_ini(Path(tmp), "indent-zero.ini", "alpha = beta\n[sec]\nkey = value\n")
            run = self.run_cli("--indent", "0", os.fspath(path))
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertEqual(run.stderr, "")
            self.assertEqual(run.stdout, '{\n"alpha": "beta",\n"sec": {\n"key": "value"\n}\n}\n')

    @case("formatting: repeated indent flags use the last provided numeric value")
    def test_repeated_indent_flags_use_the_last_value(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = self.write_ini(Path(tmp), "repeat-indent.ini", "alpha = beta\n")
            run = self.run_cli("--indent", "2", "--indent", "4", os.fspath(path))
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertEqual(run.stdout, '{\n    "alpha": "beta"\n}\n')

    @case("formatting: tab then indent uses tabs with the later indentation width")
    def test_tab_then_indent_uses_tab_char_with_updated_width(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = self.write_ini(Path(tmp), "tab-indent-order.ini", "alpha = beta\n")
            run = self.run_cli("--tab", "--indent", "3", os.fspath(path))
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertEqual(run.stdout, '{\n\t\t\t"alpha": "beta"\n}\n')

    @case("parser: output ordering is lexical for top-level keys and nested keys")
    def test_output_ordering_is_lexical(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = self.write_ini(
                Path(tmp),
                "ordering.ini",
                "zeta = last\nalpha = first\n[beta]\nz = 2\na = 1\n[alpha]\ny = 2\nx = 1\n",
            )
            run = self.run_cli("--compact", os.fspath(path))
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertEqual(
                run.stdout,
                '{"alpha":{"x":"1","y":"2"},"beta":{"a":"1","z":"2"},"zeta":"last"}\n',
            )

    @case("filesystem: extension checking is case-sensitive and requires literal .ini")
    def test_extension_check_is_case_sensitive(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = self.write_ini(Path(tmp), "upper.INI", "a = 1\n")
            run = self.run_cli(os.fspath(path))
            self.assertEqual(run.returncode, 1)
            self.assertEqual(run.stdout, "")
            self.assertEqual(run.stderr, f"ini2json: input file must have a .ini extension: {path}\n")

    @case("generator: short flags work for valid generation and preserve the explicit seed comment")
    def test_short_flags_work_for_valid_generation(self) -> None:
        run = self.run_cli("-g", "valid", "-s", "7")
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertEqual(run.stderr, "")
        self.assertTrue(run.stdout.startswith("; seed: 7\n"))

    @case("generator: maximum declared section and key bounds are accepted and parse back correctly")
    def test_generator_accepts_maximum_section_and_key_bounds(self) -> None:
        generated = self.run_cli("--generate", "valid", "--seed", "11", "--sections", "32", "--keys", "64")
        self.assertEqual(generated.returncode, 0, generated.stderr)

        with tempfile.TemporaryDirectory() as tmp:
            path = self.write_ini(Path(tmp), "max-bounds.ini", generated.stdout)
            parsed = self.run_cli("--compact", os.fspath(path))
            payload = json.loads(parsed.stdout)

        global_keys = {key: value for key, value in payload.items() if not isinstance(value, dict)}
        sections = {key: value for key, value in payload.items() if isinstance(value, dict)}
        self.assertEqual(len(global_keys), 64)
        self.assertEqual(len(sections), 32)
        self.assertTrue(all(len(section) == 64 for section in sections.values()))


def parse_args() -> tuple[argparse.Namespace, list[str]]:
    parser = argparse.ArgumentParser(add_help=True)
    parser.add_argument("binary", nargs="?", help="path to the ini2json executable")
    parser.add_argument("--binary", dest="binary_flag", help="path to the ini2json executable")
    parser.add_argument("--list-tests", action="store_true", help="list test case names and exit")
    return parser.parse_known_args()


if __name__ == "__main__":
    args, unittest_args = parse_args()
    binary = args.binary_flag or args.binary
    if not binary:
        raise SystemExit("usage: python tests/cli_behavior_suite.py /path/to/ini2json")

    BINARY_PATH = Path(binary).resolve()
    if not BINARY_PATH.is_file():
        raise SystemExit(f"binary does not exist: {BINARY_PATH}")
    if not os.access(BINARY_PATH, os.X_OK):
        raise SystemExit(f"binary is not executable: {BINARY_PATH}")

    loader = unittest.defaultTestLoader
    suite = loader.loadTestsFromTestCase(Ini2JsonCliTests)

    if args.list_tests:
        for index, test in enumerate(iter_test_cases(suite), start=1):
            print(f"{index:02d}. {test.shortDescription() or str(test)}")
        raise SystemExit(0)

    runner = NamedTextTestRunner(verbosity=2)
    result = runner.run(suite)
    raise SystemExit(0 if result.wasSuccessful() else 1)
