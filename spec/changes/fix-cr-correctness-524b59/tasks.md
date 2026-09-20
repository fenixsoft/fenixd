# Tasks: fix-cr-correctness-524b59

## Deliverables

```yaml
- path: bin/fixture_scheduling_showcase.py
  kind: modify
```

## 1. 修复审查问题

- [ ] 1.1 `_git` never inspects `returncode`, and  — bin/fixture_scheduling_showcase.py:91

  **问题描述**：

  `_git` never inspects `returncode`, and `_commit_baseline` discards both `_git` results. If `git init`/`add`/`commit` fails (git missing, no identity usable, pre-existing broken index), `reset_fixture` still prints `fixture created (fresh baseline commit)` and returns 0, so the prepare step reports success while the fixture has no HEAD — a later daemon `worktree add` will then fail inside the scenarios, producing another confusing env failure. Check the return codes and surface a FAIL (or at least a clear WARN) instead of unconditionally claiming success.

  **证据**：

  bin/fixture_scheduling_showcase.py:91（ocr scan）

