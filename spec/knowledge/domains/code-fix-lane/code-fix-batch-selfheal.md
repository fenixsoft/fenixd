# 修复批失败自愈

<!-- knowledge: capability=code-fix-batch-selfheal rev=5
     sources=spec/archive/2026-09-28-add-code-fix-batch-failure-selfheal,spec/archive/2026-10-06-evo-code-fix-api-timeout-salvage,spec/archive/2026-10-30-evo-add-codefix-anomaly-redispatch-budget,spec/archive/2026-10-30-evo-add-codefix-failure-registration-closeout,spec/archive/2026-10-30-evo-codefix-zero-face-regression-hardening -->

自动修复车道批次失败的自愈语义：失败批现场即弃与锁即释、批收尾三态与链自驱动、两层跳过与失败档案重试预算、达上限登记的闭环核销与人工解除留痕，使单批失败零人工、不堵塞车道。

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
- `reg_form` 判定：`anomaly` = 回归产不出可用失败用例明细的形态——`parse_error`（junit 产物缺失/不可解析）、`failed` 但失败明细为空（零失败面）、或 `timeout` 且失败明细映射不出任何用例（items 为空、`fallback_full=true`）；`mapped` = 回归 fail_items 非空（有真实失败面）。无 `reg_form` 键的历史失败记录按 `mapped` 处理，不因缺键报错。
- 失败批自动重派预算按 `reg_form` 分档：`anomaly` 预算为 1（模块常量 `ANOMALY_FAIL_RETRY_MAX`），`mapped` 保持 3（模块常量 `FAIL_RETRY_MAX`）；anomaly 预算耗尽即走既有触顶「登记待人工排查 + 跳过条目」路径。全部 `fail_count` 预算比较点——触顶入档判定（anomaly 达 1 即须触发登记待人工，否则记录悬为「保留但永不重派」）、新链释放判定、条目预检/可选池过滤、延迟批收敛判定、达上限自动核销类消费侧——一律取分档生效预算，单点沿用统一上限会出现悬挂态或分档被旁路；todo 登记与触顶告警文案中的轮数按生效预算动态呈现。
- `fail_count` 递增至生效预算的那次入档：发一条 warning 级点名录告警（列明条目集与历次原因），并在 `.fenix/todo.md` 追加待人工清理项（指引按 `branch`/`tip_sha` 追溯，不引用已清理的 worktree 路径）；该记录此后不再被新链释放、不再触发新告警。
- anomaly 形态触发预算降档或停派时，经既有回归失败告警通道 `write_regression_failed_alert` 发一次告警（登记 branch、`reg_form` 与被跳过条目），不新增告警类型；一次性以失败档案记录上的告警标记判重（置位后同一失败记录生命周期内不再发），与现场即弃收口的常规失败告警并存。
- 「选批为空」（`open` 条目全被排除）是链的正常收敛出口，MUST NOT 误报为故障；文案按排除来源区分——`chain_skipped` 与预算内档案表述为「已跳过，下轮自动重试」，仅达上限档案保留人工指引。
- 两个预算常量均为模块常量而非配置键，无 Dashboard 配置义务；告警在链启动释放动作中零产生（纯日志）。

### 登记闭环核销与人工解除留痕
- 达自动重试上限的失败批登记具备生命周期终点：周期对账发现某失败记录的被跳过条目已全部终态（`resolved`/`ignored`）时自动核销——记录写入 `consumed_at` 与终态分布注记，不再提示人工排查；对应 `code_fix_retry_budget_exhausted` 告警经 `AdminStore.mark_signal_handled` 收口，`action_taken` 附「N resolved / M ignored」终态分布。
- 核销判定以台账逐 id 对账为准（登记条目全部终态即核销），挂钩两处——批收尾/合回核销点后即时检查、新链启动簿记块周期兜底；对账时台账读取失败按空集 fail-open 跳过本轮核销，不阻断批收尾/链启动主流程。
- 被跳过条目仅部分终态时只更新记录的 `open_remaining`，不收口告警、不标记核销；重复核销幂等——不重复写注记、不重复收口告警、不报错。
- 记录的核销字段（`consumed_at`/`consumed_note`/`open_remaining`）为只增记账字段，缺键视为未核销（存量记录无需迁移）；核销写 `fix-failed.json` 沿用该文件既有 flock 惯例（锁内不重入，告警与 todo 写走异锁通道、保持锁外）。
- 告警收口按记录内条目集匹配未 handled 告警：告警记录无结构化 item_ids/branch/tip_sha 字段（仅 evidence 文本含 `item_ids=…` 逗号清单），经 `AdminStore.unhandled()` 过滤 signal_type 后按 evidence 内 `item_ids=<清单>` 精确子串匹配；已 handled 的告警不再改动。
- `release_failed_batch` 人工解除跳过必须留痕：无论经 daemon 内路径还是带外脚本（todo 登记正文将带外 `python3 -c` 直调列为官方解除指引），内部无条件追加一行结构化留痕到 `.fenix/code-review/fix-failed-release.jsonl`（释放时刻、释放记录数与 item_ids 摘要），不经 daemon logger 亦可追溯；调用方传入 logger 时另写一行 daemon 日志。留痕写入失败（OSError）不阻断解除本身。
- todo.md 登记的消费侧为重写式：核销时持 `.todo.md.lock` 将登记块重写为单行「已于某时刻被后续批消化（终态分布）」或整块移除（登记块已损毁成裸标题的残骸场景按标题行兜底移除），不依赖原位追加注记。登记块按块体「被跳过的条目集合」行的 item_ids 定位本记录对应块，只重写/移除该块；多个失败批的登记块可共存，MUST NOT 波及他批登记块。

## 溯源

- 2026-09-28 2026-09-28-add-code-fix-batch-failure-selfheal（spec/archive/2026-09-28-add-code-fix-batch-failure-selfheal） — 新建本页：失败批现场即弃与锁释放、批收尾三态与链自驱动条件、链内跳过集生命周期、失败档案 fail_count 重试预算与达上限一次性告警。
- 2026-10-06 2026-10-06-evo-code-fix-api-timeout-salvage（spec/archive/2026-10-06-evo-code-fix-api-timeout-salvage） — 修改本页：现场即弃规则收窄 API 超时签名例外（命中即走 salvage 保全与同链下一批接续，不再立即物理清理），其余失败路径行为不变。
- 2026-10-30 evo-add-codefix-anomaly-redispatch-budget（spec/archive/2026-10-30-evo-add-codefix-anomaly-redispatch-budget） — 修改本页：失败档案记录新增回归终局形态 `reg_form`/`reg_detail`（旧记录缺键按 mapped），失败批自动重派预算按形态分档（anomaly 1 / mapped 3）并同步作用于全部预算比较点，复燃合档以最近失败形态为准，anomaly 降档/停派经回归失败告警通道发一次性告警（记录上告警标记判重）。
- 2026-10-30 evo-add-codefix-failure-registration-closeout（spec/archive/2026-10-30-evo-add-codefix-failure-registration-closeout） — 修改本页：新增「登记闭环核销与人工解除留痕」规则——被跳过条目全部终态即自动核销并收口触顶告警、部分终态只同步 open_remaining、核销幂等、台账读取失败 fail-open；人工解除跳过无条件落结构化 jsonl 留痕（带外调用可追溯）；todo 登记消费侧改重写式核销或整块移除，废止一次性写入永不更新的旧形态。
- 2026-10-30 evo-codefix-zero-face-regression-hardening（spec/archive/2026-10-30-evo-codefix-zero-face-regression-hardening） — 修改本页：`reg_form` 的 anomaly 判据补入 timeout 且失败明细映射不出用例的零失败面形态（该形态自此自动套用 anomaly 预算 1 与一次性降档告警，重派侧规则不变）。
