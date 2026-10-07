<!-- knowledge: capability=turn-limit-lifecycle rev=3 sources=spec/archive/2026-09-17-add-turn-limit-anchor-c,spec/archive/2026-09-18-fix-run-latency-toolresult-parser,spec/archive/2026-10-08-evo-add-impl-run-budget-sizing -->

# 轮次上限与生命周期锚定

run 触及 `agents.max_turns` 轮次上限时的续期判定、终止收口与 WIP 保全：有据续期、封顶终止、现场保全。

## 现行规则

- 活性感知续期（封闭决策矩阵）：轮询环判定 run 达到轮次上限时按封闭矩阵判定续期或终止，不无差别 kill——run 表现出真实推进活性（判定窗口内分支有新提交，或有新 tool_result 事件流量，后者按 tool-result-stream-detection 统一识别）且续期次数未达封顶时，执行轮次续期（extend 上限量），以 `turn_extension` 事件落 run 产物文件留痕（含 extension 序号、步长、活性证据摘要、新上限、剩余未勾选任务数——main 树 tasks.md 判定时点口径，缺失记 unavailable；该字段与簿记占比同为纯观测字段，不参与判定语义，详见 [impl-run-budget-sizing](impl-run-budget-sizing.md)）；无活性或续期封顶时才执行 kill + 锚点 C 收口 + turn_limit_error 失败收口。
- 与超时矩阵互不干扰：判定与超时路径既有 `_supervision_deadline_action` 封闭矩阵同构（extend 有据、封顶有限、每次续期留痕）；超时 extend 计数与轮次续期计数相互独立，两者任一命中均按各自矩阵处置。
- 锚点 C WIP 保全：轮次上限终止（terminate/grace/kill 序列）后、异常收口前，对该 attempt 正在使用的 worktree（存在且为有效 git worktree）执行一次 WIP checkpoint 提交，锚点标识 `turn-limit`——复用既有 `commit_wip_checkpoint` helper（尽力而为、失败降级不阻断），消息契约 `fenix(wip): checkpoint turn-limit <spec>`。worktree 干净或无有效载体时跳过（与锚点 A/B 同语义），不产生空提交；git 操作超时（15s）或失败仅 WARNING 留痕，既有失败收口（append_run_error + RuntimeError）照常执行。
- 强杀消耗观测口径：turn-limit/timeout 等强杀路径（无 result 终态事件）的成本记账区分「观测不到（unobserved）」与「确认为零」——DEBUG 留痕与日志写明消耗不可观测（真实消耗未知且非零为大概率），不出现「tokens counted as 0」字样；STATE 侧成本累计不伪造（不凭空补数、不展示虚构金额），该 run 的 usage 记录带 unobserved 标识供审计区分。

## 溯源

- 2026-09-17 add-turn-limit-anchor-c（spec/archive/2026-09-17-add-turn-limit-anchor-c） — 新增锚点 C 轮次上限收口 WIP 保全、活性感知续期封闭矩阵与强杀消耗 unobserved 观测口径
- 2026-09-18 fix-run-latency-toolresult-parser（spec/archive/2026-09-18-fix-run-latency-toolresult-parser） — 活性证据中的 tool_result 流量改按统一识别判定（user 包裹 block 或顶层兼容形态），修复事件类型假设错误导致流量活性恒判无活性
- 2026-10-08 evo-add-impl-run-budget-sizing（spec/archive/2026-10-08-evo-add-impl-run-budget-sizing） — turn_extension 事件与判定 evidence 增记剩余未勾选任务数观测字段（判定矩阵逐位不变），观测面规则归入 impl-run-budget-sizing 页
