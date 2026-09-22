## Context

2026-09-22 code-fix 第 3 批合回冲突事故（merge_back_conflict）取证结论：

1. 「两次回归均失败」与「合回冲突」两条失败路径按「保留 worktree 待人工提取修复」设计，不调用 `_safe_cleanup` → `code-review-fix:code-fix` 进程内 spec 锁永不释放；`worktree_manager.create()` 的锁检查是裸内存判断（无进程/流/锁龄陈锁二次确认），`refresh_locks()` 仅 daemon 启动首扫调用（docstring 称「周期调用」但全库无调用点），`has_active_worktree` 的释放逻辑只被 STATE spec 派发路径调用（code-fix 非 STATE spec 轮不到）——三重叠加使待人工态**锁死车道至 daemon 重启**（事故中 16:44 与 16:57 两次派发均 14ms 内被「Worktree already active」拒绝，重启前无任何自愈路径）。
2. 失败条目进 `fix-failed.json` 后 `select_batch` 永久跳过，唯一出口 `release_failed_batch` 是人工函数。
3. `_run_batch` 仅 `ok=True` 才 `_resubmit()`；失败即终止链，剩余整队 open 条目当夜停摆。`_run_batch` 既有注释反对「失败即再投递」的理由是同步模式无限递归 / executor 模式无限空转——该理由只对「条目未离开可选池的失败」（如 worktree_create_failed 每轮复现同批）成立；凡条目已移出可选池的失败，重投递循环必然收敛。

产品定位约束（用户决策）：该车道是深夜无人值守自动维护车道，**不允许依赖人工裁决**，单批失败不得堵塞车道。

## Goals

- 批失败后车道零人工继续：现场即弃、锁即释、链自驱动推进下一批。
- 失败条目按轮自动重试，带预算上限；达上限后永久跳过并留一次性告警。
- 收敛性有保障：任何路径下不得引入无限空转/递归。

## Decisions

**D1 三态收尾替代 bool**：`_run_batch_inner`/`_run_batch_created` 返回 `"success" | "consumed" | "halt"`。`_run_batch` 对 `success`/`consumed` 执行 `_resubmit()`，仅 `halt` 终止。`consumed` 的判定标准是「该批条目已全部离开可选池」——五条路径映射：批成功（success，条目核销 resolved）、regression_failed_twice / merge_back_conflict（条目进失败档案）、agent_run_failed / regression_retry_run_failed（条目进 chain_skipped）。worktree_create_failed / worktree_manager_missing / 批 worker 异常为 halt（条目保持 open，重选同批无意义，保持既有「下轮 full scan 兜底」语义）。既有注释担心的无限空转对 consumed 不成立：可选池严格单调缩小。

**D2 现场即弃，档案留痕**：两条原保留路径在 cleanup 前记录 `branch`/`tip_sha`（`_worktree_head(wt)`）入失败档案。已过回归的修复提交随 worktree 清理丢弃，由下轮重试重新生成——对深夜自动车道，用一次重跑成本换取车道永不锁死。tip_sha 留作追溯线索（git reflog 可找回），不承担恢复职责。

**D3 两层跳过，预算分离**：
- `chain_skipped`（进度快照字段，list[item_id]）：瞬态失败（agent run 层面）只跳过本链，不写 `fix-failed.json`——网关抖动等瞬态错误不应烧跨轮重试预算。新链启动时随进度重置为空（`write_progress` 合并语义，新链路径 MUST 显式传 `chain_skipped=[]` 覆盖）。
- `fix-failed.json` 记录增 `fail_count`/`reason`/`branch`/`tip_sha`/`failed_at`：确定性失败（整批两轮回归失败/合回冲突）才入档。`record_failed_batch` 按 item_id 集合相等匹配既有记录：命中则 `fail_count += 1` 并刷新其余字段，未命中则新增（fail_count=1）。
- 新链启动（checkpoint 判定非同一链身份处）调用新增 `release_retryable_failed_batches(root)`：释放 `fail_count < FAIL_RETRY_MAX(3)` 的记录（等效现有人工 `release_failed_batch`），返回释放条目数供日志/进度文案。
- `FAIL_RETRY_MAX = 3` 为模块常量，**不新增配置键**（规避「新增配置必须带 Dashboard UI」义务；预算语义无需按项目调节）。

**D4 告警一次性（达上限瞬间）**：`fail_count` 递增至 `FAIL_RETRY_MAX` 的那次 `record_failed_batch` 内发一条 warning 告警（复用既有告警通道，列明条目集与历次原因）；此后该记录不再被释放、不再触发新告警。链启动释放动作纯日志，不发告警。

**D5 select_batch 排除口径**：`select_batch(project_root, batch_size, exclude_ids=None)` 增可选参数，排除集 = `_failed_item_ids(root) ∪ set(exclude_ids or [])`；checkpoint 调用处传 `chain_skipped`。缺省 None 保持向后兼容（存量测试/调用点零改动）。

**D6 进度文案与 phase**：consumed 失败路径收尾 `write_progress(phase="fixing", current="第 N 批失败已跳过（原因）— 继续后续批次")`，不复用 `_finish("failed")`（其语义是链终止）；halt 路径维持 `_finish("failed", ...)`。前端无需改动（读 current/reason 展示）。

**D7 存量断言改写**：`tests/test_code_fix.py` 中「保留 worktree（MUST NOT cleanup）」「失败批终止链」类断言按新语义改写；`record_failed_batch`/`release_failed_batch` 既有签名保留（后者仍供人工兜底调用），新增函数不动既有出口。

**D8 生效路径**：本 SPEC 合回后须 daemon 重启加载新代码；重启时机（批间静默窗口）由运维侧执行，不写 restart_request 交付物任务（避免杀在飞修复批——见 Risks）。

## Risks

- **R1 消费型失败烧排队时间**：链内若干批连续失败时，后续批照常推进，单批重试成本（agent run + 两轮回归）转嫁为「下轮重跑」。接受：车道定位是夜间低优先维护，吞吐优先于单批成功率的时序优化。
- **R2 合回冲突的系统性复发**：主树在批运行窗口内前进（spec 实现分支合并）是该车道与实现车道的结构性竞争，冲突可能整夜反复。缓解：失败档案预算上限兜底（≤3 轮/条目集），达上限即止损并告警；根治（如合回窗口互斥）超出本 SPEC 范围，留待观测数据支撑立项。
- **R3 chain_skipped 挤占当夜吞吐**：agent run 瞬态失败整批跳过本链，当夜不再重试。接受：失败通常成批出现（网关故障面），原地重试大概率同因失败；下轮重试成本低于空转。
- **R4 永久跳过条目的台账悬挂**：达上限条目保持 open 且永不再自动消费，台账出现「永久 open」条目。缓解：达上限告警一次性点名录；后续若需收敛（如自动关闭/降级），凭观测另立 SPEC。
- **R5 消费端兼容**：`fix-failed.json` 新增字段对读侧（load_failed_batches / 前端计数）为增量兼容；`_failed_item_ids` 只读 item_ids 字段不受影响。
