# ADR-269：仓库级门禁约定以入库 CLAUDE.md 为载体，不采用 git hooks

date: 2026-10-12
status: accepted

## Context

需要一条对「实现 run 的 worktree」与「人工交互直改会话」双方都生效的仓库级
门禁约定（win 交叉编译检查：触及 win-only 路径的改动提交前必过快档，实现 run
收工自证前必过 --full 档）。候选载体二选一：仓库根 CLAUDE.md（入库文件）或
pre-commit hook。仓库无 hooks 惯例（.git/hooks 仅 sample），hook 脚本不随仓库
分发；且实现 run 在独立 worktree 中工作，装在主仓库的 hook 对 worktree 不生效。

## Decision

仓库级约定/门禁要同时约束实现 run（worktree 内工作）与交互直改会话时，载体
必须是入库文件（仓库根 CLAUDE.md），不采用 git hooks：hook 不入库、对 worktree
不生效，永远无法完整到达实现 run；CLAUDE.md 随检出入库，实现 run 与交互会话
都会读到。

## Consequences

- 约定的强制力是提示词级而非机制级：依赖 agent 遵守 CLAUDE.md 约定，没有
  hook 的机械拦截；约定文本须写明失败阻断语义并附敞口面盘点命令，便于执行。
- 后续同类仓库级门禁/约定 SPEC 沿用同一载体选型；需要机械强制的检查走
  脚本加车道挂点（如收工自证前置），不走 hooks。
- CLAUDE.md 成为入库的活文档，须随敞口面变化维护（附盘点命令降低漂移成本）。
