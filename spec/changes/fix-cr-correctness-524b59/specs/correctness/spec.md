# Spec Delta: correctness

## ADDED Requirements

### Requirement: 修复选中的代码审查问题

系统 SHALL 修复以下 code-review 台账选中的问题：

#### `bin/fixture_scheduling_showcase.py:91` — `_git` never inspects `returncode`, and 

- 严重度：major

**问题描述**：

`_git` never inspects `returncode`, and `_commit_baseline` discards both `_git` results. If `git init`/`add`/`commit` fails (git missing, no identity usable, pre-existing broken index), `reset_fixture` still prints `fixture created (fresh baseline commit)` and returns 0, so the prepare step reports success while the fixture has no HEAD — a later daemon `worktree add` will then fail inside the scenarios, producing another confusing env failure. Check the return codes and surface a FAIL (or at least a clear WARN) instead of unconditionally claiming success.

**证据**：

bin/fixture_scheduling_showcase.py:91（ocr scan）

#### Scenario: 修复完成

- **WHEN** 修复提交
- **THEN** 对应问题不再出现在 code-review open 列表
