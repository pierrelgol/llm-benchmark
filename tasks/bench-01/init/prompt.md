You are working in a copied benchmark workspace.

Your task is to study the original `ini2json/` project and reimplement its command-line program in idiomatic Rust inside `rust/`.

The Rust implementation must match the observable behavior of the original CLI exactly. This includes CLI flags, short and long option forms, help text, exit codes, stdout versus stderr routing, error strings, JSON formatting, lexical output ordering, deterministic generator behavior, numeric bounds, file handling, parsing behavior, and edge cases.

Do not call, embed, wrap, bind to, or partially delegate to the C or C++ implementation. Do not use FFI, generated bindings, subprocess calls to the original binary, shell wrappers, or mixed-language reuse. The final solution must be a fully native Rust implementation.

Update the Rust project so the release build emits an executable named `ini2json`. The benchmark tester will run:

```sh
cargo build --release
./target/release/ini2json
```

You may inspect every file in the workspace, especially the original source and README under `ini2json/`. Keep all implementation work in `rust/`.

Finish with a short note describing what changed and any known limitations.
