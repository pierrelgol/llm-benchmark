# Sparse Checkout Implementation Guide for libgit2

## Overview

This guide describes how to implement full-index sparse checkout management in libgit2. The feature enables a caller to:

1. Write `.git/info/sparse-checkout` pattern files.
2. Toggle `core.sparseCheckout` and `core.sparseCheckoutCone` config keys.
3. Recalculate `GIT_INDEX_ENTRY_SKIP_WORKTREE` on every index entry according to the sparse patterns.
4. Update the working directory (materialize included paths, remove excluded ones) via the existing checkout machinery.

Sparse checkout is listed as a project in `docs/projects.md:93`. No implementation currently exists in the source tree. The only reference to "sparse" in the codebase outside documentation and build scripts is that line.

---

## 1. Existing Support vs Missing Behavior

### What already exists

| Capability | Location | Notes |
|---|---|---|
| `GIT_INDEX_ENTRY_SKIP_WORKTREE` flag definition | `include/git2/index.h:134` | `(1 << 14)` in the public header |
| Extended-flags mask includes SKIP_WORKTREE | `include/git2/index.h:136` | `GIT_INDEX_ENTRY_EXTENDED_FLAGS = (INTENT_TO_ADD \| SKIP_WORKTREE)` |
| Index read preserves extended flags | `src/libgit2/index.c:2577-2591` | When `GIT_INDEX_ENTRY_EXTENDED` is set, reads `flags_extended` from disk |
| Index write persists extended flags | `src/libgit2/index.c:2840-3021` | `is_index_extended()` at :2840 checks for extended flags; `write_disk_entry()` at :2953 writes them using the long-entry format with `flags_extended` field (`entry_long` macro, :86-92) |
| Extended-flag copy on entry duplication | `src/libgit2/index.c:1096` | `index_entry_cpy_nocache` copies `flags_extended & GIT_INDEX_ENTRY_EXTENDED_FLAGS` |
| Diff generation respects SKIP_WORKTREE | `src/libgit2/diff_generate.c:849-850` | Sets status to `GIT_DELTA_UNMODIFIED` when the old index entry has SKIP_WORKTREE set |
| Index version handling for extended entries | `src/libgit2/index.c:37-41, 2840-2856` | Version 3+ is required for extended flags; `is_index_extended()` determines whether to write v3 |

### What is missing (the implementation gap)

| Gap | Description |
|---|---|
| Config cache entries | No configmap items for `core.sparseCheckout` or `core.sparseCheckoutCone` in `src/libgit2/repository.h:41-59` / `src/libgit2/config_cache.c:73-89` |
| Sparse-checkout file I/O | No code reads or writes `.git/info/sparse-checkout`. The path would be constructed via `GIT_REPOSITORY_ITEM_INFO` (`src/libgit2/repository.c:61`) + filename `"sparse-checkout"`, following the pattern used for `.git/info/exclude` at `ignore.c:354-359` |
| Pattern matching against index entries | No function iterates the full index and sets/clears SKIP_WORKTREE based on sparse patterns. The existing pathspec infrastructure (`src/libgit2/pathspec.c`) can be reused (see Section 3). |
| Public API surface | No `git_sparsecheckout_*` functions exist in any header. A new public header `include/git2/sparse-checkout.h` is needed. |
| Checkout integration for materialization/removal | The checkout code (`src/libgit2/checkout.c`) does not know about sparse patterns. It must be invoked to materialize included files and remove excluded ones, rather than hand-writing file updates. |
| Status/diff awareness beyond diff_generate | `diff_generate.c:849` handles SKIP_WORKTREE for diffs, but status operations (`src/libgit2/status.c`) do not yet account for sparse checkout semantics (e.g., excluded modified files should appear clean). |

---

## 2. Relevant Structs and Types

### Index entry flags

**Public header**: `include/git2/index.h`

- `struct git_index_entry` (:58-75): Contains `flags` (`uint16_t`, :71) and `flags_extended` (`uint16_t`, :72).
- `GIT_INDEX_ENTRY_SKIP_WORKTREE = (1 << 14)` (:134) — the core flag for sparse checkout.
- `GIT_INDEX_ENTRY_INTENT_TO_ADD = (1 << 13)` (:133) — another extended flag, coexists with SKIP_WORKTREE.
- `GIT_INDEX_ENTRY_EXTENDED_FLAGS` (:136) — mask of on-disk extended flags; both INTENT_TO_ADD and SKIP_WORKTREE are included.
- `GIT_INDEX_ENTRY_UPTODATE = (1 << 2)` (:138) — in-memory only, used during add operations.

**Internal header**: `src/libgit2/index.h`

- `struct git_index` (:29-62): Internal index structure with `entries` vector (:36), `version` (:61), and `dirty` flag (:48).
- Index version constants in `index.c:37-41`: default=2, extended=3, compressed=4. Extended flags (including SKIP_WORKTREE) require v3+.

### Checkout internals

**Public header**: `include/git2/checkout.h`

- `struct git_checkout_options` (:317-391): Full options struct with:
  - `paths` (`git_strarray`, :364) — pathspec filtering for checkout scope.
  - `baseline` / `baseline_index` (:372, :378) — expected working directory content.
  - `checkout_strategy` (:325-326) — flags like `GIT_CHECKOUT_FORCE`, `GIT_CHECKOUT_SAFE`.
- Option versioning: `GIT_CHECKOUT_OPTIONS_VERSION = 1` (:395), init macro at :398.
- Public entry points: `git_checkout_head()` (:431), `git_checkout_index()` (:444), `git_checkout_tree()` (:460).

**Internal implementation**: `src/libgit2/checkout.c`

- `struct checkout_data` (:51-77): Internal data structure for checkout operations.
- `git_checkout_iterator()` (:2555-2696): Main checkout loop — creates diff, gets actions, performs removes/updates/conflicts. This is the function to reuse for sparse-checkout materialization.
- Index write at end of checkout: :2684-2686 calls `git_index_write(data.index)`.

### Config cache entries

**Internal header**: `src/libgit2/repository.h`

- `enum git_configmap_item` (:41-59): All cached config keys. Currently ends at `GIT_CONFIGMAP_LONGPATHS` (:57), followed by `GIT_CONFIGMAP_CACHE_MAX` (:58).
- `struct git_repository` (:137-173): Contains `configmap_cache[GIT_CONFIGMAP_CACHE_MAX]` (:171) for cached config values.

**Implementation**: `src/libgit2/config_cache.c`

- `_configmaps[]` array (:73-89): Maps config names to items. Each entry has `{name, maps, map_count, default_value}`.
- `git_config__configmap_lookup()` (:91-110): Looks up a config value by item ID.
- `git_repository__configmap_lookup()` (:112-132): Cached lookup with atomic cache.

To add sparse checkout support:
1. Add `GIT_CONFIGMAP_SPARSE_CHECKOUT` and `GIT_CONFIGMAP_SPARSE_CHECKOUT_CONE` to the enum in `repository.h` before `GIT_CONFIGMAP_CACHE_MAX`.
2. Add corresponding entries to `_configmaps[]` in `config_cache.c`.

### Pathspec / pattern matching

**Public header**: `include/git2/pathspec.h`

- `git_pathspec_new()` (:89) — compile a pathspec from a string array.
- `git_pathspec_matches_path()` (:112) — match a single path against compiled spec.
- `git_pathspec_match_index()` (:166) — match pathspec against index entries.

**Internal header**: `src/libgit2/pathspec.h`

- `struct git_pathspec` (:19-24): Compiled pathspec with prefix, vector of patterns, string pool.
- `git_pathspec__vinit()` (:49) — builds a vector of fnmatch patterns from string array.
- `git_pathspec__match()` (:62-68) — matches a single path against the vectorized pathspec.

**Implementation**: `src/libgit2/pathspec.c`

- `git_pathspec_prefix()` (:21-46): Extracts common non-wildcard prefix.
- `git_pathspec__vinit()` (:66-103): Builds fnmatch pattern vector using `git_attr_fnmatch__parse()`.
- `pathspec_match_one()` (:138-150): Single-match function using wildmatch.

### Ignore file infrastructure (pattern for sparse-checkout loading)

**Internal header**: `src/libgit2/ignore.h`

- `struct git_ignores` (:27-36): Three-tier ignore system with internal, path-based, and global ignores.
- Constants: `GIT_IGNORE_FILE = ".gitignore"` (:16), `GIT_IGNORE_FILE_INREPO = "exclude"` (:17).

**Implementation**: `src/libgit2/ignore.c`

- `parse_ignore_file()` (:170-243): Parses ignore rule text into fnmatch patterns.
- `push_ignore_file()` (:245-266): Loads an ignore file from disk via attr cache.
- Loading `.git/info/exclude`: :354-359 uses `GIT_REPOSITORY_ITEM_INFO` + `push_ignore_file()` with `GIT_IGNORE_FILE_INREPO`.

### Attr fnmatch infrastructure (pattern matching engine)

**Internal header**: `src/libgit2/attr_file.h`

- `struct git_attr_fnmatch` (:73-79): Pattern structure with `pattern`, `length`, `containing_dir`, `flags`.
- Flags: `GIT_ATTR_FNMATCH_NEGATIVE` (:26), `GIT_ATTR_FNMATCH_DIRECTORY` (:27), `GIT_ATTR_FNMATCH_FULLPATH` (:28), etc.
- `git_attr_fnmatch__parse()` (:209-213): Parses a single fnmatch rule from text.
- `git_attr_fnmatch__match()` (:215-217): Matches a path against an fnmatch rule.

---

## 3. Is Existing Pathspec Matching Sufficient for Sparse-Checkout Patterns?

**Yes, with caveats.** The existing pathspec infrastructure (`src/libgit2/pathspec.c`) uses `git_attr_fnmatch` patterns under the hood (see :66-103), which are the same fnmatch-based patterns used by `.gitignore` and `.gitattributes`. Sparse-checkout patterns in non-cone mode use the same gitignore-style syntax, so the existing machinery is directly applicable.

**Cone mode requires special handling.** Git's cone-mode sparse checkout uses a simplified pattern format:
- `/` at the top level means "include everything at root" (or nothing if negated).
- `*/` means "include all directories".
- `<path>/` includes a specific directory and everything beneath it.
- `<path>` (no trailing slash) includes a specific file.

The existing pathspec matcher does not natively understand cone-mode semantics. For cone mode, you would need either:
1. A dedicated cone-mode parser that translates cone patterns into equivalent fnmatch patterns before passing them to the existing infrastructure, or
2. A separate matching function for cone mode.

**Recommendation**: Implement non-cone mode first using the existing pathspec/fnmatch infrastructure directly. For cone mode, add a translation layer that converts cone patterns to standard fnmatch patterns (e.g., `foo/` becomes `foo/**`). This keeps the implementation simple and reuses tested code.

---

## 4. Suggested Public API Shape

### New header: `include/git2/sparse-checkout.h`

Following libgit2 conventions, a new public header should be created with versioned option structs. The pattern to follow is established by existing APIs like checkout (`GIT_CHECKOUT_OPTIONS_VERSION`, :395) and index options (`GIT_INDEX_OPTIONS_VERSION`, :214).

### Proposed API functions

```c
/* Initialize sparse-checkout on a repository */
typedef struct {
    unsigned int version;
    /* Whether to enable core.sparseCheckout (true = enabled, false = disabled) */
    bool enable_sparse_checkout;
    /* Whether to use cone mode (sets core.sparseCheckoutCone) */
    bool use_cone;
    /* Patterns for the sparse-checkout file. If NULL, reads from disk. */
    const git_strarray *patterns;
} git_sparsecheckout_init_options;

#define GIT_SPARSECHECKOUT_INIT_OPTIONS_VERSION 1
#define GIT_SPARSECHECKOUT_INIT_OPTIONS_INIT { GIT_SPARSECHECKOUT_INIT_OPTIONS_VERSION }

int git_sparsecheckout_init(
    git_repository *repo,
    const git_sparsecheckout_init_options *opts);

/* Update the sparse-checkout patterns and recalculate index flags */
typedef struct {
    unsigned int version;
    /* New patterns to write. If NULL, only recalculates from existing file. */
    const git_strarray *patterns;
    /* Force working directory updates (removes excluded files) */
    bool force;
} git_sparsecheckout_update_options;

#define GIT_SPARSECHECKOUT_UPDATE_OPTIONS_VERSION 1
#define GIT_SPARSECHECKOUT_UPDATE_OPTIONS_INIT { GIT_SPARSECHECKOUT_UPDATE_OPTIONS_VERSION }

int git_sparsecheckout_update(
    git_repository *repo,
    const git_sparsecheckout_update_options *opts);

/* Query whether sparse checkout is enabled */
bool git_sparsecheckout_enabled(git_repository *repo);

/* Get the current sparse-checkout patterns as a strarray (caller frees) */
int git_sparsecheckout_patterns(
    git_strarray *out,
    git_repository *repo);

/* Check if a path would be included by the current sparse patterns */
bool git_sparsecheckout_path_included(
    git_repository *repo,
    const char *path);
```

### Versioning conventions

Follow the established pattern from `include/git2/checkout.h:395-412`:
1. Define a version constant (e.g., `GIT_SPARSECHECKOUT_INIT_OPTIONS_VERSION`).
2. Provide an init macro (`GIT_SPARSECHECKOUT_INIT_OPTIONS_INIT`) that sets only the version field.
3. Provide an init function (`git_sparsecheckout_init_options_init`) for dynamic initialization.
4. In implementation, validate with `GIT_ERROR_CHECK_VERSION(proposed, VERSION, "struct_name")` (see `src/libgit2/checkout.c:2391-2392`).

### Public header organization

The new header should be added to `include/git2/sparse-checkout.h`. It must be included in the build system (`src/libgit2/CMakeLists.txt`) and follow C89 style (no C99 features, no inline functions in headers for public API). The header should use `GIT_BEGIN_DECL` / `GIT_END_DECL` guards like all other public headers.

---

## 5. Implementation Sequence

### Phase 1: Configuration and sparse-checkout file management

**Files to modify**:
- `src/libgit2/repository.h:41-59` — add configmap enum entries.
- `src/libgit2/config_cache.c:73-89` — add `_configmaps[]` entries for `core.sparsecheckout` and `core.sparsecheckoutcone`.

**New files**:
- `include/git2/sparse-checkout.h` — public API header.
- `src/libgit2/sparse_checkout.h` — internal header with private declarations.
- `src/libgit2/sparse_checkout.c` — implementation.

**What to implement**:
1. Configmap entries for reading/writing `core.sparseCheckout` and `core.sparseCheckoutCone`. Use the existing config API (`include/git2/config.h`) for writes: `git_config_set_bool()`, `git_config_delete_entry()`.
2. File I/O for `.git/info/sparse-checkout`:
   - Read path via `git_repository__item_path()` with `GIT_REPOSITORY_ITEM_INFO` (see `src/libgit2/repository.c:61`) + append `"sparse-checkout"`.
   - Follow the pattern from `ignore.c:354-359` for loading `.git/info/exclude`: use `git_str` to build the path, then read file contents.
   - Parse patterns line by line (similar to `parse_ignore_file()` at `ignore.c:170-243`). Each non-empty, non-comment line is a pattern.
   - Write patterns back to disk when updated.

### Phase 2: Pattern parsing and matching

**What to implement**:
1. For non-cone mode: Use the existing pathspec infrastructure directly. Parse each sparse-checkout pattern through `git_attr_fnmatch__parse()` (`src/libgit2/attr_file.h:209-213`) with appropriate flags (sparse patterns are always full-path anchored, so set `GIT_ATTR_FNMATCH_FULLPATH`).
2. For cone mode: Implement a translation layer that converts cone patterns to fnmatch equivalents:
   - `/` → match root-level files only
   - `*/` → match all directories recursively (`**/`)
   - `<dir>/` → `<dir>/**` (include directory and everything beneath)
   - `<file>` → exact path match
3. Provide a function `sparse_checkout__path_included(repo, path)` that returns whether a given index entry path matches the sparse patterns.

### Phase 3: Index flag recalculation

**Files to modify**: None new — this logic lives in `src/libgit2/sparse_checkout.c`.

**What to implement**:
1. Iterate all entries in the index using `git_index_iterator_new()` / `git_index_iterator_next()` (see `include/git2/index.h:604-624`).
2. For each entry, determine if it should have SKIP_WORKTREE set based on sparse patterns.
3. Set or clear `GIT_INDEX_ENTRY_SKIP_WORKTREE` in the entry's `flags_extended` field. Also ensure `GIT_INDEX_ENTRY_EXTENDED` is set in `flags` when extended flags are present (see `index.c:2840-2856` for the pattern).
4. Mark the index as dirty and write it via `git_index_write()` (`include/git2/index.h:394`).

**Important**: The index must be version 3+ to persist extended flags. If the current index is v2, upgrade it (see `git_index_set_version()`, :366). The existing code in `is_index_extended()` (:2840) and `write_disk_entry()` (:2953-2977) already handles this correctly — if any entry has extended flags, the index will be written as v3.

### Phase 4: Checkout / working directory update

**Key principle**: Reuse the existing checkout machinery (`src/libgit2/checkout.c`) rather than hand-writing file updates. The checkout code already handles all the edge cases of file creation, removal, conflict detection, and notification callbacks.

**What to implement**:
1. After recalculating SKIP_WORKTREE flags, invoke `git_checkout_index()` (see :444) with:
   - The repository's index as the target.
   - A pathspec containing all excluded paths for removal.
   - Strategy flags: `GIT_CHECKOUT_FORCE` to remove excluded files that exist in the working directory but are not in the sparse set. Use `GIT_CHECKOUT_REMOVE_UNTRACKED` and/or `GIT_CHECKOUT_REMOVE_IGNORED` as appropriate.
2. Alternatively, build a two-phase approach:
   - Phase A: Remove excluded paths from the working directory using checkout with a pathspec of excluded files and `GIT_CHECKOUT_FORCE`.
   - Phase B: Materialize included paths that are missing from the working directory using `git_checkout_index()` with a pathspec of included files.

**How to determine which paths to include/exclude**: Use the pattern matching function from Phase 2 against all index entries. Build two `git_strarray` lists: one for included paths, one for excluded paths. Pass these as `paths` in `git_checkout_options`.

### Phase 5: Status / diff validation

**Files to review/modify**:
- `src/libgit2/diff_generate.c:849-850` — already handles SKIP_WORKTREE by returning `GIT_DELTA_UNMODIFIED`. Verify this is sufficient.
- `src/libgit2/status.c` — may need adjustments so that excluded files with local modifications do not appear as dirty in status output.

**What to verify**:
1. Confirm that `diff_generate.c:849` correctly treats SKIP_WORKTREE entries as unmodified for all diff operations (index-to-workdir, tree-to-index, etc.).
2. Check that status operations (`git_status_foreach`, `git_status_list_new`) properly skip excluded files or mark them appropriately. The existing code may already handle this through the diff layer, but needs verification.

---

## 6. Edge Cases

### Dirty excluded files

When an excluded file has local modifications in the working directory:
- With safe mode (`GIT_CHECKOUT_SAFE`): Checkout should refuse to remove the dirty file and report a conflict via `notify_cb`. The caller decides whether to proceed.
- With force mode (`GIT_CHECKOUT_FORCE`): Checkout overwrites or removes the dirty file, discarding local changes.

**Implementation note**: Use the checkout notification callback (`git_checkout_notify_cb`, `include/git2/checkout.h:275-281`) with `GIT_CHECKOUT_NOTIFY_DIRTY` (:237) to inform the caller about dirty excluded files before they are removed.

### Force behavior

The `force` flag in `git_sparsecheckout_update_options` controls whether working directory updates proceed despite conflicts:
- `force = false`: Use `GIT_CHECKOUT_SAFE`. Abort on conflicts (dirty excluded files, missing included files that can't be materialized).
- `force = true`: Use `GIT_CHECKOUT_FORCE`. Overwrite or remove conflicting files.

### Conflicts

Index entries in conflict (stage > 0) should be handled carefully:
- Conflict entries have stage values of 1, 2, or 3 (`include/git2/index.h:170-190`).
- If a conflicted path is excluded by sparse patterns, the conflict entries should still have SKIP_WORKTREE set. The checkout code has `GIT_CHECKOUT_SKIP_UNMERGED` (:153) and `GIT_CHECKOUT_USE_OURS` / `GIT_CHECKOUT_USE_THEIRS` (:155-157) for handling unmerged entries.
- Recommendation: When updating sparse patterns, skip conflict entries during flag recalculation (leave them as-is). The user should resolve conflicts before changing sparse patterns.

### Missing excluded files

If an excluded file does not exist in the working directory and has SKIP_WORKTREE set, this is a valid state — no action needed. The checkout code will simply skip it because there's nothing to remove.

### Included modified files

An included file with local modifications should be left untouched during sparse-checkout updates. The checkout code handles this via `GIT_CHECKOUT_SAFE` (default) which preserves uncommitted changes that don't conflict with the target.

### Bare repositories

Sparse checkout is meaningless for bare repositories (no working directory). All public API functions must check `git_repository_is_bare()` and return `GIT_EBAREREPO`. The helper `git_repository__ensure_not_bare()` (`src/libgit2/repository.h:217-230`) can be used internally.

### Cone mode

Cone mode is a simplified pattern format that git uses by default with `git sparse-checkout init --cone`:
- Patterns are simpler: `/`, `*/`, `<dir>/`, `<file>`.
- The `core.sparseCheckoutCone` config key signals cone mode to tools.
- Implementation should translate cone patterns to fnmatch equivalents before using the existing matching infrastructure (see Phase 2).

### Index read/write persistence

Critical correctness requirements:
1. SKIP_WORKTREE must survive index round-trips (write then re-read). The existing code at `index.c:2577-2591` (read) and :2953-2977 (write) already handles this for extended flags. Verify with tests.
2. If the index is v2 and SKIP_WORKTREE is set, it must be upgraded to v3 before writing. The `is_index_extended()` function (:2840) and write logic handle this automatically — if any entry has extended flags, the written index will be v3.
3. The `GIT_INDEX_ENTRY_EXTENDED` flag in `flags` must be set whenever `flags_extended` is non-zero (see :2847-2851).

---

## 7. Test Plan

All tests go under `tests/libgit2/`. A new directory `tests/libgit2/sparsecheckout/` should be created. Tests use the clar test framework (`deps/clar/`) and follow the conventions established by existing test files (e.g., `tests/libgit2/index/version.c`).

### Test file: `tests/libgit2/sparsecheckout/init.c`

| Test | Description |
|---|---|
| `init__enables_sparse_checkout_config` | Verify `core.sparseCheckout` is set to true after init. |
| `init__writes_sparse_checkout_file` | Verify `.git/info/sparse-checkout` exists and contains expected patterns. |
| `init__cone_mode_sets_cone_config` | With cone mode, verify `core.sparseCheckoutCone` is set. |
| `init__bare_repo_fails` | Calling init on a bare repo returns `GIT_EBAREREPO`. |
| `init__disabled_clears_config_and_file` | Disabling sparse checkout removes config keys and the file. |

### Test file: `tests/libgit2/sparsecheckout/update.c`

| Test | Description |
|---|---|
| `update__sets_skip_worktree_on_excluded` | After update, excluded index entries have SKIP_WORKTREE set. |
| `update__clears_skip_worktree_on_included` | Included entries do NOT have SKIP_WORKTREE. |
| `update__index_version_upgraded_to_v3` | If index was v2, it is upgraded to v3 when extended flags are needed. |
| `update__skip_worktree_persists_across_rw` | Write index, re-read, verify SKIP_WORKTREE is preserved. |
| `update__force_removes_excluded_files` | With force=true, excluded files in workdir are removed. |
| `update__safe_aborts_on_dirty_excluded` | With force=false and dirty excluded file, update fails gracefully. |
| `update__materializes_missing_included` | Included files missing from workdir are created from index. |

### Test file: `tests/libgit2/sparsecheckout/patterns.c`

| Test | Description |
|---|---|
| `patterns__wildcard_matching` | Patterns with wildcards (`src/*`) match correctly. |
| `patterns__negation_patterns` | Negation patterns (`!src/test`) work in non-cone mode. |
| `patterns__cone_dir_pattern` | Cone pattern `foo/` includes `foo/` and all descendants. |
| `patterns__cone_root_pattern` | Cone pattern `/` matches root-level files only. |
| `patterns__path_included_api` | The `git_sparsecheckout_path_included()` function returns correct results. |

### Test file: `tests/libgit2/sparsecheckout/diff_status.c`

| Test | Description |
|---|---|
| `diff__skip_worktree_shows_unmodified` | Diff between index and workdir shows SKIP_WORKTREE entries as UNMODIFIED. |
| `status__excluded_modified_not_dirty` | Modified excluded files do not appear dirty in status output. |
| `status__included_changes_visible` | Changes to included files are visible in status. |

### Test fixtures

Create test fixture repositories under `tests/resources/`:
- `sparse_checkout_repo` — a repo with known file structure for testing pattern matching.
- `sparse_checkout_cone_repo` — same but pre-configured for cone mode testing.

### Running tests

Tests are automatically discovered by the clar framework via `file(GLOB_RECURSE SRC_TEST ${TEST_PATH}/*/*.c ...)` in `tests/libgit2/CMakeLists.txt:27`. New test files under `tests/libgit2/sparsecheckout/` will be picked up automatically. Run with:
```
ctest -R sparsecheckout
```

---

## 8. Summary of Files to Create or Modify

### New files

| File | Purpose |
|---|---|
| `include/git2/sparse-checkout.h` | Public API header |
| `src/libgit2/sparse_checkout.h` | Internal declarations |
| `src/libgit2/sparse_checkout.c` | Implementation |
| `tests/libgit2/sparsecheckout/init.c` | Init tests |
| `tests/libgit2/sparsecheckout/update.c` | Update tests |
| `tests/libgit2/sparsecheckout/patterns.c` | Pattern matching tests |
| `tests/libgit2/sparsecheckout/diff_status.c` | Diff/status integration tests |

### Modified files

| File | Change |
|---|---|
| `src/libgit2/repository.h:41-59` | Add `GIT_CONFIGMAP_SPARSE_CHECKOUT`, `GIT_CONFIGMAP_SPARSE_CHECKOUT_CONE` to enum |
| `src/libgit2/config_cache.c:73-89` | Add configmap entries for sparse checkout keys |
| `src/libgit2/CMakeLists.txt` | Add `sparse_checkout.c` to build |
| `include/git2/sparse-checkout.h` | (new) Public header — add to include directory listing if needed |

### Files reviewed but not modified

| File | Reason |
|---|---|
| `src/libgit2/index.c` | Index read/write already handles SKIP_WORKTREE correctly; no changes needed. |
| `src/libgit2/diff_generate.c:849-850` | Already respects SKIP_WORKTREE for diffs. |
| `src/libgit2/checkout.c` | Reused as-is via public API calls; no internal modifications needed. |
| `src/libgit2/pathspec.c` | Existing pathspec matching is sufficient for non-cone mode patterns. |
