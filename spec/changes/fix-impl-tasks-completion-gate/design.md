# Design: fix-impl-tasks-completion-gate

## Context

`verified → done` 的任务完成度门禁（`_task_completion_blocker`，`core/pm_engine/engine.py:1092`）全局只有一个调用点 —— `_on_spec_verified`（`engine.py:547`）。这意味着「实现者做没做完任务书」这件事，框架要在**实现、验证、合并全部走完之后**才发现。

2026-09-13 的 `add-spec-review-gate` 事故暴露了这条末位检测的三个后果：

1. 实现者自报 `status: "success"` 被无条件采信（`core/agent_runner/runner.py:2688` 的产物硬门对 `agent_type ∉ {planner-judge, planner-plan}` 直接 `return None`），`implementing → implemented → testing → verified` 全链放行。
2. 验证场景由 `planner-plan` 按 SPEC **能力**出题，测的是产品行为；文档 / Dashboard UI / 补充测试这类任务天然没有场景，于是「23/23 全绿 + 17 项未完成」并存是**结构性必然**，不是偶然。
3. 检出后无出路：`VALID_TRANSITIONS[VERIFIED] = [DONE]`、`GATE_TRANSITIONS[VERIFIED] = [TESTING]`，无 `VERIFIED → IMPLEMENTING`；SPEC 死在 verified 死角，只能人工直接改写 `.fenix/STATE.md`（Dashboard 的 13 条 `spec-*` 路由与 CLI 均无回炉入口）。

勘察中还坐实了一条**从未生效的强制契约**：`agents/implementer.md` 与 `agents/fast-track.md` 的 `task-progress-contract` 段要求每条任务一次 `TaskCreate` + 完成瞬间 `TaskUpdate`，但 `.fenix/runs/` 全部 **141** 个 runner 派发的 run 中，含真实 `TaskCreate`/`TaskUpdate` 工具调用的为 **0**；`init.tools` 含 `TaskCreate` 的仅 1 个（`review-2026-09-11.jsonl`，非 runner 派发，模型 `deepseek-v4-pro`）。实现者 run 的 `init.tools` 形如：

```
["Task","Bash","CronCreate",…,"Read","ReportFindings","Skill","TaskOutput","TaskStop",…,"Write"]
```

即 Task 家族（`TaskCreate`/`TaskGet`/`TaskList`/`TaskUpdate`）在派发路由上不存在。

## Goals / Non-Goals

**Goals**

- 把「任务书完成度」的判定从 `verified → done` **前移到实现者收工那一刻**，在源头拦住"没做完却报 success"。
- 给实现者一个**诚实申报未完成**的合法出口，使「做不完」不再等价于「只能谎报」。
- 让被 `task-gap` 拦下的 SPEC 有产品化的人工回炉入口，消除改 STATE.md 的手工作业。
- 让进度契约**可执行**：契约所要求的载体必须与该路由实际具备的工具能力一致。

**Non-Goals**

- **不修**验证场景断言与任务面的对齐问题。本 SPEC 的硬门只能保证"agent 说做完了且勾选与申报自洽"，抓不住"蓄意先勾后做"。
- **不修**交付物守卫 `_deliverable_gate_missing`（`core/pm_engine/verification.py:2621`）只做 blob 存在性检查、`kind: modify` 类"声明了但一字未改"必然放行的问题。
- **不做** `VERIFIED → IMPLEMENTING` 自动回退。
- **不治理** provider 网关长尾（归 `fix-run-hang-amplification`）。

## Decisions

### D1：硬门读 worktree 内的结果文件，不读主树拷回副本

**选择**：`_check_agent_result_artifact()` 新增 `wt_path` 形参（调用点 `runner.py:2688` 已持有 `wt_path`），implementer/fast-track 分支直接读 `wt_path / ".fenix-run-result.json"`。

**为何不读主树副本**：`runner.py:2672-2681` 会把 worktree 结果文件拷回 `project_root/.fenix/.fenix-run-result.json`，但该拷贝是**无条件覆盖**（`if wt_result.exists(): write_text(...)`），且主树路径是跨 spec 共享的。读主树副本等于把"本轮产物"与"上一轮残留 / 其它 spec 残留"混为一谈——正是 `add-verify-contract-autodraft` 与 `add-planready-artifact-gate` 两次事故的形态。worktree 路径天然绑定本轮 run。

**排除的替代**：主树共享文件 + mtime 新鲜度守卫。mtime 守卫在 planner 侧是必要的（planner 本就写主树路径），但对 implementer 是引入不必要的间接层。

### D2：tasks.md 解析收敛到单一实现点，禁止第二套正则

**选择**：把「解析 tasks.md 的数字任务勾选状态」抽成一个纯函数，置于中性模块，供三处共用：`_task_completion_blocker`（`engine.py:1149-1160` 现有内联逻辑）、新硬门、以及 `parse_run_task_done` 的调用方。

**口径**（必须与现状逐字一致）：逐行匹配 `^- \[(x| )\] (\d+\.\d+)`，`x` 记已勾选，空格记未勾选；`tasks.md` 缺失或不含数字任务 → 视为"无缺口概念"，判据通过。

**为何不开第二套**：`_task_completion_blocker` 与硬门判定的是同一个事实。两套正则一旦漂移，会出现"硬门放行、门禁拦截"或反之的矛盾结论——这类矛盾在本框架历史上已造成 `add-planready-artifact-gate` 的归因自相矛盾事故。

### D3：`parse_run_task_done` 下沉到中性模块，原处保留再导出

**问题**：`parse_run_task_done` 定义在 `core/dashboard/data.py:1245`（含 `_RUN_TASK_CACHE` memo），而硬门位于 `core/agent_runner/runner.py`。让 `agent_runner` 直接 import `core.dashboard.data` 是反向依赖（dashboard 是消费层），且会连带拉起 data.py 的模块级副作用。

**选择**：把解析核心下沉到中性模块（如 `core/run_task_track.py`），`core/dashboard/data.py` 保留同名再导出（`parse_run_task_done` 与既有别名 `_parse_run_task_done` 均保持可用），所有既有调用点零改动。

**排除的替代**：在 `runner` 内 lazy import `core.dashboard.data`。可行但把反向依赖写进了代码结构，且 memo 缓存的进程内语义会跟着 runner 走，不清晰。

### D4：能力探测以 `init.tools` 为准，缺工具时 fail-open + 审计

**选择**：硬门读本轮 run 产物中 `type == "system" && subtype == "init"` 事件的 `tools` 数组。含 `"TaskCreate"` → 额外强制 `done_ids ⊇ checked_ids`；不含或事件不可得 → 跳过该项并追加 `impl-task-crosscheck-skipped` 审计事件。

**为何必须条件化**：无条件强制会让硬门在 Task 家族不可用的路由上**永远无法通过**——拒绝 → `AgentArtifactGateError` → 原地续做 → 再拒绝，虽受 `transient_budget` 限制不会无限，但会把每一轮实现全部烧在同一个不可满足的判据上，最终 blocked。这是把"防造假"做成了"防收工"。

**为何 fail-open 而非 fail-closed**：这一项的失败语义是"无法核对"，不是"核对不通过"。框架既有惯例（如 tasks.md 缺失时不拦、lint fail-open）一致。

### D5：进度载体从 TaskCreate 改为 `completed_tasks` / `unfinished`

**选择**：契约载体落在 `.fenix-run-result.json`：

```json
{"status": "success", "spec": "<name>", "summary": "...", "completed_tasks": ["1.1", "2.3"]}
{"status": "partial", "spec": "<name>", "summary": "...",
 "completed_tasks": ["1.1"], "unfinished": ["4.5", "5.1"]}
```

**为何不是"给路由开 Task 工具"**：开工具是环境/网关侧的事（141 个 run 的 `init.tools` 一致缺失，非本仓库代码可单方面决定），且即便开了，TaskUpdate 记录也只是"过程声明"，与 `completed_tasks` 同样不能证明"真做了"。选文件载体则：零环境依赖、与已有结果文件契约同址、可被硬门机械对账、并给 `partial` 提供天然的缺口字段。

**TaskCreate 契约不删除，改为条件生效**：`init.tools` 含 `TaskCreate` 时提示词仍注入 Task 粒度契约（保留既有能力的价值），不含时提示词 MUST NOT 要求它。

### D6：`partial` 不放行、归因非空、消耗预算

**选择**：`partial` 与 `error` 同侧处理——`is_success` 为假、不进 `implemented`、走失败重派、**消耗**实现尝试预算。归因文案 MUST 由 `unfinished` 清单与缺口 id 构成。

**为何必须显式生成归因**：现行 `dispatch.py:733-741` 在 `impl_status != "success"` 且 `impl_status != "error"` 时令 `impl_error = result.error`——而正常收工的 run 的 `result.error` 是 `None`，于是 `final_error` 为空。`add-admin-disposition-empty-shell` 的教训是"空壳处置"必须被杜绝，故 `partial` 必须自带归因。

**为何走消耗预算的通道而非 P0 的续做通道**：P0 的 `AgentArtifactGateError` 续做是"格式没交对、活可能干了"的补救，走 `transient_budget` 不消耗实现预算。若 `partial` 也走那里，"申报 partial"就成了一条绕开预算的无限续做通道。`partial` 的语义是"这一轮就到这儿了"，理应按轮计费，由预算上限收口转 blocked。

**消费点全集**（MUST 逐点确认，不得有"未知状态默认放行"的兜底）：`core/pm_engine/dispatch.py:729-740`、`dispatch.py:1313`、`dispatch.py:2225`、`dispatch.py:3130`、`core/pm_engine/verification.py:3287`、`core/pm_engine/engine.py:766` 的读取器及其调用方。

### D7：硬门失败的退化语义 = 原地续做，不是判失败

**选择**：复用 `AgentArtifactGateError`（`runner.py:277`）既有通道——保 worktree、原地退避、同 session `--resume` 续做，`transient_budget` 限次。续做 prompt 注入硬门归因（缺口任务 id 清单 + 失败类别）。

**为何不判失败重派**：判失败会走 cleanup + 全新 worktree + 全新 session，把已经完成的那部分工作的上下文全部丢掉，等于让 agent 从头再推一遍"还剩什么"。`add-impl-terminal-nocommit-gate` 已验证这条通道（"锚点 B WIP 提交 + 原地退避 + 同 worktree --resume 续做"）是有效的。

**边界**：`transient_budget` 耗尽后按既有语义落失败重派，最终受实现尝试预算约束。本 SPEC 不新增独立重试计数。

### D8：回炉动作单一实现点，API 与 CLI 共用

**选择**：判定与执行收敛到一个函数（置于 `core/pm_engine/` 下，与 `promotion.promote_drafted` 同层同风格），Dashboard 路由与 `bin/fenix_cli.py reflow` 子命令均只做参数解析与结果呈现。

**为何**：`add-spec-review-gate` 的事故正是 CLI 通道绕过评审分流（`cmd_promote` 硬编码 `ready`，不消费 `promote_drafted` 的 `next_status`），修复方式是"读项目配置 + 消费 next_status + 与 daemon 同语义"。同一形态的坑不重踩第二次。

**执行语义**：`StateMachine.update_spec(spec, {"status": "ready", "error": None})`。`update_spec` 对携带 `status` 的更新会自动清 `_cancelled_hold`，并与面板重派 / admin 处置复位同语义；它不做状态机合法性校验，正是本动作用得上的地方（`verified → ready` 不在 `VALID_TRANSITIONS`）。MUST NOT 触碰预算计数、`frozen`、`start_after`。

**开放条件**（全部满足）：SPEC 存在 ∧ `status == verified` ∧ `error` 以 `TASK_GAP_ERROR_PREFIX` 开头 ∧ 未冻结。

### D9：fast-track 叠加而非另起

**选择**：在 `_hard_check_fast_track`（`core/pm_engine/dispatch.py`）既有校验之上叠加同款完成度判据，复用同一解析函数与同一硬门口径。

**背景**：`agents/fast-track.md:5,8` 同样要求读并勾 `tasks.md`，fast-track 一样会带着缺口走到 verified。fast-track 结果文件的顶层 `status` 契约本就是 `"success"`（verdict 承载在 `verification` 段），与本硬门口径兼容。

## Risks / Trade-offs

**[残余风险] 蓄意"先勾后做"不可检**。`completed_tasks` 与 `tasks.md` 的集合相等只是"申报自洽"，不是"工作已做"的证据；在过程性工具不可用的路由上，框架能观测到的只有"文件改了、提交了、自报做完了"。 → **Mitigation**：如实记入文档（`docs/help/`）与 design，不假装解决；真正的防线是验证场景覆盖任务面，而本 SPEC 明确不做，留待后续按残留量评估。本 SPEC 至少把**显式空跑**（本轮事故形态）从"可发生"变成"不可能"，并把隐式空跑的概率压低。

**[风险] 硬门误拦正当收工**。agent 可能真的做完了全部任务，只是忘了写 `completed_tasks` 或 `tasks.md` 漏勾一项。 → **Mitigation**：归因文案必须列出缺口 id（可诊断），失败走原地续做而非废轮（成本是几轮退避而非整轮重做），且续做 prompt 直接给出剩余清单。

**[风险] 硬门不可满足导致预算烧穿**。若 D4 的条件化判断本身出错（如 `init.tools` 解析位置漂移），交叉核对会在无工具的路由上被误判为"需要核对"。 → **Mitigation**：`init` 事件不可得时按"工具不可用"处理（fail-open）；`AgentArtifactGateError` 受 `transient_budget` 限次（非无限循环）；退避通道同样计入全局瞬断指纹，dispatch 闸门对"产物硬门风暴"可见。

**[风险] `partial` 被滥用成逃逸通道**。Agent 可能提前申报 partial 换取下一轮重派。 → **Mitigation**：`partial` 消耗实现尝试预算，连续 partial 受既有预算上限收口转 blocked；且 partial 的**申报一致性判据**（`completed_tasks` ∪ `unfinished` = 全部数字任务，且各自与勾选状态严格对应）是硬门必检项，不能靠 partial 跳过对账。

**[风险] 回炉入口被误用**。人工把"确实没做完但不想做了"的 SPEC 复位，等于用新预算重跑同一件事。 → **Mitigation**：开放条件收窄到"`verified` + `task-gap:` 前缀"；确认交互明示"将重新派发实现"；动作留痕进 `.fenix/PROJECT_LOG.md`；动作不触碰预算计数，重跑的真实成本由实现尝试预算如实记账。

**[风险] 契约改写影响既有读侧**。`completed_tasks` / `unfinished` / `partial` 是新字段，`_task_completion_blocker` 读侧目前只认 `status == "success"` 与 `done_ids`。 → **Mitigation**：`_task_completion_blocker` 对 `partial` 的处理须与 D6 一致（非 success → 走 `return None` 放行分支的现状语义需要复核，避免"partial 轮之后门禁放行"）；`done_ids` 通道保留不动（工具可用时仍是有效证据）。

## Migration Plan

1. **落地顺序**：能力探测与解析函数下沉（D2/D3）→ 硬门分支与续做注入（D1/D4/D7）→ `partial` 语义与消费点对齐（D5/D6）→ fast-track 叠加（D9）→ 回炉动作（D8）→ 提示词与文档同步。
2. **无数据迁移**：不新增 STATE.md 字段、不改配置键、不改既有结果文件的必填项（`completed_tasks` 仅在 `success`/`partial` 时强制，`error` 不受影响）。
3. **回滚策略**：硬门分支可由单一开关式判据（分支入口条件）退回 `return None`，无需回滚数据。回炉入口为纯增量路由与子命令，删除即回滚。
4. **对在飞 SPEC 的影响**：当前 `.fenix/STATE.md` 中非终态 SPEC 会在下一次实现轮次遇到新硬门；因 `completed_tasks` 是新增要求，届时 agent 需按新契约产出——提示词必须与硬门同批次落地，不允许硬门先上线而提示词滞后。

## Open Questions

1. **`completed_tasks` 是否该进结果文件的必填项清单**，还是仅在硬门判定时按需读取？倾向前者（与 `status` 同级声明），使契约在提示词里可逐字引用。
2. **`partial` 的重派是否应携带 `unfinished` 清单进入下一轮 prompt**（类似验证修复轮的缺口注入）？倾向是，但会与"续做"路径的注入重复，需在实现时去重。
3. **要不要给 `partial` 单独的状态标识**（如 `_impl_partial_rounds` 计数）供 Dashboard 区分"网关长尾做不完"与"agent 能力不足"？本 SPEC 暂不做，若观测到高频 partial 再议。
