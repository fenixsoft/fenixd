# 评审结论消费与中断恢复
<!-- knowledge: capability=spec-review-recovery rev=2
     sources=spec/archive/2026-09-19-add-spec-review-gate,spec/archive/2026-09-24-fix-spec-review-blocking-dispatch -->

评审 run 收工后的机械收口（approved/repaired 放行、rejected 打回）、未完成重试与上限冻结、人工恢复双路径与入口契约。

## 规则

- 执行模型：评审 run 经派发队列在独立 worker 线程异步执行，与 implementer 同构；派发入口入队后立即返回，不阻塞调用线程。「锚点先落盘 → 快照 → 执行 → 机械收口」四步链在同一调用栈内闭合（收口用本轮 attempt 的 `run_started_at` 做结果新鲜度校验），但该调用栈不是调用方线程。
- worker 内异常走统一失败回滚路径（`_rollback_failed_dispatch` 的 `spec-review` 分支），不得让 SPEC 停留在 `reviewing` 且无锚点、无 error、无恢复路径；四步链之外的异常使 SPEC 停留 `reviewing` 且 `reviewer_run` 为空时，既有 recovery 的 `reviewing` 分支（全量扫描 / watcher）重新触发评审派发，不依赖人工。
- 结论机械消费（不交 LLM 二次解释）：
  - `approved` / `repaired` → `transition(spec, "ready")` 并直调 `_on_spec_ready(spec)` 进入实现调度（与晋升成功路径同语义，不依赖事件循环）；repaired 时 SPEC 目录保留评审者的修补。
  - `rejected`（打回）→ 不进入实现调度：未达打回上限时回 `reviewing` 自动复评（经队列入队接力，`error` 写 `spec-review-rejected:` 加 blocking 条目维度与证据摘要，`_review_rejections` 递增、`_review_rejection_class` 留痕，复评 prompt 注入上轮 blocking 摘要以区分「前提证伪」与「文档不一致」）；打回累计达上限（`MAX_REJECT_REDO = 2`，含首次）时冻结转人工——`freeze_for_human` 置冻结态并发 `spec-review-rejected` 告警，人工修订方案后解冻恢复 `reviewing` 重派评审，或直接撤销。
  - 评审未完成（未通过结果硬门或写入边界校验）→ 不得归入任何评审结论（尤其不得按 approved 放行）。
- 未完成重试：递增 `_review_attempts` 并经派发队列重新入队重试（不得在收口线程内递归调用派发入口；重试入队前必须已清除 `reviewer_run` 锚点，否则队列候选筛选会判定「已有在飞评审」而拒派）。累计尝试上限 3 次（首次派发 + 最多 2 次重试），达上限 `transition(spec, "blocked")` 并把失败原因写入 `error`，前缀 `spec-review-incomplete:`；重试成功则状态到 ready、计数清零。
- 失败原因具体可辨，至少区分：进程非零退出、结果文件缺失或为空、JSON 非法、`status` 越白名单、mtime 陈旧、`repairs` 路径越界、SPEC 目录外越界写入、`status` 与改动不一致。
- 两类评审 blocked 通过 `error` 前缀与其它 blocked 原因严格区分：`spec-review-rejected:`（方案被否决，冻结态）与 `spec-review-incomplete:`（评审未完成）；不复用熔断、冻结、合并失败等前缀；error 内容足以让 Dashboard 与人工不读 run 流转录即可判断该做什么。
- 人工恢复双路径（均人工显式触发，任何自动链路不得调用）：
  1. **重新评审**：`transition(spec, "reviewing")`，用于人工已修改 SPEC 内容、要求再次过评审门；
  2. **担责放行**：`transition(spec, "ready")`，人工裁决后直接进入实现调度，不自动重评。
- 重新评审开放条件：目标 SPEC 状态为 `blocked`、`error` 以两类评审前缀之一开头、且不带 `frozen: true` 标记；任一不满足即拒绝并返回明确原因，STATE 无变更。对非评审类 blocked（熔断、合并失败、人工冻结）执行重新评审被拒，防止把不应进自动链的 SPEC 误推进评审；重复触发靠幂等防御（第二次因状态已非 blocked 被拒），不派发两个评审 run。
- 评审不占实现并发槽位：评审条目不增减 `_active_runs`、不进入 `_active_priorities` / `_active_priority_counts`（不参与宽松优先级档位比较，不以「更重要的活动任务」身份阻塞低优先级实现派发）；以自身优先级参与队列内排序（同档 FCFS）；在飞状态由独立集合 `_active_reviews`（spec 名）登记，出队置位、worker 收尾释放，集合由队列锁保护；评审并发不设上限。
- 入口：Dashboard spec 列表展示 `reviewing` 状态（独立于其余状态的视觉标识），「重新评审」入口仅对评审类 blocked 可见（带确认），操作失败展示后端拒绝原因；设置页「审批」页签提供 `gates.spec_review_mode` 单选（auto/never，位于草稿晋升模式设置项相邻处）；提示词页签与模型分配包含 `spec-review` 角色。CLI `bin/fenix_cli.py review <spec> [--project <path>]` 与 Dashboard 同语义，失败以非零退出码表示。

## 溯源

- [2026-09-19 2026-09-19-add-spec-review-gate](spec/archive/2026-09-19-add-spec-review-gate/) — 新增结论消费与恢复：机械收口三分支、未完成重试与 3 次上限、两类 blocked 前缀、人工恢复双路径与开放条件、Dashboard/CLI 入口
- [2026-09-24 2026-09-24-fix-spec-review-blocking-dispatch](spec/archive/2026-09-24-fix-spec-review-blocking-dispatch/) — 评审异步化：派发队列 worker 执行与四步链同栈闭合、重试经队列且先清锚点、worker 异常统一回滚、评审不占实现并发槽位且无并发上限
