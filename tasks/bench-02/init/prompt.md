# Task: Write a Sparse Checkout Implementation Guide for libgit2

Inspect this libgit2 checkout and produce a `document.md` guide for implementing sparse checkout support. Do not implement code. Your output should be a technical implementation guide that tells a future libgit2 contributor where the feature belongs, which files matter, and where to start.

Write the final guide to `document.md` in the workspace root. Replace the file if it already exists.

The target feature is a public sparse-checkout management API that:

- writes `.git/info/sparse-checkout`
- toggles `core.sparseCheckout` and `core.sparseCheckoutCone`
- updates `GIT_INDEX_ENTRY_SKIP_WORKTREE` on full-index entries
- updates the working directory safely

The guide must include file and line references from this local repository. Read the relevant files directly and cite concrete anchors for the current behavior.

Cover at least these areas:

- Existing support versus missing behavior.
- Relevant structs and types, especially index flags, checkout internals, config cache entries, pathspec or pattern matching, and tests.
- A suggested public API shape, including options/versioning conventions.
- An implementation sequence that starts with configuration and sparse-checkout file management, then pattern parsing, index flag recalculation, checkout/workdir update, and status/diff validation.
- Edge cases: dirty excluded files, force behavior, conflicts, missing excluded files, included modified files, bare repositories, cone mode, and index read/write persistence.
- A focused test plan under `tests/libgit2`.

Important constraints:

- Do not write implementation code or patches.
- Do not propose sparse-index support; this task is full-index sparse checkout management only.
- Explain whether existing pathspec matching is sufficient for sparse-checkout patterns.
- Explain how checkout should be reused for materialization/removal instead of hand-writing file updates.
- Respect libgit2 conventions, including C89 style, public header organization, option struct versioning, and clar tests.
- Do not modify files under `libgit2/`.
