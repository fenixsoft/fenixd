# 修复批失败自愈

<!-- knowledge: capability=code-fix-batch-selfheal rev=3
     sources=spec/archive/2026-09-28-add-code-fix-batch-failure-selfheal,spec/archive/2026-10-06-evo-code-fix-api-timeout-salvage,spec/archive/2026-10-30-evo-add-codefix-anomaly-redispatch-budget -->

自动修复车道批次失败的自愈语义：失败批现场即弃与锁即释、批收尾三态与链自驱动、两层跳过与失败档案重试预算，使单批失败零人工、不堵塞车道。

## 规则

### 失败批现场即弃与锁释放
- 凡已建树（`worktree_manager.create` 成功）的批失败路径，收尾前 MUST 清理 worktree（`_safe_cleanup`），不得保留现场等待人工；唯一例外是 API 超时签名的失败——命中签名且工作区脏时改走现场抢救路径（salvage 提交 + legacy 保全 + 同链下一批接续，见 [code-fix 批 API 超时现场抢救](code-fix-api-timeout-salvage.md)），其余失败路径仍现场即弃。其中「两次回归均失败」与「合回冲突」两条路径 MUST 在 cleanup 前把 `branch` 与 `tip_sha`（分支末梢提交 SHA）写入失败档案记录。
- `branch`/`tip_sha` 留作 git reflog 追溯线索，不承担恢复职责；已过回归的修复提交随 worktree 清理丢弃，由下轮重试重新生成（API 超时失败批的 WIP 除外——经抢救提交落批分支，被同链下一批接续）。
- 失败批收尾后 `code-review-fix:code-fix` 进程内 spec 锁即释放，后续批次的 `create()` 不会因该锁被拒。

### 批收尾三态与链自驱动
- 批收尾返回三态：`success`（批成功合回并核销）/ `consumed`（该批条目已全部离开可选池）/ `halt`（环境性失败）。批 worker 对 `success` 与 `consumed` 均 MUST 自驱动再投递推进下一批；仅 `halt` 终止链——条目保持 `open`，回落下一轮 full scan 兜底，进度 `phase=failed`。
- `consumed` 路径映射：批成功（success，条目核销）；两次回归均失败与合回冲突（条目入失败档案）；agent run 失败、回归重试 run 失败、零有效修复拒合回（条目入 `chain_skipped`）。
- `halt` 路径：`worktree_create_failed`、`worktree_manager_missing`、批 worker 异常——重选同批无意义，保持既有 full scan 兜底语义。
- consumed 失败收尾写进度 `phase=fixing`、`current=「第 N 批失败已跳过（原因）— 继续后续批次」`，不得复用链终止语义的终态收尾（`_finish("failed")` 语义是链终止，仅 halt 路径使用）。
- 收敛性：每个 consumed 失败批的条目都严格移出可选池（失败档案 ∪ `chain_skipped`），可选池严格单调缩小，链在可选池为空时正常收尾，不发生无限空转或递归。

### 两层跳过与重试预算
- 跳过分两层：**链内跳过**——进度快照 `chain_skipped` 字段（条目 id 列表）承载瞬态失败（agent run 层面），只跳过本链，不写永久档案、不烧跨轮重试预算；**失败档案**——`fix-failed.json` 承载确定性失败（整批两轮回归失败 / 合回冲突），带跨链重试预算。
- `select_batch` 的排除口径 = 失败档案条目并集 ∪ `chain_skipped`（经可选 `exclude_ids` 参数传入，缺省 `None` 保持向后兼容）。
- 新链启动（进度快照无 live 链、`activation_id` 更替）时：`chain_skipped` 重置为空（写侧 MUST 显式传空覆盖），并调用释放原语自动释放档案中 `fail_count` 未达生效预算（按记录回归终局形态分档，见「失败档案记录与预算用尽」）的记录——条目回到可选池实现下轮自动重试，等效人工释放但零人工；预算内条目 MUST NOT 要求人工解除。

### 失败档案记录与预算用尽
- 失败档案记录含 `fail_count`（缺省 1）、`reason`、`branch`、`tip_sha`、`failed_at`，以及回归终局形态 `reg_form`（`anomaly` | `mapped`）与 `reg_detail`（anomaly_streak、mapped_rounds、重试收敛事实）；同条目集（item_id 集合相同）再次失败复用既有记录并 `fail_count` 递增、刷新其余字段，不追加重复记录，`reg_form` 与重派计数以最近一次失败为准（最近失败为真实失败面即回到 mapped 预算，为异常形态即按 anomaly 预算继续）。
- `reg_form` 判定：`anomaly` = 回归 `parse_error`（junit 产物缺失/不可解析）或回归 `failed` 但失败明细为空（零失败面）；`mapped` = 回归 fail_items 非空（有真实失败面）。无 `reg_form` 键的历史失败记录按 `mapped` 处理，不因缺键报错。
- 失败批自动重派预算按 `reg_form` 分档：`anomaly` 预算为 1（模块常量 `ANOMALY_FAIL_RETRY_MAX`），`mapped` 保持 3（模块常量 `FAIL_RETRY_MAX`）；anomaly 预算耗尽即走既有触顶「登记待人工排查 + 跳过条目」路径。全部 `fail_count` 预算比较点——触顶入档判定（anomaly 达 1 即须触发登记待人工，否则记录悬为「保留但永不重派」）、新链释放判定、条目预检/可选池过滤、延迟批收敛判定、达上限自动核销类消费侧——一律取分档生效预算，单点沿用统一上限会出现悬挂态或分档被旁路；todo 登记与触顶告警文案中的轮数按生效预算动态呈现。
- `fail_count` 递增至生效预算的那次入档：发一条 warning 级点名录告警（列明条目集与历次原因），并在 `.fenix/todo.md` 追加待人工清理项（指引按 `branch`/`tip_sha` 追溯，不引用已清理的 worktree 路径）；该记录此后不再被新链释放、不再触发新告警。
- anomaly 形态触发预算降档或停派时，经既有回归失败告警通道 `write_regression_failed_alert` 发一次告警（登记 branch、`reg_form` 与被跳过条目），不新增告警类型；一次性以失败档案记录上的告警标记判重（置位后同一失败记录生命周期内不再发），与现场即弃收口的常规失败告警并存。
- 「选批为空」（`open` 条目全被排除）是链的正常收敛出口，MUST NOT 误报为故障；文案按排除来源区分——`chain_skipped` 与预算内档案表述为「已跳过，下轮自动重试」，仅达上限档案保留人工指引。
- 两个预算常量均为模块常量而非配置键，无 Dashboard 配置义务；告警在链启动释放动作中零产生（纯日志）。

## 溯源

- 2026-09-28 2026-09-28-add-code-fix-batch-failure-selfheal（spec/archive/2026-09-28-add-code-fix-batch-failure-selfheal） — 新建本页：失败批现场即弃与锁释放、批收尾三态与链自驱动条件、链内跳过集生命周期、失败档案 fail_count 重试预算与达上限一次性告警。
- 2026-10-06 2026-10-06-evo-code-fix-api-timeout-salvage（spec/archive/2026-10-06-evo-code-fix-api-timeout-salvage） — 修改本页：现场即弃规则收窄 API 超时签名例外（命中即走 salvage 保全与同链下一批接续，不再立即物理清理），其余失败路径行为不变。
- 2026-10-30 evo-add-codefix-anomaly-redispatch-budget（spec/archive/2026-10-30-evo-add-codefix-anomaly-redispatch-budget） — 修改本页：失败档案记录新增回归终局形态 `reg_form`/`reg_detail`（旧记录缺键按 mapped），失败批自动重派预算按形态分档（anomaly 1 / mapped 3）并同步作用于全部预算比较点，复燃合档以最近失败形态为准，anomaly 降档/停派经回归失败告警通道发一次性告警（记录上告警标记判重）。
