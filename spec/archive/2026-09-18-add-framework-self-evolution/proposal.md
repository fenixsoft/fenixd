## Why

`add-daily-self-review` 已把「全天复盘」自动化：每晚按项目把当日**浪费 / 失误 / 可改进**追加写入被执行项目的 `.fenix/todo.md`，每条含影响、证据、调查评估、建议四项，质量标准是「新 agent 可据此直接起草 SPEC」。但这条链的**下游是断的**：

- `core/self_review.py:27-30` 有硬约束「本模块及自省链路 MUST NOT 创建 spec/changes 条目、注册 STATE.md 条目或派发任何 agent」——这条护栏本身是对的（立项权属人，`add-daily-self-review` 立项意图），但护栏之后没有任何替代通道；
- 于是 todo.md 只能等人读一遍、逐条回源复核、再手工 `/fenix-new` 起草 SPEC。当下 `.fenix/todo.md` 已在 fenixd / fenix-server / scheduling-showcase 三个项目持续产出，单日新增动辄五六条，人工复核 + 起草的吞吐远低于产出速率——todo.md 事实上正在退化成只写不读的日志。

同时，**自省条目本身不可直接采信**：2026-09-12 复盘结论为「todo.md 证据段近全中、根因段 8 条错 3 条」，且此前多次出现「自省建议与源码实际不符」。所以下游不能是「照单立项」，必须是「**逐条独立回源复核 → 判定是否值得立项 → 只对判定值得的条目按 fenix-new 流程起草 SPEC**」，且**起草结果仍由人点「同意」才立项**。

本 SPEC 把这条下游补齐，同时把人工闸门保留为默认：设置页「自愈」页签升级为「自进化」，除既有「代码陈旧自愈」卡片外新增「建议改进项」卡片——跨项目分条展示复核结论与 SPEC 草稿，用户一键「同意（开始立项）／拒绝（放弃并删除）」。另加全局开关「允许框架自改进」（默认关闭）：打开后才授权框架自动接受全部判定值得立项的条目，并自动开发直至推进到 push 状态。

为什么现在做：① 自省已在跑（`admin.self_review.enabled: true`，三个项目持续产出 todo.md）；② 框架自身是自托管开发（该 daemon 的 `PROJECT_ROOT == FRAMEWORK_ROOT`），改进 SPEC 落在框架仓库、由框架 daemon 开发，闭环最短；③ 触发、执行、状态机、配置、dashboard 骨架全部现成（AgentRunner / ConfigLoader / StateMachine / registry / 设置页），无新增运行时依赖。

## What Changes

- **设置页页签改名与扩展**：`core/dashboard/static/src/pages/settings/index.tsx` 的菜单项由 `{ key: 'selfheal', label: '自愈' }` 改为「自进化」；页签下**第一张卡片**仍为既有 `StaleCodeSelfhealPanel`（「代码陈旧自愈」，标题、配置键、语义全部不变），**第二张卡片**为新增 `SuggestedImprovementsPanel`（「建议改进项」）。
- **自进化触发（框架自身 daemon）**：`fenixd.py` 主循环新增检查点——按 dashboard registry 逐项目读取 `<proj>/.fenix/self_review_state.json` 的 `last_run_at`，与该项目的分析水位比较，**就绪即入队**（MUST NOT 等待其他项目到齐）；当前无分析 run 在跑时立刻以队列中全部就绪项目启动一次分析 run（一个 claude 进程拿到多个项目的 todo.md），有在跑则留在队列等下一检查点。仅 `PROJECT_ROOT == FRAMEWORK_ROOT` 的 daemon 启用本检查点。
- **分析 agent 角色**：新增 `agents/evolution.md` prompt 与 `evolution` 角色（`prompt_builder.py` 映射 + `runner.py` 一个新入口 + `core/config.py` 的 `KNOWN_AGENT_TYPES`），模型链取 `agents.models.self-review` → 回退 `agents.models.administrator`；在主树无 worktree 运行（同自省），`run_id` 前缀 `evo-`，超时/预算/告警/provider 熔断全部走既有 AgentRunner。
- **逐条子代理复核**：分析 run 对每个就绪项目 todo.md 中**水位之外的新条目**各派一个 Task 子代理，独立回源核查（只读日志/源码/STATE，不采信 todo.md 自述），判定三项——问题是否存在且准确 / 建议是否合理完整 / 是否有价值与必要性立项修复；init 工具表无 Task 族时降级为同进程串行逐条并记录降级原因。
- **契约产物**：run 结束写 `.fenix/evolution/out-<run_id>.json`（`items[]`：项目、日期节、小节、标题、原始四字段、`verdict{problem_exists,suggestion_sound,worth_spec,rationale}`、`analysis_md`、`spec` 全套内容或 `null`）；JSON 非法或缺必填字段 → 该 run 判失败并写 admin 告警，水位不推进。
- **框架侧确定性落地**（agent 只产出内容，落盘/校验/注册一律由框架代码完成）：条目入库 `.fenix/evolution/items.jsonl`；**增量水位去重**（身份键 = 项目 + 日期节 + 小节 + 标题 的稳定摘要；已分析过、已生成草稿、已接受/已拒绝的条目 MUST NOT 重复分析或重复生成）；`worth_spec` 为真且内容齐全 → 按 fenix-new 流程写 SPEC 全套到 `.fenix/evolution/drafts/<id>/`（`proposal.md` / `specs/<capability>/spec.md` / `design.md` / `tasks.md` / `.spec.yaml`），并跑与 daemon 晋升同源的 lint 预检（`core.deliverables.lint_declared` + `lint_tasks_parseable`）；lint 不过或内容缺失 → 条目标 `draft_failed` 并记录 violation，MUST NOT 落到 `spec/changes/`、MUST NOT 注册。
- **接受路径**（人工「同意」或开关打开后的自动接受，同一实现）：草稿落地到 `spec/changes/<evo-name>/` → 仅 `git add` 该目录并提交 → `state_machine.add_spec(name, {status: 'drafted', priority: 5})`；注册后由既有流水线自动晋升/实现/验证直至 `pushed`（**推送审批门 `gates.require_push_approval` 保持不变**）。SPEC 名 = `evo-<slug>`（统一前缀），重名时追加条目 id 短后缀。接受路径幂等；提交或注册失败 → 不注册、告警、状态置 `accept_failed` 并保留草稿可重试。
- **拒绝路径**：「拒绝（放弃并删除）」删除 `.fenix/evolution/drafts/<id>/` 并把条目标 `rejected`；删除 MUST 限定在该条目自己的草稿目录内；已接受的条目 MUST NOT 可拒绝。
- **新的用户级配置节 `self_evolution`**：`auto_accept`（布尔，默认 `false`）与 `max_items_per_run`（正整数，默认 `20`）；非法值回退缺省且不使 daemon 启动失败；走既有 30s 配置热更新。两键均为**全局（用户级）键**，项目级写入 MUST 被拒绝。
- **新增 dashboard 端点（5 个）**：条目列表、分析结论全文、草稿文档全文、接受、拒绝。
- **自动接受**：`self_evolution.auto_accept` 为真时，分析 run 落地完成后对全部 `draft_ready` 且 `pending` 的条目自动走接受路径（记录 `decided_by: auto`），无需用户点击。

## Capabilities

### New Capabilities

- `self-evolution`: 框架自身的自进化链路——触发与就绪扫描（跨项目、就绪即分析、单飞）、分析 run 的角色/模型/执行形态、逐条子代理复核与降级、契约产物、增量水位与幂等、草稿生成与同源 lint 校验、接受/拒绝/自动接受的落地语义、`self_evolution` 配置节与用户级约束、失败与降级可观测性。
- `suggested-improvements-ui`: 设置页「自进化」页签与「建议改进项」卡片——全局开关与每轮上限、跨项目表格（列与状态）、操作列「更多」下拉（查看分析结论 / 查看 SPEC 草稿 / 同意 / 拒绝）与 spec 列表页一致的交互形态、查看类内容的展示、接受/拒绝的前端交互与反馈。

### Modified Capabilities

- `stale-code-selfheal`: 设置页页签文案由「自愈」改为「自进化」，`stale_code_selfheal` 面板迁移为该页签下的第一张卡片；配置键、缺省值、语义与面板控件本身不变（仅归属页签与页面标题变化）。

## Impact

- **代码（后端）**：`fenixd.py`（自进化检查点挂载）、新增 `core/evolution.py`（就绪扫描、水位与条目存储、草稿落盘、同源 lint、接受/拒绝/自动接受）、`core/config.py`（`self_evolution` 读取与校验、`KNOWN_AGENT_TYPES` 增 `evolution`）、`core/agent_runner/prompt_builder.py`（prompt 映射与 `_build_evolution_prompt`）、`core/agent_runner/runner.py`（`run_evolution` 入口与模型链解析）、`core/dashboard/data.py`（配置白名单/缺省回显/前置校验/项目级拒绝）、`core/dashboard/server.py`（5 个新端点）。
- **代码（前端）**：`core/dashboard/static/src/pages/settings/index.tsx`（菜单改名 + 挂载新面板）、新增 `core/dashboard/static/src/pages/settings/components/SuggestedImprovementsPanel.tsx`、`core/dashboard/static/src/services/dashboard.ts`（新类型与请求封装）；构建产物 `core/dashboard/static/dist/` 由 `npm run build` 重建。
- **新增资产**：`agents/evolution.md`（分析 agent prompt，含子代理派发契约与 JSON 产物契约）。
- **配置**：新增用户级节 `self_evolution`（`auto_accept` / `max_items_per_run`），无该节时行为等同本 SPEC 落地前（不生成、不自动接受）。
- **运行时产物（gitignored，非交付物）**：`.fenix/evolution/items.jsonl`、`.fenix/evolution/state.json`（水位）、`.fenix/evolution/drafts/<id>/`、`.fenix/evolution/out-<run_id>.json`、`.fenix/runs/evo-*.jsonl`。
- **文档**：`docs/help/08-dashboard.md`（设置页「自进化」页签与「建议改进项」面板）、`docs/help/09-config.md`（`self_evolution` 节 + 页签-配置键对照表）、`docs/help/10-artifacts.md`（`.fenix/evolution/` 产物）、`docs/help/03-lifecycle.md`（自进化 SPEC 的 `evo-*` 前缀与进入流水线的位置）。
- **依赖（不修改）**：`core/dashboard/registry.py` 的项目发现、`core/self_review.py` 的 `.fenix/self_review_state.json` 契约、`StateMachine.add_spec`、`AgentRunner._run_claude`、`core/deliverables.py` 的 lint 函数——全部按原样复用，本 SPEC 只调用不重定义。
- **风险**：① 分析 run 是全自动 LLM 链路，可能产出低质量结论或错误草稿——由「同源 lint 硬门 + 默认关闭的人工同意闸门」缓解（lint 不过一律 `draft_failed` 不落地）；② 自动接受打开后框架会自行立项并开发，可能消耗预算——由 `max_items_per_run` 上限、每轮告警与开关随时可关缓解；③ 草稿写盘与在飞 run 的 merge-back 竞争——由「草稿只落 gitignored 暂存区、接受时才进 `spec/changes/` 并即时提交」规避（`autostash` 熔断历史已两次发生）；④ 跨项目文件读取范围扩大——只读各项目 `.fenix/self_review_state.json` 与 `.fenix/todo.md` 两个文件，路径由 registry 项目根拼接，不接受任意路径参数。
- **非目标**：不改自省链路（`self_review` MUST NOT 建 spec 的护栏原样保留）；不按来源项目分流改进 SPEC（**一律落框架仓库**）；不改推送审批门；不做分析结论/草稿的在线编辑；不做历史条目的周期性全量复核（只做增量水位）；不做「建议改进项」表格的卡片式移动端降级（仅横向滚动 + 操作列固定）；不做非自托管部署（`PROJECT_ROOT != FRAMEWORK_ROOT`）下的跨项目自进化——该场景下面板显示不可用提示且不发分析 run。
