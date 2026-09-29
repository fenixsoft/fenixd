<!-- knowledge: capability=impl-tasks-completion-gate rev=1 sources=spec/archive/2026-09-19-fix-impl-tasks-completion-gate -->

# 任务书完成度收工硬门

实现者车道 run 的产物硬门：`exit 0` 不等于成功，结果文件与任务书完成度须过门才算收工，防止「自报 success 却留大量未勾任务」的空转收工。

## 现行规则

- 覆盖车道与校验对象：产物硬门覆盖 `implementer` 与 `fast-track` 两类 agent；校验对象是本轮 run 的 worktree 根目录下的 `.fenix-run-result.json`（不经主树拷回副本判定，避免读到上一轮残留）。
- 基础校验序列：`exit 0` 时依次校验——文件存在、非空、内容为合法 JSON、顶层为对象（非数组/标量）、顶层 `status` ∈ 白名单 `{"success", "error", "partial"}`。任一不满足返回失败归因（含具体路径与失败类别），由调用方抛 `AgentArtifactGateError`。
- `success` 完成度判据：①勾选清零——worktree 内 `tasks.md` 不存在未勾选数字任务，口径与 `_task_completion_blocker` 同源（正则 `^- \[(x| )\] (\d+\.\d+)`，不另写第二套解析）；tasks.md 缺失或不含数字任务时该项通过。②完成清单对账——结果文件顶层 `completed_tasks` 集合与已勾选数字任务 id 集合完全相等（缺项、多项、含非数字 id 均判失败）。
- `partial` 申报一致性判据：结果文件须同时含 `completed_tasks` 与 `unfinished` 两数组；两集合与勾选/未勾选数字任务 id 集合严格相等、互斥且并集覆盖全部数字任务 id。防止 `partial` 成为绕过 `success` 判据的缺口。
- `error` 不施加任何完成度类判据。
- TaskUpdate 交叉核对条件化：读取 run 产物 `init` 事件的 `tools` 数组做能力探测；含 `TaskCreate` 时强制 `done_ids` 覆盖全部已勾选任务 id，不一致判失败；不含（或 init 事件不可得）时跳过核对并放行，同时向 run 产物追加 `impl-task-crosscheck-skipped` 审计事件。交叉核对不得实现为无条件硬要求，否则在 Task 工具不可用的路由上形成「拒绝 → resume → 再拒绝」的预算烧穿循环。
- 失败处置走原地续做：硬门失败复用 `AgentArtifactGateError` 既有通道——保留 worktree 与 run 现场、按既有退避序列原地重试、同 worktree 同 session `--resume` 续做，不清理 worktree、不判「零成果整轮重做」；续做轮 prompt 注入缺口任务 id 清单与失败类别。连续失败由既有 provider-transient 退避与实现尝试预算收口，不新增独立重试计数。
- 归因可诊断：失败文案指明具体文件、失败类别（缺失/为空/非法 JSON/顶层非对象/status 白名单外/未完成任务/完成清单不一致/TaskUpdate 不一致）与相关任务 id；status 白名单外时文案含实际读到的取值；缺口 id 清单最多列前 20 个、其余以数量概括。
- `partial` 消费点一致性：`partial` 是「诚实申报未完成」的合法终态，全部结果消费点上——判非成功终态（与 `error` 同侧），不放行 `implemented → testing`；生成非空失败归因（由 `unfinished` 与缺口任务 id 构成，不用 `result.error`，避免成功进程产出空壳处置）；走既有失败/重派通道并消耗实现尝试预算（不走不消耗预算的原地续做通道，防「申报 partial → 无限续做」绕行）；连续 `partial` 由既有预算上限收口转 blocked 交人工。

## 关键行为

- run 进程 `exit 0` → 硬门读取 worktree 根结果文件 → 基础校验 → 按 `status` 施加对应判据 → 通过放行 / 失败抛 `AgentArtifactGateError` 进原地续做。

## 溯源

- [2026-09-19 2026-09-19-fix-impl-tasks-completion-gate](spec/archive/2026-09-19-fix-impl-tasks-completion-gate/) — 确立全部门禁：结果文件硬门覆盖实现者双车道、success/partial 判据、TaskUpdate 能力探测条件化、原地续做处置、归因契约与 partial 消费点一致性
