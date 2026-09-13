# add-spec-review-gate — SPEC 方案评审门禁（draft → ready 之间的 reviewing 状态）

## Why

当前 SPEC 从 `drafted` 晋升 `ready` 只做机械校验（软化 + 声明 lint + tasks 可解析性 lint），没有任何环节评估**方案本身是否成立**：能否达成 proposal 声明的目的、任务拆分是否留有实现漏洞、改动是否会波及其他场景。机械 lint 只管「声明路径长什么样」，管不了「这条路走不走得通」。后果是方案层面的方向性错误要等到实现完成、验证流水线跑完才暴露，而那时已烧掉一整轮实现 + 验证预算，且框架只能给出一堆场景失败证据，无法告诉人「根因是方案当初就想错了」。

这一问题在自进化链路（`self_evolution`）上被放大：框架自动从自省报告里提炼需求、批量产出 `evo-*` SPEC 并直接进入自动实现。**这些 SPEC 没有人为方案背书**，一旦方向错了就是无人察觉的批量错误。

需要一道方案评审门禁：在 `drafted` 与 `ready` 之间插入评审环节，由一个独立 Agent 阅读 SPEC 三文档做方案级判断，把方向性风险挡在实现之前，把关成本从「一轮实现 + 一轮验证」降到「一次单轮只读评审」。

## What Changes

- **新增状态 `reviewing`（第 11 个状态）**：状态机增加 `reviewing`，新增合法转移边 `drafted → reviewing`、`reviewing → ready`、`reviewing → blocked`、`blocked → reviewing`（人工重新评审）。`blocked → ready`（人工担责放行）保留。
- **新增 Agent 角色 `spec-review`**：单轮只读**方案评审者**。仅在没有内容物需要隔离这个意义上「只读」——它被授予 `spec/changes/<spec>/` 目录的写权限用于就地修补可修补漏洞，其余路径只读。运行范式完全对齐既有 `dispute-judge`：**不建 worktree、cwd = 主树**（评审官需要读的 SPEC 文档、`spec/archive/` 的已完成 SPEC、`.fenix/runs/` 流转录本来就在主树里）。
- **评审评估三个维度**：能否达成目的（`goal-fit`）、是否存在漏洞（`hole`）、是否会因该功能导致其他场景出问题（`regression`）。复杂方案可查阅 `spec/archive/` 下已完成 SPEC 与 `.fenix/runs/` 历史流转录辅助判断。
- **三种评审结论**：`approved`（方案可行）→ `ready`；`repaired`（评审官已就地修补可修补漏洞）→ `ready`；`rejected`（存在方向性风险/致命漏洞）→ `blocked` 交人工裁决，error 前缀 `spec-review-rejected:`。
- **评审故障与否决严格区分**：run 失败/超时/结果文件缺失/JSON 非法/status 越白名单/mtime 陈旧，一律**不计否决**，重试上限 2 次；耗尽后转 `blocked`，error 前缀 `spec-review-incomplete:`。两类 blocked 在 Dashboard 上一眼可分。
- **默认全量评审 + 跳过白名单**：仅当四项**全部命中**时跳过评审直通 `ready`——`mode == fast-track` 且 能力数 ≤ 1 且 交付物声明条目 ≤ 3 且 **非 `evo-` 前缀**。`evo-` 前缀是硬否决项：即使命中前三项也必须评审。
- **新增配置键 `gates.spec_review_mode`**（枚举 `auto` 默认 / `never`）与 **`agents.models.spec-review`**（模型分配），均配 Dashboard 界面。
- **评审 run 的主树写入边界校验**：派发前对 `spec/changes/<spec>/` 与工作区脏文件记录哈希快照，收工后校验 `repairs` 路径合法性 + 越界改动检测 + `status` 与改动的一致性。
- **人工恢复通道**：`blocked → reviewing`（重新评审）仅对 error 前缀为 `spec-review-*` 的 blocked SPEC 开放；`blocked → ready`（人工担责放行）保留。Dashboard 与 CLI 各配入口。
- 同步更新文档：生命周期（11 状态与转移表）、核心概念（Agent 角色表）、治理规则、配置参考、文件与数据地图。

### 非目标

- **不替代验证流水线**：评审只判断「方案是否成立」，不判断「实现是否正确」。验证闭环职责不变。
- **不做评审结果的分级重试策略**：`rejected` 一律进 blocked 交人工，不引入「部分采纳」的中间态。
- **不引入评审预算键**：重试上限（2）与跳过白名单判据先硬编码，`gates.spec_review_mode: never` 作为整体逃生门。

## Capabilities

### New Capabilities

- `spec-review-agent`：评审 Agent 本体——`agents/spec-review.md` 提示词契约、`AGENT_PROMPT_FILES` 白名单注册、`run_spec_review` runner 入口、run_id 前缀与两处前缀元组同源、模型路由、结果硬门接入、输出契约（status/findings/repairs/history_consulted）、主树直改的写入边界校验（快照 + 越界检测 + 一致性校验）。
- `spec-review-gate`：`reviewing` 状态与转移边、`VALID_TRANSITIONS` 扩展、`gates.spec_review_mode` 配置键（校验/缺省/热更新/受管键白名单）、跳过白名单判据（含 `evo-` 硬否决）、晋升链（`promote_drafted`）接入与三条人工通道全覆盖、事件总线与调度器接入（`_status_to_event` / 处理器表 / `check_scheduling_deadlines` / `_recover_one`）、`reviewing` 中断态回退、并发闸门。
- `spec-review-recovery`：评审结论的机械消费（三种 status 的收口动作）、评审故障的重试与 `spec-review-incomplete:` 标记、评审否决的 `spec-review-rejected:` 标记、`blocked → reviewing` 与 `blocked → ready` 双恢复路径、重新评审入口的开放条件（error 前缀限定）、冻结态保护、Dashboard 与 CLI 入口。

### Modified Capabilities

（无——`spec/specs/` 活跃目录为空。本改动扩展的 `draft-promotion-gate` / `manual-spec-promotion` 两个能力仍位于 `spec/changes/add-draft-promotion-gate/specs/`，尚未归档，不构成对活跃能力的修改。）

## Impact

### 状态机与调度

- `core/state_machine.py`：`SpecStatus` 增 `REVIEWING`；`ALL` 列表；`VALID_TRANSITIONS` 三处（`DRAFTED` 增 `REVIEWING`、新增 `REVIEWING` 项、`BLOCKED` 增 `REVIEWING`）；`reviewer_run` 字段纳入序列化白名单；内部字段 `_review_attempts`。
- `core/event_bus.py`：`_status_to_event` 增 `"reviewing": "spec_reviewing"`；`_recover_one` 增 `reviewing` 分支；中断态回退集纳入 `reviewing`。
- `core/pm_engine/engine.py`：处理器表增 `"spec_reviewing": self._on_spec_reviewing`；新增 `_on_spec_reviewing`；`check_scheduling_deadlines` 增 `reviewing` 分支；`_on_spec_drafted` 收尾由「transition ready」改为按分流选择 ready / reviewing。
- `core/pm_engine/promotion.py`：`promote_drafted` 返回结构扩展分流结论；跳过白名单判定函数落位于此（三条人工通道共用）。

### 评审 Agent

- `agents/spec-review.md`：新增提示词文件。
- `core/agent_runner/prompt_builder.py`：`AGENT_PROMPT_FILES` 增 `spec-review`；结果路径函数（`.fenix/spec-review/<spec>/.fenix-run-result.json`）；status 白名单。
- `core/agent_runner/runner.py`：新增 `run_spec_review()`（对齐 `run_dispute_judge` 范式）；结果硬门 `_check_agent_result_artifact` 接入；写入边界快照与越界检测辅助。
- `core/agent_runner/run_files.py` 与 `core/admin_monitor.py`：`_RUN_PREFIXES` 两处同源增 `spec-review-`。
- `.fenix/spec-review/<spec>/`：新运行产物目录（运行时，非交付物）。

### 配置与界面

- `core/config.py`：`gates.spec_review_mode` 校验与 getter（缺省 `auto`）；`agents.models.spec-review` 纳入既有校验结构。
- `core/dashboard/data.py`：受管键白名单扩展 `gates.spec_review_mode`（读侧 sources 标注 + 写侧提取两处）；新增重新评审动作构造函数。
- `core/dashboard/server.py`：重新评审 API 路由。
- `core/dashboard/static/src/`：设置页审批页签新增评审模式单选；提示词页签与模型分配补 `spec-review`；项目页 spec 列表新增 `reviewing` 状态展示与「重新评审」入口；状态色板新增 `reviewing`。
- `bin/fenix_cli.py`：新增 `review <spec> [--project <path>]` 子命令。

### 文档

- `docs/help/03-lifecycle.md`（11 状态、转移表、mermaid）、`docs/help/02-concepts.md`（Agent 角色表，并修正「七类」的过时计数）、`docs/help/06-governance.md`（评审门禁、白名单、恢复路径）、`docs/help/09-config.md`（新配置键）、`docs/help/10-artifacts.md`（`.fenix/spec-review/` 目录）。

### 依赖与风险

- 依赖 `add-draft-promotion-gate` 已落地的共享晋升函数 `core/pm_engine/promotion.py:promote_drafted`（三条人工通道共用点）——本改动的分流判定挂在该函数上，是其自然延伸。
- 依赖 `dispute-judge` 已落地的「不建 worktree、cwd=主树」判官范式（`core/agent_runner/runner.py:run_dispute_judge`）。
- **BREAKING（内部）**：`VALID_TRANSITIONS` 新增转移边与状态，所有对状态全集做穷举的代码路径（Dashboard 状态色板、文档、任何 `SpecStatus.ALL` 消费点）需同步扩展；`drafted` 不再必然直通 `ready`，任何假设「drafted 的下一步就是 ready」的逻辑需复核。
