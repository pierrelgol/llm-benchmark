You are working in a copied benchmark workspace.

Your task is to turn this starter project into a native C TOML v1.1 decoder that passes the bundled `toml-test` decoder suite.

Read `spec.md`, `toml.abnf`, the headers and source in `include/` and `src/`, and the vendored tester contract under `../tester/toml-test` as needed. The implementation must be your own code in this workspace. Do not shell out to another TOML parser, do not embed another language runtime, and do not wrap an external library or service.

Required end state:

- `make` succeeds in the workspace root.
- The built executable is `./toml`.
- `./toml` reads TOML from `stdin`.
- On valid TOML, `./toml` writes tagged JSON to `stdout` in the exact format expected by `toml-test` and exits with code `0`.
- On invalid TOML, `./toml` exits non-zero and should write a useful error to `stderr`.
- Target TOML version is `1.1`.

Work autonomously and use long-horizon judgment:

- Inspect the local spec and tester before making design decisions.
- Implement the decoder incrementally, but keep the final interface aligned to the tester contract at all times.
- Run local checks during the round when useful, especially `make` and targeted tester invocations.
- Preserve work already completed in prior rounds; do not restart from scratch unless the current code is unsalvageable.

Focus on correctness over cosmetics. The benchmark is driven by the test suite, so matching the decoder contract and TOML semantics matters more than internal architecture.

Finish with a short note describing what changed, what passes, and any known remaining gaps.
