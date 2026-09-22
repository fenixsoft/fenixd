## Why

自动修复代码问题车道（`admin.code_review_fix`）定位是深夜无人值守的自动维护车道，但批次失败后的处置全部依赖人工：①「两次回归均失败」与「合回冲突」两条路径按「保留 worktree 待人工提取」设计，**从不释放进程内 spec 锁**，而 `worktree_manager.create()` 的锁检查是裸内存判断、`refresh_locks()` 只在 daemon 启动时执行一次——批次失败即车道锁死至 daemon 重启（2026-09-22 第 3 批合回冲突事故实证：16:44 与 16:57 两次派发均 14ms 内被「Worktree already active」拒绝）；②失败条目进入 `fix-failed.json` 后被 `select_batch` 永久跳过，唯一出口是人工调用 `release_failed_batch`；③批失败即 `_finish("failed")` 终止链，剩余整队 open 条目当夜停摆。用户已明确：该车道不能依赖人工裁决，单个批次失败不得堵塞整个车道，需要在机制上自愈。

## What Changes

- **失败批现场即弃（解锁关键）**：「两次回归均失败」与「合回冲突」两条路径不再保留 worktree——记录 `branch`/`tip_sha` 入失败档案后 `_safe_cleanup`（清理 worktree 并释放 `code-review-fix:code-fix` 进程内锁），车道不再因待人工而锁死。
- **批收尾三态化**：`_run_batch_inner` 返回值从 bool 改为 `success` / `consumed` / `halt` 三态；凡 `consumed`（该批条目已离开可选池：批成功、两次回归失败、合回冲突、agent run 失败、重试 run 失败、零有效修复拒合回）都照常自驱动 `_resubmit()` 推进下一批；`worktree_create_failed`、`worktree_manager_missing`、批 worker 异常等环境性失败保持 `halt`（终止链，条目保持 open 待下轮 full scan）。收敛性：每个 consumed 失败批的条目都严格移出可选池，循环必然终止。
- **两层跳过 + 重试预算（去人工化核心）**：
  - **链内跳过** `chain_skipped`（进度快照新字段）：agent run 失败等**瞬态**失败条目只跳过本链（不进永久档案、不烧重试预算），下次链激活自动重试；新链启动时重置。
  - **永久档案重试预算**：`fix-failed.json` 记录新增 `fail_count`/`reason`/`branch`/`tip_sha`/`failed_at` 字段，同条目集再次失败 `fail_count` 递增；新链启动时自动释放 `fail_count < 3` 的记录（=下轮重试，无需人工 release）；`fail_count` 达上限（常量 `FAIL_RETRY_MAX = 3`，不新增配置键）那一刻发一条 warning 告警，此后不再重试。
- **可见性去人工化**：批失败进度文案改为「第 N 批失败已跳过（原因）— 继续后续批次」；回归失败告警措辞从「待人工处置」改为「已跳过，下轮自动重试」，保留 warning 级可见性。
- **存量语义改写**：`regression_failed_twice` 路径「保留 worktree（MUST NOT cleanup）」的既有断言与注释按新语义改写（现场即弃 + 档案留痕）。

## Capabilities

### New Capabilities

- `code-fix-batch-selfheal`: 自动修复车道的批次失败自愈语义——失败批现场即弃与锁释放、批收尾三态（success/consumed/halt）与链自驱动条件、链内跳过集（chain_skipped）与新链重置、失败档案 fail_count 重试预算（新链自动释放 <3、达上限永久跳过并一次性告警）、select_batch 双重排除口径。

### Modified Capabilities

- `code-fix-lane`：批失败处置分支语义整体改写（MODIFIED delta 见本变更
  `specs/code-fix-lane/spec.md`）——既有 requirement 中「失败保留批 MUST NOT 调
  cleanup」「丢弃时 MUST 保留失败 worktree（不自动删除）」「人工处理前 MUST NOT
  重复派发同一批」「丢弃时 MUST 在 todo.md 追加待人工清理项」被本能力取代（现场
  即弃 + 预算内自动重试）；「零有效修复拒合回」的收尾从链终止（`phase=failed`）
  改为链内跳过（`chain_skipped`，零产物批按 halt 终止链会使最早队列头永久堵塞
  车道，违背本 SPEC 目标）。成功路径、进度链身份（D8）、手动授权链
  （manual_authorized）、回归锁根等 requirement 不变。

<!-- code-fix-progress：进度快照字段为「至少含」口径（add-code-review-auto-fix
     code-fix-progress L8），新增 chain_skipped 属增量，无需 delta；与在飞变更
     add-code-fix-item-level-progress 新增的批上下文字段同属 FIX_PROGRESS_DEFAULT
     增量键，合并实现时取键集并集。 -->

## Impact

- `core/code_fix.py`：`_run_batch`/`_run_batch_inner`/`_run_batch_created` 返回三态；两条保留路径改 cleanup + 档案留痕；`record_failed_batch` 增量记录 fail_count；新增 `release_retryable_failed_batches`；`select_batch` 排除口径加 `chain_skipped`；`FIX_PROGRESS_DEFAULT` 增 `chain_skipped` 字段；新链启动处重置 chain_skipped 并释放可重试档案。
- `tests/test_code_fix.py`：新增三态收尾、锁释放、重试预算、告警一次性、chain_skipped 生命周期等用例；改写「保留 worktree MUST NOT cleanup」存量断言。
- 不新增配置键（`FAIL_RETRY_MAX` 为模块常量），无 Dashboard 配置 UI 义务；进度/告警复用既有展示通道。
- 生效条件：实现合回后 daemon 重启加载新代码（重启时机由运维侧在批间静默窗口执行，不属于本 SPEC 交付物）。
