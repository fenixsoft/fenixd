<!-- 知识重建 2026-10-01：原文件为 untracked 产物，随 09-30 夜间工作区清理事故丢失；依 adr/index.md 摘要与归档 2026-09-30-evo-fix-worktree-name-collision-retry design.md 重建。 -->

status: accepted
日期: 2026-09-30

# ADR-203：worktree 分支名末段恒为纯数字时间戳命名契约

## Context

worktree 分支名（`fenix/{spec}-{timestamp}` 等）的末段被 queries 层多处（`_spec_from_branch`、`_spec_from_worktree_name`、`find_branches_by_spec` 等）以 `rsplit("-", 1)` + `isdigit` 解析回 spec 名。2026-09-30 出现同名分支创建冲突（现有 5 组撞名均为 planner 先到），需要在「唯一名」与「解析契约」之间裁决命名规则。

## Decision

- 分支名末段恒为纯数字时间戳，命名公式禁掺非数字后缀——`rsplit("-") + isdigit` 解析契约是跨层依赖，任何为唯一化而附加的字母/uuid 尾巴都会破坏全链 spec 归属解析。
- 同名冲突以**单调递增换名**解决：撞名时 `timestamp = max(now, old + 1)`，branch 与 wt_path 同步重建后重试（总计至多 3 次 add -b：首跑 + 至多 2 次换名）；不用 uuid 唯一化、不做同名分支复用。
- 换名重试全程持有 create 锁，锁语义对调用方透明；非 "already exists" 的失败不重试，直接走既有放弃路径。
- 换名重试落 WARNING 留痕（含 spec、新旧分支名、尝试序号）；verifier 车道（verify- 前缀）同样受益。

## Consequences

- 新后缀严格大于旧值（max 保证单调），与既有「新纪元后缀成功」形态一致。
- 撞名胜者不定（先到先得），换名重试对任一方后到都生效，不依赖到达顺序。
- queries 层解析契约零改动；runner 的 sleep 重试兜底保留为最后防线。
