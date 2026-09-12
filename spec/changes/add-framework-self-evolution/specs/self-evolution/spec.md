# self-evolution Spec

## ADDED Requirements

### Requirement: 自进化触发与就绪扫描

框架自身 daemon（`PROJECT_ROOT.resolve() == FRAMEWORK_ROOT`，`FRAMEWORK_ROOT = Path(core/__file__).resolve().parents[1]`）MUST 在主循环维护一个自进化检查点，节拍复用既有 admin 巡检间隔（`admin.interval_minutes`，缺省 5 分钟）。检查点按 Dashboard registry（`core/dashboard/registry.py` 的项目发现结果）逐项目判定就绪：

- 就绪条件：`<proj>/.fenix/self_review_state.json` 存在，其 `last_run_at` 可解析为 ISO8601 时间，且**晚于**该项目在 `.fenix/evolution/state.json` 中的 `last_analyzed_at`（该项目无记录时视为「从未分析」，只要 `last_run_at` 存在即就绪），并且 `<proj>/.fenix/todo.md` 存在且非空。
- 未就绪的项目 MUST NOT 入队，且 MUST NOT 为此产生 admin 告警（项目未启用自省、daemon 未运行都属正常态，最多一条 DEBUG/INFO 日志）。
- **就绪即入队**：MUST NOT 等待其他项目自省结束或到齐。
- 当且仅当当前无自进化分析 run 在途时，检查点 MUST 立刻以队列中全部就绪项目启动一次分析 run（一个 claude 进程同时拿到多份 todo.md）；已有分析 run 在途时 MUST NOT 启动第二个，就绪项目留在队列等下一检查点。
- 分析 run 在途的判定 MUST 基于 daemon 内部活跃 run 状态（run_id 前缀 `evo-` 或 agent 角色 `evolution`），MUST NOT 依赖外部进程扫描。
- `PROJECT_ROOT` 解析后与 `FRAMEWORK_ROOT` 不一致的 daemon MUST NOT 启动自进化检查点（非自托管部署下本能力整体不启用，日志明示一次，不刷屏）。

#### Scenario: 项目自省就绪即启动分析 run

- **WHEN** 某项目的 `.fenix/self_review_state.json` 的 `last_run_at` 晚于该项目水位、其 `.fenix/todo.md` 非空，且当前无 `evo-` run 在途
- **THEN** 该项目入队，检查点立刻启动一次自进化分析 run，run 的输入包含该项目 `.fenix/todo.md` 全文

#### Scenario: 未就绪项目不被分析

- **WHEN** 某项目 `.fenix/self_review_state.json` 缺失、`last_run_at` 不可解析，或 `last_run_at` 不晚于水位
- **THEN** 该项目不入队、不产生 admin 告警，检查点继续处理其他项目

#### Scenario: 多个项目同时就绪合并为一次分析 run

- **WHEN** 检查点在同一轮发现项目 A 与项目 B 都就绪
- **THEN** 只启动一次分析 run，且本次 run 的输入包含 A 与 B 两份 todo.md（MUST NOT 为每个项目各起一个 claude 进程）

#### Scenario: 分析 run 在途时就绪项目排队

- **WHEN** 一个 `evo-` run 正在执行，检查点又发现项目 C 就绪
- **THEN** C 留在队列，本轮不启动第二个分析 run；当前 run 结束后由下一检查点启动

#### Scenario: 非自托管 daemon 不启用自进化

- **WHEN** daemon 的 `PROJECT_ROOT` 解析后不等于 `FRAMEWORK_ROOT`
- **THEN** 检查点不启动任何分析 run，即使被管项目的自省已就绪

### Requirement: 分析 run 的角色、模型链与执行形态

系统 MUST 新增 agent 角色 `evolution`，其 prompt 模板为 `agents/evolution.md`（经 `core/agent_runner/prompt_builder.py` 的 `AGENT_PROMPT_FILES` 映射加载，填充占位符含 todo.md 内容与产物路径）。分析 run MUST 经既有 `AgentRunner._run_claude` 启动，因此超时、轮次上限、token 预算、provider 熔断、run 文件与 token 归账 MUST 全部走既有链路，MUST NOT 另起一套子进程执行路径。

- 模型链 MUST 取 `agents.models.self-review` → 回退 `agents.models.administrator` → 既有 `_get_admin_model` 兜底（与自省 agent 完全同源，「同样使用自省 agent 的 llm provider」）。
- run MUST 在框架主树（`PROJECT_ROOT`）下执行且 **MUST NOT 创建 worktree**（与自省 run 同形态）。
- `run_id` 前缀 MUST 为 `evo-`（形如 `evo-<epoch>`），原始 stream-json 事件 MUST 落 `.fenix/runs/evo-*.jsonl`，可在 Dashboard runs 视图检索到。

#### Scenario: 模型链与自省同源

- **WHEN** 配置含 `agents.models.self-review.provider` 链
- **THEN** 分析 run 使用该链的首个候选（provider baseurl/apikey/model 经既有 `_run_claude` 注入），行为与自省 run 一致

#### Scenario: 自省模型键缺失时回退

- **WHEN** 配置中不存在 `agents.models.self-review`
- **THEN** 分析 run 使用 `agents.models.administrator` 链；两者都不存在时使用既有默认网关兜底，MUST NOT 因缺配置而拒绝启动

#### Scenario: 不创建 worktree

- **WHEN** 分析 run 被派发
- **THEN** 其执行目录为主树 `PROJECT_ROOT`，`.claude/worktrees/` 下 MUST NOT 新增该 run 的 worktree

#### Scenario: run 记录可见

- **WHEN** 分析 run 完成
- **THEN** `.fenix/runs/evo-<epoch>.jsonl` 存在且含 stream-json 事件，token 用量计入既有归账路径

### Requirement: 逐条子代理复核

分析 run MUST 对每个待分析条目派一个 Task 子代理（**一条目一子代理**），子代理的输入 MUST 至少包含该条目在 todo.md 中的原文（标题、影响、证据、调查评估、建议）与其所属项目根路径。

- 子代理 MUST 为只读核查者：MUST NOT 创建 `spec/changes/` 条目、MUST NOT 写入或注册 STATE.md、MUST NOT 修改被审项目与框架仓库的任何文件。
- 同一条目在同一 run 内 MUST NOT 被派发多个子代理。
- **降级**：当 run 的 init 事件工具表不含 Task 工具族时，分析 MUST 降级为同进程串行逐条复核（顺序执行、结论完整度不降），并在 run 日志与契约产物中记录降级标记（如 `degraded: "no-task-tool"`）。降级 MUST NOT 导致整轮失败。

#### Scenario: 每条条目一个子代理

- **WHEN** 待分析集合含 N 条条目（N > 1）
- **THEN** 分析 run 派发 N 个子代理，每条条目恰好一个

#### Scenario: 子代理不落盘

- **WHEN** 子代理完成对某条条目的复核
- **THEN** 框架仓库与被审项目的工作区 MUST 无该子代理产生的文件改动（`spec/changes/`、STATE.md 均不变）

#### Scenario: Task 工具族缺失时降级

- **WHEN** 分析 run 的 init 事件工具表不含 Task 工具族
- **THEN** 复核改为同进程串行执行，全部条目仍产出结论，产物中记录降级原因，run 判成功

### Requirement: 复核判定维度与证据要求

子代理 MUST 独立回源核查（只读日志、源码、STATE.md、git 记录），MUST NOT 直接采信 todo.md 自述的「调查评估」结论。每条条目的结论 MUST 包含三项判定字段与依据：

- `problem_exists`：`yes` / `no` / `partial` —— 自省所述问题是否真实存在且描述准确；
- `suggestion_sound`：`yes` / `no` / `partial` —— 建议是否合理、完整、可落地；
- `worth_spec`：布尔 —— 是否有价值与必要性立项修复；
- `rationale`：结论依据，MUST 引用可核对的具体证据（`文件:行号`、日志时间戳、run id、STATE 条目名等至少一项）。

无法核实的部分 MUST 明示「未核实」，MUST NOT 编造。`analysis_md` MUST 是可独立阅读的 Markdown（含结论、核查过程、证据、与存量 SPEC 的关系），MUST NOT 只复述 todo.md 原文。

#### Scenario: 三项判定与依据齐全

- **WHEN** 子代理完成某条条目复核
- **THEN** 该条目结论含 `problem_exists`、`suggestion_sound`、`worth_spec` 三个字段与至少一项引用具体证据的 `rationale`

#### Scenario: 核实不了写未核实

- **WHEN** 条目所述现象在日志/源码/STATE 中均找不到可核对证据
- **THEN** 结论明示「未核实」并据此给出保守判定（`worth_spec` 不为真），MUST NOT 编造证据

#### Scenario: 回源结论覆盖 todo.md 自述

- **WHEN** todo.md「调查评估」给出的根因与源码实际不符
- **THEN** 结论以回源核查结果为准，并在 `analysis_md` 中说明与 todo.md 自述的差异

### Requirement: 分析产物的 JSON 契约

分析 run 结束 MUST 把结果写入 `.fenix/evolution/out-<run_id>.json`，结构为：

```json
{
  "run_id": "evo-<epoch>",
  "degraded": "no-task-tool | null",
  "items": [
    {
      "project": "<项目名>",
      "date_section": "YYYY-MM-DD",
      "section": "浪费 | 失误 | 可改进",
      "title": "<条目标题，逐字取自 todo.md>",
      "impact": "...", "evidence": "...", "analysis": "...", "suggestion": "...",
      "verdict": {"problem_exists": "yes|no|partial", "suggestion_sound": "yes|no|partial",
                  "worth_spec": true, "rationale": "..."},
      "analysis_md": "...",
      "spec": {"name": "<kebab-case 不含前缀>", "capability": "<kebab-case>",
               "proposal_md": "...", "spec_md": "...", "design_md": "...", "tasks_md": "..."}
    }
  ]
}
```

`spec` 字段仅在 `verdict.worth_spec` 为真时必填；否则 MUST 为 `null`。JSON 解析失败、缺 `items`、`section` 不在三值枚举内、或条目缺 `project`/`date_section`/`title`/`verdict` 任一必填字段时，**整轮 MUST 判失败**：写 admin 告警（WARNING，含 run_id 与原因）、水位不推进、MUST NOT 产生任何条目。产物文件 MUST 在框架读取完成后删除（与既有 `self_review_out-*.json` 的处理方式一致）。

#### Scenario: 合法产物被消费并清理

- **WHEN** run 写出结构完整的 `.fenix/evolution/out-<run_id>.json`
- **THEN** 框架逐条落库，随后删除该产物文件

#### Scenario: 非法产物整轮失败且水位不推进

- **WHEN** 产物不是合法 JSON，或缺 `items`，或某条目缺 `verdict`
- **THEN** 本轮不产生任何条目、不生成任何草稿，写一条 admin WARNING 告警，该项目水位保持原值，下一检查点重试

#### Scenario: worth_spec 为真时 spec 内容必填

- **WHEN** 某条目 `verdict.worth_spec` 为 `true` 但 `spec` 为 `null` 或缺 `proposal_md`/`tasks_md`
- **THEN** 该条目标 `draft_failed` 并记录缺失字段，其余条目照常落地

### Requirement: 增量水位与条目幂等

条目身份键 MUST 为 `id = sha1(f"{project}\x1f{date_section}\x1f{section}\x1f{title}")[:12]`（稳定、可复算、与运行环境无关）。去重的**权威来源** MUST 是 `.fenix/evolution/items.jsonl` 中已存在的 id 集合：凡 id 已存在的条目（无论其状态为 `pending` / `analyzed` / `draft_failed` / `accepted` / `auto_accepted` / `rejected` / `accept_failed`）MUST NOT 再次分析、再次生成草稿。

`.fenix/evolution/state.json` MUST 按项目维护 `last_analyzed_at`（ISO8601 UTC）与 `last_run_id`，仅用作检查点的触发判据；其推进 MUST 仅发生在分析 run 成功落地之后，且 MUST 取本轮 run 启动时的快照时刻（MUST NOT 取落地时刻，避免漏掉 run 执行期间新写入的条目）。

`self_evolution.max_items_per_run` 限制单轮处理条目数：超出上限的条目 MUST 留待下轮（因其 id 尚未入库，下一轮自然被再次选中），MUST NOT 因此把水位推进到「已全部处理」。

`items.jsonl` MUST 对同一 id 只保留一条记录（重复落地 MUST 更新而非追加）。

#### Scenario: 已分析条目不再重复处理

- **WHEN** 某条目昨日已入库（状态 `analyzed`），今日 todo.md 仍包含同一条（标题、日期节、小节一致）
- **THEN** 本轮不为它派子代理、不重复生成草稿，条目不重复入库

#### Scenario: 超出单轮上限的条目留待下轮

- **WHEN** 待分析条目数为 30 而 `max_items_per_run` 为 20
- **THEN** 本轮最多处理 20 条，其余 10 条的 id 未入库，下一轮分析 run 仍会选中它们

#### Scenario: 身份键跨环境稳定

- **WHEN** 用相同的（项目、日期节、小节、标题）四元组计算两次身份键
- **THEN** 两次结果一致（同一 id），且与 todo.md 的渲染顺序、条目在文件中的行号无关

### Requirement: 草稿生成与同源 lint 校验

对 `verdict.worth_spec` 为真且 `spec` 内容齐全的条目，框架 MUST 按 fenix-new 流程把 SPEC 全套写入 `.fenix/evolution/drafts/<id>/`：`proposal.md`、`specs/<capability>/spec.md`、`design.md`、`tasks.md`（含 `## Deliverables` 声明段，path 为具体文件、kind 语义正确）、`.spec.yaml`（`schema: spec-driven` + `created: <YYYY-MM-DD>` + `mode: full`）。

落盘后框架 MUST 执行与 daemon 晋升**同源**的 lint 预检（`sys.path` 指向 `.fenix/`，即 `core.deliverables.lint_declared(draft_dir, project_root)` 与 `lint_tasks_parseable(draft_dir, project_root)`）：

- 无 violation → 条目标 `pending`，草稿保留，等待用户决定；
- 有 violation 或内容缺失 → 条目标 `draft_failed`，**删除草稿目录**（MUST NOT 留下半成品），并把 violation 原文与 agent 原始 spec 内容摘要记入条目记录供人工诊断；MUST NOT 落到 `spec/changes/`、MUST NOT 注册 STATE.md。

`verdict.worth_spec` 为 `false` 的条目 MUST NOT 生成草稿，状态为 `analyzed`。

#### Scenario: 草稿落盘并通过 lint

- **WHEN** 某条目判定需立项，`spec` 内容齐全，同源 lint 输出 `OK`
- **THEN** `.fenix/evolution/drafts/<id>/` 含完整五个文件，条目标 `pending`

#### Scenario: lint 不过不留半成品

- **WHEN** 草稿的 `tasks.md` 声明了目录路径或 gitignored 路径等触发 lint violation
- **THEN** 该草稿目录被删除，条目标 `draft_failed` 并记录 violation 原文，`spec/changes/` 与 STATE.md 均无变化

#### Scenario: 判定不需要立项时不生成草稿

- **WHEN** 某条目 `verdict.worth_spec` 为 `false`
- **THEN** 不创建草稿目录，条目标 `analyzed`，用户侧仅可查看分析结论

### Requirement: 接受路径（人工同意与自动接受共用）

接受 MUST 按以下确定性顺序执行，全程由框架代码完成（MUST NOT 交由 LLM）：

1. 条目状态 MUST ∈ `{pending, accept_failed}`；其它状态 MUST 幂等返回现状（MUST NOT 重复提交或注册）。
2. SPEC 名 MUST 为 `evo-` + agent 给出的 `spec.name`（`^[a-z0-9][a-z0-9-]*$`，非法规格 → 条目标 `draft_failed`）。名称冲突时（`spec/changes/<name>` 已存在、STATE.md 已有同名条目、或 `spec/archive/*-<name>` 已存在）MUST 追加 `-<id 前 6 位>`；仍冲突 → `draft_failed` + 告警。
3. 把草稿复制到 `spec/changes/<name>/`，随后 **仅** `git add spec/changes/<name>/` 并提交（message 形如 `[fenix] spec: <name>`）；MUST NOT 使用 `git add -A` / `git add .`。
4. 提交成功后注册：`StateMachine.add_spec(<name>, {'status': 'drafted', 'priority': 5})`（MUST NOT 写 `start_after`，立即进入调度）。
5. 注册成功后删除暂存草稿目录 `.fenix/evolution/drafts/<id>/`，条目状态置 `accepted`（人工）或 `auto_accepted`（自动），并记录 `spec_name`、`decided_at`、`decided_by`（`manual` / `auto`）。

提交或注册失败时 MUST NOT 产生「已注册但未提交」或「已提交但未注册」的半成品：提交失败 MUST NOT 注册；注册失败 MUST 保留草稿（便于重试）并把条目标 `accept_failed`、写 admin 告警。注册后的 SPEC 走既有流水线（晋升 → 实现 → 验证 → `done` → `pushed`），推送审批门 `gates.require_push_approval` MUST 保持不变。

#### Scenario: 人工同意完成立项全链

- **WHEN** 用户对状态为 `pending` 的条目点击「同意」
- **THEN** 草稿落到 `spec/changes/evo-<slug>/` 并被单独提交，STATE.md 新增 `evo-<slug>` 条目（`status: drafted`, `priority: 5`），暂存草稿删除，条目标 `accepted` 且记录 `spec_name`

#### Scenario: 重名自动加后缀

- **WHEN** 目标 SPEC 名 `evo-xxx` 已存在于 `spec/changes/` 或 STATE.md
- **THEN** 实际落地名为 `evo-xxx-<id 前 6 位>`，且该名字在注册前被再次确认唯一

#### Scenario: 提交失败不注册且可重试

- **WHEN** `git commit` 因 hook 报错等原因失败
- **THEN** STATE.md MUST 无该 SPEC 条目，草稿保留在 `spec/changes/` 或暂存区（二者不并存），条目标 `accept_failed`，写 admin 告警；用户再次点击「同意」可完成注册

#### Scenario: 重复同意幂等

- **WHEN** 对状态已为 `accepted` / `auto_accepted` 的条目再次点击「同意」
- **THEN** 不产生第二次提交与第二次 `add_spec`，返回当前状态

### Requirement: 拒绝路径

拒绝 MUST 仅对状态 ∈ `{pending, draft_failed, accept_failed}` 的条目生效；对 `accepted` / `auto_accepted` / `rejected` 的条目 MUST 返回错误且不改动任何状态与文件。

拒绝时 MUST 删除 `.fenix/evolution/drafts/<id>/`，并把条目标 `rejected` 且记录 `decided_at`。删除前 MUST 校验解析后的目标路径位于该条目自己的草稿目录内（符号链接与非本条目路径一律拒绝删除并报错）。

#### Scenario: 拒绝删除草稿并落状态

- **WHEN** 用户对 `pending` 条目点击「拒绝」
- **THEN** `.fenix/evolution/drafts/<id>/` 被删除，条目标 `rejected`，`spec/changes/` 与 STATE.md 无任何变化

#### Scenario: 已接受条目不可拒绝

- **WHEN** 对状态为 `accepted` 的条目发起拒绝
- **THEN** 返回错误，草稿与 STATE.md 均不变

#### Scenario: 越界路径不被删除

- **WHEN** 草稿目录被替换为指向外部的符号链接
- **THEN** 拒绝操作报错并 MUST NOT 删除该目标

### Requirement: 自动接受开关

当 `self_evolution.auto_accept` 为真时，框架 MUST 在分析 run 落地完成后（同一检查点内）对本轮全部 `pending` 条目逐个走「接受路径」（`decided_by: auto`，状态 `auto_accepted`），MUST NOT 要求任何前端交互。单个条目的接受失败 MUST NOT 影响其余条目（逐条独立、失败者置 `accept_failed` 并保留草稿）。自动接受 MUST NOT 作用于 `analyzed` 与 `draft_failed` 条目，MUST NOT 改动已决定条目。开关为假时（含配置缺失）MUST 保持 `pending` 等待用户决定。

#### Scenario: 开关打开时自动全部接受

- **WHEN** 配置 `self_evolution.auto_accept: true`，一次分析 run 落地了 3 条 `pending` 条目
- **THEN** 3 条自动完成落地与注册，状态均为 `auto_accepted`，无需任何用户点击

#### Scenario: 开关关闭时保持待决策

- **WHEN** 配置中无 `self_evolution.auto_accept`（或缺省 `false`）
- **THEN** 分析 run 落地后条目标保持 `pending`，等待用户在设置页点击「同意」

#### Scenario: 单条失败不影响其余

- **WHEN** 自动接受过程中某条因名称冲突或提交失败而失败
- **THEN** 该条置 `accept_failed` 并保留草稿、写告警，其余条目照常完成接受

### Requirement: self_evolution 配置节

系统 MUST 支持 `self_evolution` 配置节，含 `auto_accept`（布尔，缺省 `false`）与 `max_items_per_run`（正整数，缺省 `20`，上界 `200`）。节、键缺失或值非法（非布尔 / 非正整数 / 大于上界）时 MUST 回退缺省值，MUST NOT 抛异常、MUST NOT 使 daemon 启动失败。配置 MUST 走既有 30s 配置热更新，改动 MUST 在下一个检查点生效而无需重启 daemon。

两键为**全局（用户级）键**：Dashboard 配置写入 API 对项目级作用域提交 `self_evolution` MUST 返回 400 与可读错误（引导用户到用户级作用域修改）；读取侧的有效值取合并后配置（与其它配置键一致），因此正常路径下不会产生项目级覆盖。

#### Scenario: 缺省值生效

- **WHEN** 配置文件中不存在 `self_evolution` 节
- **THEN** 框架按 `auto_accept: false`、`max_items_per_run: 20` 运行（即：只生成、不自动接受）

#### Scenario: 非法值回退不中断

- **WHEN** `auto_accept` 被写成字符串、或 `max_items_per_run` 被写成 `0` / 负数 / 非数字 / 大于 200
- **THEN** 对应键回退缺省值，daemon 不抛异常、主循环不中断

#### Scenario: 热更新立即生效

- **WHEN** 用户在运行中的 daemon 上把 `auto_accept` 改为 `true`
- **THEN** 下一个检查点起，新落地的 `pending` 条目被自动接受，无需重启 daemon

#### Scenario: 项目级写入被拒

- **WHEN** 以项目级作用域向配置 API 提交含 `self_evolution` 的配置
- **THEN** 返回 400 与可读错误，项目级配置文件 MUST 未被写入该键

### Requirement: 失败、降级与可观测性

自进化链路的任何环节 MUST NOT 抛异常中断 daemon 主循环（检查点整体 try/except 包裹并记 ERROR 日志）。分析 run 失败（非零退出、超时、产物文件缺失、JSON 非法）MUST 写一条 admin 告警（WARNING 级，含 run_id 与原因），且该项目水位 MUST NOT 推进（下一检查点自动重试）。降级（Task 工具族缺失）MUST 在 run 日志与契约产物中留痕。每轮落地结果（就绪项目、条目数、草稿数、接受数、失败数）MUST 记 INFO 日志。

#### Scenario: 分析 run 失败告警且水位不推进

- **WHEN** 分析 run 非零退出或未写出契约产物
- **THEN** 产生一条 WARNING 级 admin 告警（含 run_id），项目水位保持原值，下一检查点会再次启动分析

#### Scenario: 异常不中断主循环

- **WHEN** 检查点内部任一环节抛出异常（如 registry 读取失败、items.jsonl 写盘失败）
- **THEN** 异常被捕获并记 ERROR，daemon 主循环继续运行，其它定时任务不受影响

#### Scenario: 每轮结果可观测

- **WHEN** 一次分析 run 成功落地
- **THEN** 日志包含本轮处理的条目数、生成草稿数、接受数与失败数
