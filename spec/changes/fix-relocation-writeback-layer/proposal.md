# 交付物声明修正：写回层与读取基准对齐

## Why

dispute judge 裁决 `typo`（声明路径笔误）后，机械修正**只写主树** `spec/changes/<spec>/tasks.md`
并提交到主树，而守卫/裁决的**声明读取**优先序是 `worktree > 分支 > 主树`
（`declaration-relocation-protocol` 的分层解析契约）。

事故实证（add-code-review-auto-fix，2026-09-21）：该 SPEC 的进度卡片声明路径笔误
（`pages/settings/…` 应为 `pages/projects/…`）。judge 判 `typo` 并「修正声明段」，
但修正落在主树；实现 worktree 与分支里那份声明**仍是旧路径**，且**分支提交已携带**该
旧路径。于是此后每轮实现完成的收工守卫都按分支版本解析 → 又读到旧路径 → 判缺件 →
打回重派 → 实现方无任何信息可改（文件确实在真实路径）→ 原地打转，叠加 daemon 重启续做，
累计 31 小时 / $44.98 仍在 `implementing`。

根因是**「修正写入层」与「守卫读取层」不一致**：同一份声明的写口径（主树）与读口径
（分支/worktree 优先）错层，修正永远读不回来。本变更把两者对齐，并补上「修正后校验
读取路径一致」的熔断与跨轮脱困路径。

## What Changes

- **修正写回层对齐**：judge 的 `typo` / `reference` 修正，其改写目标与提交根 MUST 取
  **生效声明命中层**——worktree 命中写 worktree（分支提交）、主树命中写主树（此时守卫
  读取基准即主树，同源）、`source == "branch"`（无落盘位置）不可就地写入；与守卫读取
  基准同源；MUST NOT 在守卫读分支时改主树并假装「修正已生效」。
- **分支为唯一命中层时不产生「读不回来」的修正**：`source == "branch"`（worktree 已
  清理、声明只存在于分支对象库）时，修正 MUST 交由实现方在分支上续做（走既有缺件打回
  / relocate 凭据通道），该条裁决落 dispute 审计流（供跨轮核销），MUST NOT 把修正写进
  主树而让守卫继续按分支顺序读回旧路径。
- **修正后复检熔断**：机械修正后 MUST 以**守卫读取基准**复检该路径（旧路径不再作为
  生效声明硬校验项）；读回仍是旧路径 → 记入 error 明细，MUST NOT 静默销账。
- **跨轮脱困（残留核销）**：读取到的缺件若在 dispute 审计流已存在该路径的 typo /
  重定位凭据，则**以凭据核销为收敛动作**（旧路径不再要求存在），MUST NOT 仅因
  「本轮无新凭据」无限重派。
- 新增迁移期复发熔断：`typo` 修正后同路径连续 N 轮复发（读取基准未对齐）→ blocked
  待人工（上限后不再烧预算）。计数 MUST 用独立持久字段——现有 `_retry_count` 在恢复
  续做/阻塞复位时被清零，事故态 31 小时在飞期间该值恒为 `0`，既有封顶形同不存在。
- **解冻续做锚点耐久（同族静默降级根除）**：`unfreeze_spec` 当前仅当**外部显式传入**
  `project_root` + `worktree_manager` 时才走保留分支续做解析（`_frozen_hold` 分支），
  未传则**静默**丢弃 branch 锚点、走「新轮次派发清除旧锚点」→ 从 main 新建分支重做。
  实测：worktree 已清理只剩下分支时，经**裸** `unfreeze_spec` 解冻，6 个提交 / 48 勾选
  的保留分支不再被 `find_branches_by_spec` 枚举（`_frozen_hold` 已清），实现成果被弃、
  预算被重复消耗。本变更 MUST 消除该静默面：解冻时未显式传上下文 MUST 自解析项目根再
  尝试续做判定，且「丢弃保留分支」MUST 显式告警而非静默（与写回层错层同族——都是
  「降级路径无人可见」）。

## Capabilities

### New Capabilities

- `relocation-writeback-layer`: 声明修正的「写回层」契约——修正写入位置 MUST 与守卫
  读取基准同源（生效声明所在工作树）；修正后复检读取一致性；跨轮残留凭据核销。

### Modified Capabilities

- `declaration-relocation-protocol`: 机械执行的改写目标由「生效声明所在位置（`spec_dir`
  `or` 主树回退）」收紧为「生效声明**命中层**」（worktree → 该 worktree；main → 主树，
  同源，可写），并补「`source == "branch"`（无落盘位置）时改走凭据/打回、不写主树」。
- `deliverable-declaration-resolution`: 补「写回层对齐」要求——解析入口返回的
  `spec_dir` 用于**写入**时，MUST 与实际生效（读取命中）的那一层同源；`source ==
  "branch"`（`spec_dir` 为 `None`）时 MUST NOT 回落主树目录作为写入落点（main 命中层
  可就地写入，不得禁止）。
- `implementer-deliverable-gate`: 缺件判定补「凭据核销」收敛路径——缺件路径若已有
  typo / 重定位凭据在册，则视为可收敛（核销），与既有 `removed` 收缩防护豁免同源。
- `freeze-stop-inflight-agents`: 「解冻后在保留分支自动续做」补锚点耐久——保留判定
  MUST NOT 以「调用方是否显式传上下文」为前置条件；未显式传时自解析项目根后仍须尝试
  续做，worktree 已清理只剩分支时经命名空间枚举记录续做分支，杜绝静默丢弃保留分支。

## Impact

- **代码**：`core/pm_engine/dispatch/adjudication.py`（judge typo/reference 执行、
  `_preclassify_missing` / `_preclassify_orphan` 写入点与复检熔断）、
  `core/deliverables.py`（写回层解析辅助 / 凭据查询含替代路径）、
  `core/pm_engine/verification/branch_guard.py`（缺件凭据核销）、
  `core/pm_engine/engine.py`（`_git_commit` 支持提交根）、
  `core/state_machine.py`（`unfreeze_spec` 续做锚点耐久）、
  `tests/test_relocation_writeback_layer.py`（新增回归）。
- **行为**：judge 裁决后的声明修正不再在「守卫读取层为分支」时写主树；写入落点与守卫
  读取基准同源（worktree / main 命中层可就地写，branch 命中层走打回+凭据）。解冻续做
  不再因未显式传上下文而静默丢弃保留分支。
- **风险**：改动触及裁决流水线——须 fail-safe（不可写入命中层时不得误改主树、不得静默
  放行），并有回归测试覆盖「有 worktree / 主树命中就地写 / 分支命中不写主树 / 复检
  不一致 / 凭据残留 / worktree 写入冲突降级」六态；另须清点 `tasks.md` 声明段**全部**
  写入点（含 `_preclassify_missing` / `_preclassify_orphan` / 晋升软化），并核对既有
  「主树就地软化 + 立即提交」断言（2026-09-15 merge-back 死锁修复）不回归。
- **数据**：`.fenix/dispute_audits.jsonl`（凭据查询，运行时文件，`reference`）。
