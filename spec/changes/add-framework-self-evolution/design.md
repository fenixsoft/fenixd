## Context

`add-daily-self-review` 已交付自省链路：每晚（`admin.self_review.run_at`，本机 02:00）由每个被管项目自己的 daemon 产出 `.fenix/todo.md`（`## YYYY-MM-DD` + `### 浪费/失误/可改进` + 条目四字段），并把 `last_run_date` / `last_run_at` 写入 `.fenix/self_review_state.json`。`core/self_review.py:27-30` 有硬约束禁止自省链路创建 SPEC / 注册 STATE / 派发 agent——立项权保留给人。

现状的三个事实决定了本设计：

1. **todo.md 的下游是空的**。三个被管项目（fenixd / fenix-server / scheduling-showcase）持续产出条目，但没有任何机制消化它们；人工逐条复核 + `/fenix-new` 起草的吞吐远低于产出速率。
2. **自省条目不可直接采信**。2026-09-12 复盘：「证据段近全中、根因段 8 条错 3 条」；历史上多次出现建议与源码实际不符。因此下游必须先**独立回源复核**，再决定是否立项。
3. **跨项目视角只有 Dashboard 有**。每个被管项目跑自己的 daemon，`core/dashboard/registry.py` 与 `/api/overview` 是唯一的跨项目事实源；而 agent 执行能力（AgentRunner、预算、告警、run 记录、超时监督、provider 熔断）只在 daemon 侧。

框架自身是自托管开发的（本机 `PROJECT_ROOT == FRAMEWORK_ROOT == /root/fenixd`），所以「框架改进自己的 SPEC」落回框架仓库、由框架 daemon 开发，闭环最短。

## Goals / Non-Goals

**Goals:**

- 把 todo.md → 复核 → SPEC 草稿 → 人工一键立项（或开关打开后自动立项并开发至 push）这条下游补齐，且**保留人工闸门为默认**。
- 复用既有骨架：AgentRunner（执行/预算/告警/熔断/run 记录）、ConfigLoader（配置 + 30s 热更新）、StateMachine（注册与状态机）、registry（跨项目发现）、设置页 UI 与配置 API。**不引入新的运行时依赖**。
- 每个条目都有可复查的复核结论（三项判定 + 证据），用户不点开 SPEC 也能判断该不该立项。
- 未注册草稿对 daemon 与 SPEC 列表**完全不可见**，且不会给主树带来未跟踪文件风险。

**Non-Goals:**

- 不改自省链路本身（`self_review` MUST NOT 建 spec 的护栏原样保留；todo.md 格式不变）。
- 不做「改进 SPEC 按来源项目分流」——一律落框架仓库（用户决策）。
- 不改推送审批门（`gates.require_push_approval` 保持）。
- 不做分析结论 / 草稿的在线编辑，不做历史条目的周期性全量复核（只做增量水位）。
- 不做非自托管部署（`PROJECT_ROOT != FRAMEWORK_ROOT`）下的跨项目自进化。
- 不做「建议改进项」的卡片式移动端降级（仅横向滚动 + 操作列固定）。

## Decisions

### D1 宿主：框架自身 daemon（`PROJECT_ROOT.resolve() == FRAMEWORK_ROOT`）

跨项目视角出现在 daemon 里并不自然，但**执行与登记必须落在 daemon**：分析 run 需要 AgentRunner 的超时监督、轮次上限、token 预算、provider 熔断与 `.fenix/runs/` 记录；接受路径需要 `StateMachine.add_spec`，而注册后由**同一进程**的事件总线在 2s 内拾取，不需要任何跨进程信号（历史上文件信号（`restart_request` / `approve_push_request`）因「无消费者确认」反复出问题，这里刻意不再引入第三条文件信号）。

跨项目列表由 daemon 直接复用 `core/dashboard/registry.py` 的项目发现（只读 `~/.config/fenixd/dashboard.yaml` + 一级目录扫描），不做第二份项目清单。宿主守卫用路径恒等比较：`FRAMEWORK_ROOT = Path(core/__file__).resolve().parents[1]`（与 `core/agent_runner/prompt_builder.py:18` 同式），与 `PROJECT_ROOT.resolve()` 比较；不相等则整套能力不启用（日志一次，不刷屏）。Dashboard 侧在该情形下显示不可用提示。

**被否决的方案**：Dashboard 侧托管。Dashboard 虽有跨项目视角与 headless claude 调用先例（`/api/project/describe`），但那是 120s 同步调用；把长任务 agent 执行搬进 Web 服务进程意味着 run 记录、预算归账、告警、超时监督全部要另建一套，且 dashboard 重启（历史多次）会杀在飞 run。

### D2 草稿存 `.fenix/evolution/drafts/<id>/`，接受时才进 `spec/changes/`

未注册 SPEC 在本框架里**不是**合法状态：daemon 只认 STATE.md（`promote_drafted` 对无 entry 的目录返回 `not found`，`tests/test_pm_promotion_gate.py:196` 已固化该语义），但 `spec/changes/<name>/` 下留一个未跟踪目录会与自托管的其他 agent 的 `git stash` / merge-back 相互作用——历史已两次因未提交/未跟踪文件导致 merge-back 熔断（`fenix-merge-back-untracked-spec-deadlock`、`fenix-stashpop-unmerged-deadlock`）。

因此草稿全程留在 gitignored 的 `.fenix/evolution/` 暂存区，接受时才「复制到 `spec/changes/` → 仅 `git add` 该目录 → 提交 → 注册」四步一次做完，拒绝时整目录删除。这样：①「不可见」由路径保证，不依赖任何门禁；② 主树 git 状态在任何时刻都不引入新未跟踪文件；③ 拒绝是纯删除，无需清理残留。

### D3 触发：就绪即入队，不等待其他项目到齐

用户明确选择「不等，就绪即分析」。检查点（节拍复用 `admin.interval_minutes`）逐项目比较 `.fenix/self_review_state.json.last_run_at` 与水位 `last_analyzed_at`，就绪即入队；**无分析 run 在途时立刻以队列中全部就绪项目启动一次分析 run**，有在途则留队到下一检查点。这条折中同时满足两件事：不等待其他项目（符合「就绪即分析」），以及同一轮就绪的多个项目仍是**一个** claude 进程（符合原始需求「启动一个 claude code 进程，将各项目有更新的 todo.md 传递给它」）。

代价：一夜之间可能连开多个分析 run（项目自省时刻分散时）。可接受——`max_items_per_run` 与增量水位把单轮成本封顶，且分析 run 走既有预算与告警。

### D4 去重以 `items.jsonl` 的 id 集合为权威，水位只做触发判据

条目身份键 `id = sha1(project|date_section|section|title)[:12]` 与运行环境无关、可复算。**权威去重来源是 `items.jsonl` 已存在的 id**：凡 id 已在库（无论状态）即不再分析、不再生成草稿。水位 `last_analyzed_at` 只用于回答「这个项目有没有新内容值得起 run」，不承担去重职责。

这样 `max_items_per_run` 的截断自然正确：未处理的条目 id 未入库，下一轮自然被再次选中；水位推进用 run 启动时的快照时刻（不用落地时刻），避免漏掉 run 执行期间自省新写入的条目。

### D5 子代理只做复核，落盘/校验/注册全在框架代码里

分析 run 对每条新条目派一个 Task 子代理做**只读**复核，产出三项判定 + 证据 + `analysis_md`，并按 fenix-new 流程给出 SPEC 的文本内容（`spec.name` / `capability` / 四份文档正文），写进契约 JSON——**子代理不写任何文件**。

落地由框架的确定性代码完成：写条目 → 写草稿目录 → 跑与 daemon 晋升同源的 lint（`core.deliverables.lint_declared` + `lint_tasks_parseable`）→ 通过才置 `pending`，不通过删草稿置 `draft_failed`。理由：lint、路径校验、git 提交、STATE 注册都是确定性、可回归的东西，交给 LLM 会让失败模式发散（历史上「声明段写目录 / 写 gitignored 路径」正是靠这套 lint 才拦住的）。**降级**：init 事件工具表无 Task 族时（该门控由 `--model` 模型名决定，第三方模型名可用，第一方 `claude-*` 名不可用），同进程串行逐条复核，结论完整度不降，产物记 `degraded`。

### D6 接受路径复用 fenix-new §4/§5 语义，且必须「先提交后注册」

SPEC 名 `evo-<slug>`（用户决策的前缀；slug 由 agent 给出并校验 `^[a-z0-9][a-z0-9-]*$`），重名追加 `-<id 前 6 位>`。落地顺序固定为「复制 → 仅 add 该目录 → commit → `add_spec(status='drafted', priority=5)` → 删暂存草稿」，失败一律不留半成品：提交失败不注册（`accept_failed` + 告警 + 保留可重试）；注册失败保留草稿并告警。注册为 `drafted` 后由既有 `gates.promote_mode`（本机 auto）自动晋升，流水线终点仍是 `pushed`（需人工审批推送），与用户「直至推进到 push 状态」一致。

人工「同意」与开关打开后的自动接受**共用同一实现**，只差 `decided_by`（`manual` / `auto`）与终态名（`accepted` / `auto_accepted`）——避免两条路径语义漂移。

### D7 全局开关存用户级配置

`self_evolution` 两键（`auto_accept`、`max_items_per_run`）存 `~/.fenix/config.yaml`。`ConfigLoader.resolve_config` 本就 deep_merge 用户级 + 项目级（`core/config.py:198-216`），daemon 侧无需额外读取逻辑即可看到开关并随 30s 热更新生效。Dashboard 配置写入 API 对项目级作用域提交 `self_evolution` 返回 400（引导到用户级），从而「全局开关」在正常路径下语义唯一；面板在项目级作用域把控件置只读并提示。

### D8 前端复用 spec 列表页的「更多」形态与既有配置/文档展示方式

「操作」列直接照搬 `pages/projects/list.tsx:886-892` 的 `Dropdown + MoreOutlined + menu onClick` 形态（含移动端同一份菜单函数、`touch-expand`），四项动作与禁用规则集中在 `SuggestedImprovementsPanel` 内。「查看分析结论」与「查看 SPEC 草稿」走 Drawer/Modal + Markdown 渲染，草稿文档切换沿用 SPEC 详情页「文档」页签的交互直觉。**不复用** `/api/spec-doc`——它要求 spec 在 STATE.md 中（草稿恰恰不在），因此新开 `/api/evolution/draft`，读取路径固定由 `item_id` 推导、不接受任意路径参数。

### D9 新配置项必须带界面（既有约束）

`self_evolution` 的两键都必须在「建议改进项」卡片顶部有可见控件（开关 + 数字输入）——这是仓库既有约束（`fenix-new-config-needs-dashboard-ui`），也是新增配置键与 UI 同步落地的验收点。

## Risks / Trade-offs

- **全自动 LLM 链路的结论质量**：复核结论可能仍偏、草稿可能不可用。缓解：① 每轮强制同源 lint 硬门（不过一律 `draft_failed` 不落地）；② 默认关闭自动接受，人工「同意」为默认闸门；③ 复核要求引用可核对证据、核实不了写「未核实」，便于人工快速识别水货结论。
- **自动接受打开后的预算消耗**：框架会自行立项并开发。缓解：`max_items_per_run`（默认 20）封顶单轮条目数；自动接受逐条独立、失败不影响其余；开关随时可关（30s 热更新）；每轮落地结果记 INFO 日志，注册后的 SPEC 与人工立项走同一条预算/告警通道。
- **草稿写盘与在飞 run 的竞争**：由 D2 的暂存区设计规避——写盘只发生在 gitignored 目录，避免主树出现未跟踪文件触发 `git stash` / merge-back 熔断；接受时的提交是单目录、原子语义（仅 add 该目录）。
- **daemon 与 Dashboard 同时写同一存储**：`.fenix/evolution/items.jsonl` 由 daemon（落地/自动接受）与 dashboard（人工同意/拒绝）双写。缓解：条目更新采用「读-改-写 + 文件锁 + 原子替换」（沿用 `StateMachine.write_all` 的 flock + tempfile + rename 范式）；单条更新粒度小、无长事务。残余风险：极端并发下仍可能丢弃一次更新，表现为条目状态需刷新一次才正确——不产生错误注册（接受路径本身幂等）。
- **跨项目文件读取范围扩大**：daemon 会读取被管项目 `.fenix/self_review_state.json` 与 `.fenix/todo.md`。缓解：路径由 registry 项目根拼接、文件名固定、不接受外部路径参数；只读、不写被管项目。
- **Task 工具族可用性**：由 `--model` 模型名门控，第一方 `claude-*` 名不可用。缓解：D5 的串行降级 + 产物留痕；降级不导致整轮失败。
- **回滚**：改动集中在「新模块 + daemon 检查点挂载 + dashboard 端点 + 前端面板」。紧急回滚可只关自动接受（配置开关），或移除检查点挂载；未开启本功能时（无 `self_evolution` 配置、无分析 run）行为与落地前等价，todo.md 与自省链路零影响。
