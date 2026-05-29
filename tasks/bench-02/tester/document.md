# Sparse Checkout Implementation Guide

## Feature Goal

Implement full-index sparse checkout management in libgit2. This feature should expose a public API that owns `.git/info/sparse-checkout`, toggles `core.sparseCheckout` and `core.sparseCheckoutCone`, recalculates `GIT_INDEX_ENTRY_SKIP_WORKTREE` on ordinary index entries, persists the index, and updates the workdir safely.

Do not implement sparse-index. The index should continue to contain normal entries for tracked paths; sparse checkout only changes which paths are expected in the workdir and which entries carry the skip-worktree bit.

## Existing Building Blocks

The skip-worktree flag already exists in the public index API. `include/git2/index.h:132` defines `git_index_entry_extended_flag_t`; `include/git2/index.h:134` is `GIT_INDEX_ENTRY_SKIP_WORKTREE`, and `include/git2/index.h:136` includes it in `GIT_INDEX_ENTRY_EXTENDED_FLAGS`, the set of extended flags that can be written to disk.

Index persistence already keeps the relevant extended flag:

- `src/libgit2/index.c:1096` copies only `GIT_INDEX_ENTRY_EXTENDED_FLAGS` when duplicating entries without cache data.
- `src/libgit2/index.c:2587` reads extended flags from on-disk index entries.
- `src/libgit2/index.c:2849` marks an entry as extended when its persistent extended flags are present.
- `src/libgit2/index.c:2955` writes `entry->flags_extended & GIT_INDEX_ENTRY_EXTENDED_FLAGS`.

Diff/status already quiets entries marked skip-worktree. `src/libgit2/diff_generate.c:848` documents support for the skip-worktree bit, and `src/libgit2/diff_generate.c:849` treats such entries as unmodified. This is useful validation coverage, but it is not a sparse-checkout management implementation.

What is missing is the orchestration layer: public API, config updates, sparse-checkout file parsing and writing, index flag recalculation, safe workdir update, and tests for Git-compatible sparse checkout behavior.

## Files To Touch

- `include/git2.h`: include the new public sparse checkout header.
- `include/git2/sparse_checkout.h`: define the public API, mode enum, options struct, version/init macro, init function, and function declarations.
- `src/libgit2/sparse_checkout.c`: implement public entry points and internal sparse checkout orchestration.
- `src/libgit2/sparse_checkout.h`: hold internal parser/matcher declarations and helpers shared with checkout or tests if needed.
- `src/libgit2/config_cache.c`: add cached lookups for `core.sparseCheckout` and `core.sparseCheckoutCone` if implementation code needs fast internal config checks.
- `src/libgit2/repository.h`: extend `git_configmap_item` and defaults for those config cache keys.
- `src/libgit2/checkout.c`: integrate sparse checkout workdir transitions with existing checkout action calculation instead of open-coding file writes and deletes.
- `src/libgit2/pathspec.c` or a new matcher module: reuse matching primitives where correct, but sparse-checkout patterns are gitignore-like and ordered, so a dedicated matcher may be required.
- `tests/libgit2`: add focused sparse checkout tests, probably in a new `sparse_checkout` area plus checkout/status/index regression coverage where appropriate.

## Public API Proposal

Add a public header `include/git2/sparse_checkout.h` and include it from `include/git2.h`.

Suggested mode enum:

```c
typedef enum {
	GIT_SPARSE_CHECKOUT_MODE_DEFAULT = 0,
	GIT_SPARSE_CHECKOUT_MODE_PATTERN = 1,
	GIT_SPARSE_CHECKOUT_MODE_CONE = 2
} git_sparse_checkout_mode_t;
```

Suggested options shape:

```c
#define GIT_SPARSE_CHECKOUT_OPTIONS_VERSION 1
#define GIT_SPARSE_CHECKOUT_OPTIONS_INIT { GIT_SPARSE_CHECKOUT_OPTIONS_VERSION }

typedef struct git_sparse_checkout_options {
	unsigned int version;
	git_sparse_checkout_mode_t mode;
	unsigned int flags;
	git_checkout_options checkout_options;
} git_sparse_checkout_options;

GIT_EXTERN(int) git_sparse_checkout_options_init(
	git_sparse_checkout_options *opts,
	unsigned int version);
```

Suggested functions:

```c
GIT_EXTERN(int) git_sparse_checkout_set(
	git_repository *repo,
	const git_strarray *patterns,
	const git_sparse_checkout_options *opts);

GIT_EXTERN(int) git_sparse_checkout_disable(
	git_repository *repo,
	const git_sparse_checkout_options *opts);

GIT_EXTERN(int) git_sparse_checkout_list(
	git_strarray *out,
	git_repository *repo);
```

`git_sparse_checkout_set` should validate that `repo` is non-bare, normalize/write patterns to `.git/info/sparse-checkout`, set `core.sparseCheckout=true`, set `core.sparseCheckoutCone` according to mode, recalculate index flags, write the index, and update the workdir.

`git_sparse_checkout_disable` should clear config or set sparse checkout keys false according to libgit2 config conventions, clear skip-worktree flags, write the index, and materialize files through checkout.

`git_sparse_checkout_list` should read `.git/info/sparse-checkout` and return the configured pattern lines. It should follow existing ownership rules for `git_strarray` returns.

## Implementation Plan

1. Implement config and file management first. Reject bare repositories early. Use repository path helpers to write `.git/info/sparse-checkout` under the repository common dir or git dir as appropriate. Update `core.sparseCheckout` and `core.sparseCheckoutCone` in the repo config, then clear the repository config-map cache if new cache entries are added.

2. Implement sparse-checkout pattern parsing second. Support ordered include/exclude behavior and comments/blank lines as Git expects. Cone mode should validate and/or normalize cone-compatible directory patterns separately from arbitrary pattern mode.

3. Recalculate index flags third. Load the repository index, iterate all stage-0 entries, match each path against the sparse specification, set `GIT_INDEX_ENTRY_SKIP_WORKTREE` for excluded paths, and clear it for included paths. Preserve non-stage-0 conflict entries; do not erase conflict stages while recalculating sparse state.

4. Update checkout/workdir fourth. Use checkout machinery to remove excluded paths and materialize included paths. Default behavior should protect dirty excluded files and report conflicts. A force option can opt into removal of dirty files, but it should be explicit and routed through checkout semantics.

5. Validate status and diff fifth. Existing diff generation treats skip-worktree entries as unmodified at `src/libgit2/diff_generate.c:848`, so tests should prove missing excluded files are quiet while modifications to included files are still reported.

## Checkout Notes

Checkout already has the structures and decision points needed for safe workdir updates. `src/libgit2/checkout.c:51` defines `checkout_data`, which carries the repository, target iterator, diff, options, index, remove list, and other state for a checkout operation.

`src/libgit2/checkout.c:1312` starts `checkout_get_actions`, which computes per-delta checkout actions against the workdir. Sparse checkout should feed desired target state into this machinery rather than hand-writing workdir files. `src/libgit2/checkout.c:1372` shows the conflict gate: if checkout actions include conflicts and `GIT_CHECKOUT_ALLOW_CONFLICTS` is not set, checkout returns `GIT_ECONFLICT`. Sparse checkout should preserve that behavior for dirty excluded paths unless an explicit force strategy is requested.

`src/libgit2/checkout.c:2369` starts `checkout_data_init`, the central initialization path for checkout options and repository state. If sparse checkout needs extra internal checkout options or target state, integrate near this initialization path or through existing public checkout calls in `sparse_checkout.c`.

## Pattern Matching Notes

Existing pathspec internals are close but not necessarily sufficient. `src/libgit2/pathspec.c:66` builds a vector of fnmatch patterns, `src/libgit2/pathspec.c:138` begins single-pattern matching, and `src/libgit2/pathspec.c:196` matches a path against the vectorized pathspec.

Sparse-checkout patterns are closer to gitignore patterns than ordinary pathspecs: they are ordered, negation-sensitive, directory-oriented, and have cone-mode semantics. Normal pathspec matching may be useful for fnmatch support, case folding, and path normalization, but the sparse-checkout matcher must preserve Git sparse pattern semantics. If `pathspec.c` cannot express ordered include/exclude decisions exactly, add a dedicated sparse matcher and share only lower-level matching helpers.

## Testing

Tests should follow the clar setup documented in `tests/README.md:16`. Useful existing anchors include `tests/libgit2/checkout/index.c:147`, which tests checkout pathspec behavior, and `tests/libgit2/status/worktree.c:51`, where status assertions are centralized.

Add coverage for:

- enabling sparse checkout writes `.git/info/sparse-checkout`, sets `core.sparseCheckout`, sets or clears `core.sparseCheckoutCone`, updates index flags, and removes excluded clean files
- disabling sparse checkout clears skip-worktree flags, updates config, writes the index, and materializes files again
- cone mode accepts directory-shaped input and rejects or normalizes incompatible patterns
- dirty excluded files fail by default with a checkout conflict
- force mode removes dirty excluded files only when explicitly requested
- missing excluded files are quiet in status
- modifications to included files are reported in status and diff
- index write/read persistence keeps `GIT_INDEX_ENTRY_SKIP_WORKTREE`
- bare repositories are rejected
- conflict stages are preserved when recalculating sparse state

## Pitfalls

- Do not clear or collapse conflict stages while updating sparse flags.
- Do not invent sparse-index support; this feature is full-index sparse checkout only.
- Do not hand-write checkout file materialization or deletion when checkout can compute safe actions and conflict behavior.
- Do not assume ordinary pathspec matching is equivalent to sparse-checkout pattern matching.
- Do not leave config cache entries stale after writing sparse checkout config.
- Do not ignore libgit2 conventions: C89-compatible declarations, public API versioning, `GIT_EXTERN`, `GIT_*_INIT` macros, repository ownership rules, error reporting conventions, and clar-based tests.
