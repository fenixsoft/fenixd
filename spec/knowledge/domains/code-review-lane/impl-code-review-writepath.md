# 实现车道验证进度写路径与目录授权

<!-- knowledge: capability=impl-code-review-writepath rev=2
     sources=spec/archive/2026-09-25-fix-impl-code-review-writepath,spec/archive/2026-09-26-add-impl-ocr-parallel-lane -->

实现车道对 `.fenix/verify-progress/` 的写路径纪律与 `--add-dir` 目录授权矩阵：写盘路径与门检/消费路径必须落在同一棵树，杜绝「写主树、查 worktree」的读写错层。

## 规则

- 验证进度目录的写路径一律是**当前工作目录（worktree）内的相对路径** `.fenix/verify-progress/...`，禁止用主树绝对路径写该目录下的文件。
- `agents/implementer.md` 与 `agents/fast-track.md` 的「工作目录（worktree 隔离，强制）」段把「验证进度目录」表述为**当前工作目录（worktree）内的** `.fenix/verify-progress/`，并显式提示「不是主树的同名目录」；不得出现未限定的「验证进度目录 `.fenix/verify-progress/`（框架已显式授权）」裸表述（裸表述会把「授权目录」误读为主树绝对路径落点）。
- `_run_claude` 向 agent 子进程注入 `--add-dir` 时只授予该车道真实需要的目录，按 `agent_type` 判定：
  - 没有主树 verify-progress 落点的车道（`implementer` / `repair` / `spec-review`）：不注入 `<project_root>/.fenix/verify-progress`，仍注入 `--add-dir <worktree>`；
  - 确有主树 verify-progress 落点的车道（`verifier` / `planner-plan` / `planner-judge` / `fast-track`）：保留注入该目录；
  - 未知/缺省 `agent_type`（maintenance / admin / dashboard 会话等）：保持既有注入（零行为变化兜底）。

## 溯源

- 2026-09-25 fix-impl-code-review-writepath — 新建写路径纪律：提示词与 agent 契约显式锚定 worktree 内相对路径、`--add-dir` 按车道精准授予（根治「报告被绝对路径写进主树、门在 worktree 恒判缺失」的写读错层）。
- 2026-09-26 add-impl-ocr-parallel-lane — 内联收尾审查段摘除，实现者不再落盘 `code-review.json`（报告改由框架侧 ocr 车道写入）；`--add-dir` 授权矩阵与契约消歧规则保留。
