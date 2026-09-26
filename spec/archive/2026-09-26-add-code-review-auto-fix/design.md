# Design: add-code-review-auto-fix

## Context

`add-code-review-agent-and-quality-tab` 已交付周期性仓库级代码审查：daemon 每日自省时点派 `code-review` agent（**只读审查，MUST NOT 改码**）→ 问题入台账 `.fenix/code-review/items.jsonl`（`status: open`）→ 项目页「代码审查」分面呈现 → 人工勾选走 `generate_fix_spec` 生成 `fix-cr-*` SPEC 进 PM 流水线。本仓现状：台账 428 条、`open` 数百条，人工分诊不可扩展。

同时 `add-test-regression-tab` 已交付独立回归车道：`verify.yaml` 的 `regression` 段声明全量回归命令与 JUnit XML 产物 → `core/regression.run_regression` 执行原语（主机级锁互斥 + 进程组杀树 + XML 宽松解析 + 快照落盘）→ 手动/周期两路触发。`verify.yaml` 缺失 `regression` 段时，既有 AI 契约起草通道（`verify_contract_missing` 信号 → administrator agent 按 `agents/administrator.md` 的「regression 段起草」手册生成并自证落位）可补齐。

本设计新增第三条与二者正交的车道：**自动修复**——把台账 `open` 条目按 `batch_size`（缺省 20）分批，每批派一个**可改码**的 `code-fix` agent 在独立 worktree 内修复并提交，框架在该 worktree 上跑**全量回归**，通过才 merge-back 主树并把该批条目置 `resolved`。

## Goals

- 审查产出的 `open` 条目**自动**进入修复通道，无需人工逐条勾选。
- 每批（缺省 20 条）修复后**必过全量回归**才合回主树，批次粒度限制单次改动面、抑制同步风险。
- 两路激活：审查 run 收尾同步触发 + 30 分钟 full scan 周期兜底。
- 开关关闭 / 已有 `code-fix` 在跑 / 无 `open` 条目 → 不重复激活（幂等）。
- 项目页「代码审查」页签呈现自动修复进度（已处理数 / 总数 / 进度条）。

## Non-Goals

- **不**替换既有「生成修复 SPEC」人工通道（`generate_fix_spec`）——两者并存，自动修复走独立车道。
- **不**改 `code-review` agent 的只读语义与既有审查车道行为。
- **不**为自动修复新增回归执行原语——复用 `core.regression.run_regression` 与 `verify.yaml regression` 契约。
- **不**引入多分支批量 merge（既有 `merge_back_from_branch` 只接单分支；本设计每批一次单分支合并）。
- **不**做 token/预算硬上限（用户明确「不设上限」，一次激活处理到无 `open` 条目为止）；批次之间有全量回归作天然节流。

## Decisions

### D1：新增一等公民 agent 类型 `code-fix`，模型链复用 code-review 的 LLM 配置（用户已确认）

`code-fix` 与 `code-review` 同形，注册四处（缺任一即退化）：

- `core/agent_runner/prompt_builder.py` 的 `AGENT_PROMPT_FILES` MUST 含 `"code-fix": "code-fix.md"`；框架根 `agents/code-fix.md` MUST 存在。
- `core/agent_runner/run_files.py` 的 `RUN_ID_AGENT_PREFIXES` MUST 含 `("code-fix-", "code-fix")`（否则时间线退化为泛型 `agent`）。
- `core/config.py` 的 `KNOWN_AGENT_TYPES` MUST 含 `"code-fix"`（否则 `agents.models.code-fix` 被静默跳过、回退默认网关）。
- `.fenix/config.template.yaml` 的 `agents.models` MUST 含 `code-fix` 示例（模板入库；`.fenix/config.yaml` 为 gitignored 运行时文件，不进交付声明）。

**模型链（用户原话「使用 code-review agent 相同的 llm 配置」）**：`agents.models.code-fix` 分配优先 → 回退 `agents.models.code-review` → 回退 `agents.models.self-review` → 回退 `agents.models.administrator` → 再回退默认网关。**默认即与 code-review 同源**（本仓未显式配 `code-fix`/`code-review` → 二者都落到 `self-review`）；显式配 `code-fix` 可独立覆盖。

**理由**：与 code-review 并列的一等公民，保证 run 时间线/模型配置/dashboard 归属一致；模型链前置 `code-review` 级使「相同 LLM 配置」是缺省行为而非巧合。

### D2：框架编排、一批一次 agent run（用户已确认）

批次循环由**框架驱动**，不在单个长 agent run 内：

1. daemon 编排器选台账 `open` 条目中最早的 `batch_size` 条为一批；
2. 派一次 `code-fix` run（独立 worktree，`spec_name="code-review-fix"`，run_id `code-fix-<epoch>`）修复并提交；
3. run 收尾后框架在**该 worktree** 上跑全量回归；
4. 回归通过 → merge-back 主树 → 该批条目置 `resolved` → 编排器推进/投递下一批；
5. 回归不通过 → **自动重试一次**（见 D6）→ 仍不过 → 丢弃该批（不合回），worktree 保留待人工，条目保持 `open`。

**理由**：每批独立可恢复（daemon 重启后由 30 分钟 full scan 兜底续做）、失败隔离（一批失败不影响后续条目状态一致性）、进度可观测（done/total 按批推进）。单个长 run 断线即全丢且合回仍须框架完成。

**不做 `_execute_agent` 路径**：与 `code-review`/`regression` 同理由——自动修复是运维车道，**不占 spec 维度预算、不计入每日 agent run 计数**。`run_code_fix` 自行经 `worktree_manager.create` 建 worktree、`runner._run_claude` 执行。

### D3：worktree 隔离与合回

- worktree 经 `worktree_manager.create(spec_name="code-review-fix", agent_type="code-fix")` 创建；每批**新建**一个 worktree（从当前 HEAD 起），批成功合回后移除。
- 失败重试（D6）在**同一** worktree 内续做（agent 看到上一轮回归失败输出）。
- 合回经 `worktree_manager.merge_back(wt_path)`（已持 `_main_tree_lock`、含 merge-tree 预演 / WIP 重叠闸 / spec 目录在飞闸）。分支名形如 `fenix/code-review-fix-<ts>`。
- 回归**在 worktree 内**执行（改动在 worktree，主树不含）。`verify.yaml` 已入库（`git ls-files` 命中 `.fenix/verify.yaml`），worktree 内可见；`regression.output` 相对路径在 worktree 内落盘。
- **批收尾 MUST 释放 worktree**：成功合回后 MUST 调 `worktree_manager.cleanup(wt_path, success=True)`。`create()` 在 `_spec_locks` 登记 `"code-review-fix:code-fix"`，**只有 `cleanup()` 会释放该锁**（`core/worktree_manager/lifecycle.py:131` 的重复判定 / `:498-502` 的 finally 释放）。漏掉 cleanup → 第 2 批 `create()` 直接返回 `None`（"Worktree already active for code-review-fix:code-fix"），车道在首批成功后即死。
- 失败批（D6 第二次回归仍失败）MUST NOT 调 `cleanup()`（保留现场），其条目集合经 D6 的跳过机制排除，不阻塞后续批次；`release_failed_batch` 不接 UI，故 MUST 同时在 `.fenix/todo.md` 登记待人工清理。
- `create()` 返回 `None`（锁占用 / git 失败）→ 本次不派 run、不合回，进度 `phase="failed"`、`reason="worktree_create_failed"`，条目保持 `open`，下一轮 full scan 重试。

**理由**：worktree 隔离是既有全 agent 的硬约束（主树只读 hook `block-main-tree-write.py` 拦截直接写主树）；每批新 worktree 使合回后的下一批从干净 HEAD 增量修复，避免累积。

### D4：两路激活 + 幂等（用户已确认「审查收尾 + 30min 兜底」）

单一入口 `CodeFixOrchestrator.checkpoint()`，两处调用：

- **审查 run 收尾**：`run_code_review` 成功收尾、且本轮 `upsert_findings` 产生了 `open` 条目时，经 `getattr(runner, "_code_fix_orchestrator", None)` 触发一次 `checkpoint()`（手动触发与周期触发的审查 run 都经此，勿在调用点重复接线）。
- **30 分钟 full scan 兜底**：`event_bus._run_full_scan_body()` 末尾调用 `checkpoint()`（经可选的 `self.code_fix_orchestrator` 引用，未装配时静默跳过）。

**守卫链（幂等）**：`admin.code_review_fix.enabled` 为 false → `disabled`；已有 `code-fix` run 在跑（单飞锁 `_in_flight` 或 `_running_agents` 含 `code-fix-` 前缀）→ `already_running`；台账无 `open` 条目 → `no_open_items`；回归契约不可用 → 见 D5。任一命中即不投递。

**自驱动链**：批 worker 收尾后经 executor 再次投递 `checkpoint()`（而非递归直调，避免阻塞/嵌套），处理下一批；30 分钟 full scan 是链断裂（进程重启、异常）后的兜底。

**理由**：审查收尾触发保证「审查结束即启动」的时延；full scan 兜底保证重启/异常后自动续做；幂等守卫使两路并发安全（同一时刻至多一个 `code-fix` run）。

### D5：回归契约缺失 → 复用 AI 起草通道 + fail-closed（用户已确认）

`checkpoint()` 选批后、派 run 前，经 `load_verify_contract` 检查 `regression` 段：

- 有有效 `regression` 段 → 正常进入批次；
- **契约整体缺失**（`load_verify_contract` 返回 `None`）→ 经 `AdminStore.append` 发 `verify_contract_missing` 信号（administrator 按手册起草**完整契约**，含 regression 段）；
- **契约有效但仅缺 regression 段**（`contract.regression is None`，本仓现状）→ 发 `verify_regression_missing` 信号（administrator **仅补段**，MUST NOT 动 prepare/serve/ready）。分流口径 MUST 对齐既有 `core/dashboard/routes/regression_routes.py:_api_regression_autodraft_post`（:195-236 的 `verify_contract_missing if contract is None else verify_regression_missing`）与 `core/admin_monitor.py:214-216` 的既有区分——**用错信号会令 administrator 重写一份有效且在服务的 prepare/serve/ready**（回归风险），而两信号均已在 `admin_monitor` 的 `STORED_SIGNAL_TYPES`/severity 表中（同 major），切换零成本。payload 形态对齐既有 `_write_verify_contract_missing`（`signal_type`/`spec`/`severity:"major"`/`description`/`evidence`/`recommended_action`）。
- 两路信号后本次均 **fail-closed**：不派批、不合回，进度 `phase=blocked` 记原因（`reason="regression_contract_missing"` / `"regression_section_missing"`），下一轮 full scan 再试。

**理由**：无回归即无法证明「未引入新缺陷」，合回违反本需求的唯一铁律；fail-closed + 起草通道符合用户「生成失败则 fail-closed 并记录原因」的指令。不重复发信号由既有信号节流（`_throttled`）承担。

### D6：回归失败 → 自动重试一次，仍失败再丢弃（用户已确认）

批 worker 内，首次全量回归 `status != passed`：

- 记录失败输出，**在同一 worktree 内**再派一次 `code-fix` run（prompt 注入失败用例摘要），令 agent 修复被引入的回归；
- 第二次回归 `passed` → 正常合回；仍非 `passed` → 丢弃该批：**不合回**、删除 worktree（或按 D3 保留待人工——见下），条目保持 `open`，进度 `phase=failed` 记原因。

**worktree 保留策略**：第二次失败时**保留** worktree 并写告警信号（`code_fix_regression_failed`，major，附 worktree 路径与失败用例），供人工排查后决定是否手工合回或丢弃；30 分钟 full scan 的下一轮会对同一批条目重新选批（若尚未被人工处理）——为避免与保留 worktree 冲突，`checkpoint()` 在存在未清理的失败 worktree 时对**该批条目集合**跳过（避免重复派发同一批）。

**理由**：一次自动重试覆盖「agent 修复引入的轻微回归」这一高频形态；仍失败说明是难例，交人工比无限重试更省。

### D7：条目终态复用 `resolved`（用户已确认）

批合回成功后，框架按 `item_id` 精确把该批条目置 `resolved`。新增内部函数 `mark_resolved(project_root, item_ids)`（形态对齐既有 `_mark_in_spec`；`set_item_status` 仅允许人工 `open`/`ignored`，不适用）。不新增 `fixed` 状态，不改状态机与下游读侧。

**理由**：`resolved` 的既有语义即「问题已消失」；自动修复的条目在合回后确实不再存在，与全仓快照核销的终态一致。区分来源可由 `resolution` 字段承载（可选，见 tasks）。

### D8：进度上报 `{running, phase, total, done, current, batch_no}`

落盘 `.fenix/code-review/fix-progress.json`（单文件覆盖式，与 `.fenix/regression/last-run.json` 同型），由编排器每步刷新：

- `total`：**本次激活链**开始时的 `open` 条目总数（链内不变）。「激活链」由自驱动再投递串联（D4），链身份 MUST 持久化在进度文件的 `activation_id` 字段：`checkpoint()` 读到进度文件 `running=true` 且 `activation_id` 未变 → 视为同一条链，MUST NOT 重算 `total`；链终止（`no_open_items` / `disabled` / 人工复位）后的下一次激活 MUST 生成新 `activation_id` 并重算 `total`。否则每批收尾复位单飞后再投递，`total` 会被重置为**已缩小**的 `open` 数，前端出现「已处理 0/40」的倒退（与「激活期间不变的快照」自相矛盾）。
- `done`：已合回主树并**实际置 `resolved`** 的条目累计数（= 各批 `mark_resolved` 命中数之和），MUST NOT 以批条数计——`skipped` 条目与未命中 `item_id` 不计入。
- `current`：当前批正在处理的条目/阶段描述（如「第 2 批修复中（20/60 条）」）。
- `phase`：`selecting` / `fixing` / `regressing` / `retrying` / `merging` / `blocked` / `failed` / `idle`。
- `running`：当前是否有未收尾的激活（编排器判据：`_in_flight` 或存在 `code-fix-` 在飞 run）。

只读 API：`GET /api/code-review/fix-progress`（新增于既有 `code_review_routes.py`）。项目页「代码审查」页签复用既有 `Progress percent={done/total*100}` 形态呈现「已处理 done/total 条 · 当前：current」。

**理由**：`{total,done,current}` 是本仓两条既有车道（verify、code-review）的通用进度范式，前端呈现与轮询逻辑可零学习复用。

### D9：配置键群 `admin.code_review_fix.*`（用户已确认键名）

- `admin.code_review_fix.enabled`（缺省 `false`，严格 bool）：总开关。关闭 = 全链路零动作（不选批、不派 run、不写进度）。
- `admin.code_review_fix.batch_size`（缺省 `20`，正整数，非法回退 20）：每批条目数。

读取器 `ConfigLoader.get_code_review_fix_config(config)`（形态对齐 `get_code_review_config`：段缺失/非法回退缺省）。Dashboard 受管键接线**逐条对齐既有 `admin.code_review` 的落点**（`_SOURCE_KEYS` / `_managed_key_sources` / `_DEFAULT_CODE_REVIEW_FIX` 缺省回显 / `read_config`+`read_effective_config` / `_deep_merge_managed` / `write_config` 前置校验 / `_SYNC_PAGE_KEYS`）+ 前端 `ConfigData` 类型 + `QualityPanel` 表单 + `.fenix/config.template.yaml` + `docs/help/09-config.md` 映射表。

**UI 落点**：设置页「质量」页签，在「周期性代码审查」开关**下方**新增一卡片「自动修复代码问题」：`enabled` 开关（`data-testid="code-review-fix-enabled-switch"`）+ `batch_size` 数值输入（`InputNumber`，合法值 1–1000）。

**理由**：用户点名「下面增加开关」且批大小要可配（用户确认做配置项）；项目约束「新增配置项必须带 Dashboard UI」（多处历史 spec 印证）在此以完整接线兑现。

### D10：回归执行的主机级锁锚定主树

`core.regression.run_regression` 新增可选参数 `lock_root=None`（缺省回落 `project_root`，零迁移）：code-fix 调用时传**主树根**，使 worktree 内回归与主树/其它 worktree 的回归共用同一把主机级锁（`.fenix/full-suite.lock`），串行化整套全量测试。

调用形态 MUST 能同时表达「执行根 = worktree、锁根 = 主树」：`run_regression(project_root=<worktree>, lock_root=<main>)`。`core/agent_runner/maintenance_runs.py` 的门面 `run_regression(runner, spec, reason)` 以 `runner.project_root`（= main 树）为执行根，**无法表达 worktree 执行根**——门面 MUST 增加可选 `project_root`（缺省 `runner.project_root`，既有调用点零迁移）并与 `lock_root` 一并透传到 `core.regression.run_and_write_regression`。注意快照（`.fenix/regression/last-run.json` / `run-<id>.json`）随 `project_root` 落盘：worktree 内回归的快照落在 worktree（门禁用途），MUST NOT 依赖其出现在主树「测试回归」分面——分面仍以主树快照为准。

**理由**：worktree 的 `.fenix` 是独立目录（仅 `verify.yaml` 入库），锁若锚定 worktree 则与主树锁不同路径 → 两套全量测试并行（CPU/磁盘/端口互扰，`core/regression.py` 模块注释点名的既有风险）。锚定主树恢复互斥语义。

## Risks

- **[R1] 回归命令副作用**：code-fix 在 worktree 内执行项目声明的 `regression.cmd`，可能污染 worktree（生成产物）。缓解：worktree 用完即弃（每批新建）；命令幂等性由 `add-test-regression-tab` 既有文档约束承担。
- **[R2] 全量回归时长 × 批次数**：数百条 `open` × 每批一次全量回归，总时长可观。缓解：批次粒度即节流阀（`batch_size` 可调大）；用户已确认不设上限。
- **[R3] worktree 依赖供给**：`worktree_manager.create` 的 node_modules 供给是 best-effort；若 `regression.cmd` 依赖构建产物（如前端 `dist`），worktree 内可能缺。缓解：code-fix 提示词要求 agent 修复后自行确保构建可运行；`regression.cmd` 可自带构建（与 `bin/run_full_suite.py` 的用法一致）。
- **[R4] 合回闸门误拦**：worktree 的 `merge_back` 会走 `_wip_overlap_gate` / `_check_spec_dir_inflight` 等闸门；若主树存在未提交 WIP 与分支重叠，合并会被阻塞。缓解：复用既有 merge 失败分类与告警（不绕过闸门），失败记 `phase=failed` 交人工。
- **[R5] 失败 worktree 累积**：D6 保留失败 worktree 会占用磁盘（含 node_modules）。缓解：告警信号提示人工清理；`.fenix/todo.md` 登记。

## 兼容性

- `admin.code_review_fix.enabled` 缺省 false → 全链路零动作，旧配置零迁移。
- 无 `regression` 段项目 → fail-closed 不合回 + 起草通道，不报错刷屏。
- `run_regression` 新增参数缺省回落，既有调用点（admin_monitor checkpoint / fenixd 信号消费 / maintenance_runs.run_regression）语义逐字不变。
- `code-fix` 新 agent 类型不改变既有任何 agent 的行为；不登记 `agents.models.code-fix` 时模型链回退行为明确（D1）。

## 契约要点（实现者必读）

- **不占 spec 维度预算**：`code-fix` 与 `code-review`/`regression` 同属运维车道，MUST NOT 走 `_execute_agent`（不经 spec 预算/每日计数）。run_id 前缀 `code-fix-<epoch>`。
- **产物硬门**：agent MUST 每修完一条问题向框架注入的绝对路径 out 文件追加一行（`{item_id, status, file}`）；框架据此算批内 `done`，并对「run exit 0 但 out 文件缺失/零有效行」判失败（对齐 code-review 的 `_check_repo_code_review_artifact` 形态）。
- **绝不空集合回（两种形态）**：(a) 批内零有效产物行 → 不合回、不置 `resolved`、记失败（防「空跑=成功」白洗）；(b) **批内零有效修复**（产物行全部为 `status: skipped`，或 worktree 分支相对创建点无任何提交）→ 同样 MUST NOT 合回、MUST NOT 置 `resolved`，进度 `phase="failed"`、`reason="no_effective_fix"`。形态 (b) 是本设计的真实白洗口：`merge_back` 对「分支已是 HEAD 祖先」**返回成功**（`core/worktree_manager/mergeback.py:37-45` 幂等语义），若只守 (a)，一个把 20 条全判 `skipped` 的 run 会以「零改动分支合并成功 + 回归必过」把 20 条问题置 `resolved`（D7 语义=「问题已消失」），台账从此永久少报这些仍然存在的缺陷（复现时 `upsert_findings` MUST NOT 覆盖 `status`，条目永不复原）。
- **`skipped` 条目的终态**：`skipped` = 未修复，MUST 保持 `open`（或人工置 `ignored`），MUST NOT 由自动通道置 `resolved`。
- **`resolved` 只能由合回成功驱动**：回归未通过或未合回时 MUST NOT 置该批条目 `resolved`。
