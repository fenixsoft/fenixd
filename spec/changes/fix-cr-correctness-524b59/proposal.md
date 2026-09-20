## Why

代码审查发现问题修复 SPEC（由 code-review 台账选中条目机械生成）。

## What Changes

- 修复以下审查发现（SPEC `fix-cr-correctness-524b59`）：

### [major] `_git` never inspects `returncode`, and 

- 类别：`correctness`
- 位置：`bin/fixture_scheduling_showcase.py:91`

**问题描述**：

`_git` never inspects `returncode`, and `_commit_baseline` discards both `_git` results. If `git init`/`add`/`commit` fails (git missing, no identity usable, pre-existing broken index), `reset_fixture` still prints `fixture created (fresh baseline commit)` and returns 0, so the prepare step reports success while the fixture has no HEAD — a later daemon `worktree add` will then fail inside the scenarios, producing another confusing env failure. Check the return codes and surface a FAIL (or at least a clear WARN) instead of unconditionally claiming success.

**证据**：

bin/fixture_scheduling_showcase.py:91（ocr scan）

## Capabilities

### New Capabilities

- 修复 code-review 台账中选中的代码质量问题。

## Impact

- 修改 `## Deliverables` 声明段所列文件。
