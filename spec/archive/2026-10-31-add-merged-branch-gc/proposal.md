## Why

fenix 框架每轮实现/验证都以时间戳后缀创建新分支（`fenix/<spec>-<ts>`、`fenix/verify-<spec>-<ts>`，
见 `core/worktree_manager/lifecycle.py` 的 collision 规避设计），但全链路没有任何分支回收机制：
worktree 目录有 `cleanup_stale_worktrees` 清理，分支 ref 则永久累积。截至 2026-10-27 主仓库已积累
**2157 条** `fenix/*` 分支（其中 2041 条已完全并入 main），`git branch` 输出与分支甄别成本持续膨胀。

分支不删是设计使然：merge-back 销毁序列在保留场景刻意跳过 branch -D（`legacy_registry.py`
「分支承载首轮已提交成果」），该保守口径针对合并时刻，但没有任何后续环节兜底回收，导致只增不减。

本次人工清理已验证收敛口径可行：2041 条 `--merged` 分支批量删除零风险（`git branch -d` 拒绝
未合并分支，race 下最多漏删不会误删）；未合并的 116 条中仅 3 条活跃 spec 分支 + 1 条近期实质
未落地内容需要保留。

## What Changes

在 worktree 陈旧清扫（`stale_sweep`）中新增**已合并分支 GC** 环节，随清扫回收满足全部安全条件的
`fenix/*` 分支（既有清扫由 daemon 启动路径触发、无周期调度——GC 随每次 daemon 启动执行一轮，
收敛性依赖重启节奏，见 design 决策 1）：

1. **GC 判定（四条件同时满足才删）**：
   - 分支名命中实现/验证分支前缀家族（复用 `worktree.implement_branch_prefix` 配置，默认 `fenix/`）；
   - 分支已完全并入 main（`git branch --merged` 口径，只允许 `-d` 语义删除）；
   - 分支 tip 提交时间早于宽限期（默认 7 天）——保留 deliverables 读侧 D1 兜底
     （`git show <branch>:tasks.md`）在合并后流程中的读取窗口；
   - 分支未被任何 worktree checkout，且所属 spec 在 STATE.md 中非活跃状态
     （保护口径 = `stale_sweep._branch_protected_by_state` 在飞引用保护 ∪ STATE.md 显式活跃
     状态集判定——前者未覆盖 reviewing 等活跃状态，由后者补齐，见 design 决策 2/5）。
2. **删除动作只用 `git branch -d`**（绝不 `-D`）：未合并分支天然免疫，扫描与删除之间的竞态
   最坏结果是漏删，不可能丢失内容；已合并分支的提交仍从 main 可达，删除后可随时按 sha 重建。
3. **不引入备份 ref 机制**：`-d` 口径下零内容损失，备份只会把 ref 膨胀问题换名字重演。
4. **可观测性**：每轮 GC 记录删除清单与数量（logging 口径），GC 关闭或零删除时静默。
5. **配置项 + Dashboard 界面**（配置键与 UI 能力同步的既有约定）：
   - `worktree.branch_gc.enabled`（默认 true）
   - `worktree.branch_gc.retention_days`（默认 7）
6. **未合并分支不进自动 GC**：补丁等价检测（git cherry）慢且语义微妙，v1 不做；未合并分支
   数量仅进日志计数，留人工甄别。

## Capabilities

### New Capabilities
- `merged-branch-gc`: 已合并 fenix 分支的定期回收——四安全条件判定、`-d` 语义删除、
  宽限期与开关配置、GC 运行日志。

### Modified Capabilities

## Impact

- `core/worktree_manager/stale_sweep.py`：新增分支 GC 环节（worktree 清扫后追加，复用既有
  锁与扫描节奏、`_branch_protected_by_state` 状态保护）。
- `core/config.py` + `.fenix/config.template.yaml`：`worktree.branch_gc.*` 两个键的解析、
  校验与模板注释。
- `core/dashboard/static/src/pages/settings/`：设置页新增分支 GC 面板（开关 + 宽限期输入），
  参照既有 Panel 组件形态。
- `tests/`：GC 判定四条件（含边界：宽限期内 / 未合并 / worktree 占用 / 活跃 spec / GC 关闭）
  与删除语义（-d 拒绝未合并）的测试。
- 风险面：deliverables D1 读侧兜底在宽限期内不受影响；GC 只在 main 可达内容上动作，
  不触及 merge-back / preserve / salvage 任何写路径。
