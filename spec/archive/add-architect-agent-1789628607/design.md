# Design: add-architect-agent

## Context

架构师是第 10 类 agent 角色，与「自省 Agent」同周期触发但数据源不同：自省读运行期信号（转录/告警/run 统计/git 提交），架构师读**代码**。二者产出汇入同一建议体系（`todo.md`）。新增角色涉及多处**必须同步的注册表**，漏一处会导致 agent 被当作未知类型静默失效。

关键现状（已核实）：
- `core/config.py` 的 `KNOWN_AGENT_TYPES`（9 角色）——未知键只记 ERROR 并跳过校验；
- `core/agent_runner/runner.py` 的 `AGENT_TYPE_TO_ROLE`；
- `core/agent_runner/prompt_builder.py` 的 `AGENT_PROMPT_FILES`（缺失即 raise）；
- `core/agent_runner/run_files.py` 的 `RUN_ID_AGENT_PREFIXES`（run_id 前缀 → agent_type）；
- 前端 `AgentModelPanel.tsx` 的 `AGENT_ROLES`（与后端白名单「严格一致，勿增删」）；
- 自省调度：`core/self_review.py` 的 `SelfReviewScheduler.check_and_run` 与 `self_review_state.json`。

## Goals / Non-Goals

**Goals**：让架构师成为可调度、可配模型、可在 UI 设置、产出可复用的完整角色；审查范围严格受限。

**Non-Goals**：不改自省的既有数据源与产出格式；不做全仓扫描；不自动创建 SPEC。

## Decisions

### D1：复用自省调度入口（唯一门），状态键分离，独立 run

**触发入口唯一**：不新增定时器/线程，复用 `SelfReviewScheduler.check_and_run` 既有巡检检查点（`core/self_review.py:456`）。**执行顺序固定**：自省路径（含其零活动跳过）先走完，架构师 run 在其后执行；架构师 MUST NOT 在自省写入状态之前触发。

**状态键分离（本决策的硬约束）**：`self_review_state.json` 现为单键语义——`_save_state`（`core/self_review.py:1062`）写 `last_run_date` + `last_run_at`，`check_and_run`（`core/self_review.py:477`）以 `last_run_date == today` 早退。若架构师按字面「共享同一状态判定」直接复用 `last_run_date`，两种实现顺序均产生事故：

- 自省先跑并写 `last_run_date=today` → 架构师当日**永不触发**（功能静默失效）；
- 架构师先跑并写 `last_run_date=today` → 自省 `check_and_run` 当日**被抑制**（既有功能回归）。

因此 MUST：

1. `self_review_state.json` 新增架构师专用键 `architect_last_run_date`；架构师路径 MUST NOT 写 `last_run_date`（自省的「今日已执行」基准）；
2. 架构师路径 MUST NOT 写 `last_run_at`——它是自省**增量窗口锚点**（`_load_last_run_at` → `window_start`），被架构师覆写会把次日自省窗口起点推到架构师完成时刻，静默丢失两 run 之间的数据；
3. `check_and_run` 的整日早退门扩为「`last_run_date == today` **且** `architect_last_run_date == today`」——两者都完成才不再巡检；架构师单独失败时同日可补跑一次，无需人工清状态文件。

**run 独立**：独立 run_id 前缀、独立结果文件、独立成本类目（见 D8）。
**理由**：用户要求「在每日自省的时候执行」；共享入口避免第二套定时器，状态键分离避免两个角色互相抑制。
**替代**：独立 cron 段——否决，增加配置面且与用户表述不符；共享 `last_run_date` 单键——否决，见上事故分析。

### D2：审查范围 = 自省窗口内变动文件（清单由框架产出，非布尔探测）

数据源为「自省窗口 `window_start`（复用 `SelfReviewScheduler` 的增量窗口起点计算）内发生变更的代码文件**清单**」，注入 prompt。MUST NOT 遍历全仓。

**⚠️ 实测更正（原草案有误）**：`fenixd.py` 的既有工具**无法**用于产出该清单，不得作为清单来源：

- `code_tracked_files`（`fenixd.py:131`）只 glob `fenixd.py` + `core/**/*.py`——`agents/*.md`、`tests/`、前端 `src/**`、`bin/`、`docs/` 全在范围外，用它会把大部分「当日改动」静默漏掉；
- `code_files_changed_since(baseline_ns, files) -> bool`（`fenixd.py:152`）需要调用方**先给出文件清单**，且只返回「是否任一变更」的布尔值——它回答不了「哪些文件变了」；
- `max_code_mtime_ns`（`fenixd.py:141`）返回单个最大 mtime，同样不含路径信息。

**清单来源（按序并集，均以 `window_start` 为界）**：

1. `git -C <project_root> log --since=<window_start ISO> --name-only --pretty=format: --diff-filter=ACMR`——覆盖已提交改动（含 implementer worktree 合并进 main 的提交）；
2. `git -C <project_root> status --porcelain` + `git diff --name-only HEAD`——覆盖**未提交**改动（本仓 main 树常见在飞未提交修改，仅用 git log 会漏）；
3. 上两步均不可用（非 git 仓库 / git 命令失败）时回退 mtime 扫描：按**后缀白名单**（`.py .ts .tsx .js .mjs .md .yaml .yml .json .sh .toml`，白名单可配置）枚举，取 mtime ∈ `[window_start, now]` 者，并在 prompt 中显式标注「清单来源：mtime 降级」。

**范围过滤**：仅保留代码与提示词类路径——`core/`、`fenixd.py`、`agents/`、`bin/`、`scripts/`、`core/dashboard/static/src/`、`tests/`；MUST 排除 `.fenix/`（运行时状态）、`spec/`（SPEC 文档，非代码）、`docs/`、`node_modules/`、`static/dist/`（构建产物）。

**条数上限**：MUST 设上限（缺省 50 条），超出按改动行数降序截断，并在 prompt 中标注「清单已截断（N/M）」，防止大重构日撑爆 prompt。

**理由**：用户明确「代码审查范围也控制在自省周期内变动过的代码；初始化的全仓重构只由人工驱动」。这也是成本控制的关键——每日只审当天动过的代码。

### D3：产出汇入 `todo.md`，复用结构化条目契约
建议条目以 `todo.md` 的既有结构化格式（含 impact/evidence/analysis/suggestion 等键）追加，落点与自省一致。MUST NOT 自动创建 SPEC（沿用自省既有禁令）。
**理由**：用户要求「生成到建议条目中」；复用格式使既有消费方（Dashboard 建议面板、evolution）零改动即可读取。

### D4：模型分配与设置界面（含配置键命名空间与作用域）

- `agents.models.architect` 进 `KNOWN_AGENT_TYPES`；前端 `AGENT_ROLES` 增加 `architect` 卡片（label 如「Architect（架构师）」）。**前后端白名单必须同步**，否则保存被后端拒绝或前端不显示。
- **配置键命名空间（原草案未定，这里定死）**：架构师设置与自省同段同作用域，采用**项目级** `admin.architect.*`：
  - `admin.architect.enabled`：布尔，缺省 `false`；
  - `admin.architect.window_max_hours`：非负整数，`0`/缺省 = 完全跟随自省增量窗口 `[last_run_at, now]`；`>0` = 窗口上界截断为 `max(window_start, now - N hours)`。
  - 原草案的「是否随自省执行」键删除：架构师没有独立调度器（D1 唯一门），该键恒等于 `enabled`，属语义空洞键。
- **作用域（原草案未定，这里定死）**：`self-evolution` 页签在用户级也可打开（`settings/index.tsx` 的 `BASE_MENU_ITEMS`），而 `self_evolution.*` 是**用户级全局键**、`admin.self_review`/`admin.architect` 是**项目级键**。新卡片 MUST 沿用 `SuggestedImprovementsPanel` 的既有 scope 约定——用户级作用域下只读、`collect()` 返回空补丁，仅项目级可写；否则会把项目级键写进用户级配置。
- 新增配置键落盘的**四处必改点**（缺一处即「保存被静默丢弃」，本仓已有两次同类事故，见 D7）。
- 无 `agents.models.architect` 时回退策略：回退到 `self-review` 链或全局默认（沿用既有未配置回退语义）。

### D5：prompt 文件化
新增 `agents/architect.md`，经 `AGENT_PROMPT_FILES` 映射加载（缺失 fail-fast）。prompt MUST 说明：五种 DFX 维度、受限审查范围、输出格式与「不得自动建 SPEC」。

### D6：不使用绝对行号锚定任务。

### D7：受管键必须走全链路（白名单合并是静默丢弃区）

`_deep_merge_managed`（`core/dashboard/data.py:4484`）是**白名单合并**：patch 里未显式列出分支的键不会报错，会被**静默丢弃**。本仓已因此出过两次事故，注释留有记录：

- `data.py:4508`「add-cost-observability：此前缺合并分支，保存后预算键被静默丢弃」；
- `data.py:4512`「fix-daemon-lifecycle-races 验证发现：缺合并分支导致保存被静默丢弃」。

且 `admin.self_review` 的合并分支（`data.py:4576-4590`）**只透传 `enabled` / `read_todo` / `run_at` 三个子键**，其余子键一律丢弃。因此：

- 架构师键 MUST NOT 挂在 `admin.self_review.<子键>` 下（会被该分支吞掉），必须是**顶层 `admin.architect` 段**并自带合并分支与前置校验；
- 新键落盘 MUST 同步四处：`_deep_merge_managed` 合并分支、`write_config` 前置校验（`data.py:4682` 一带）、`_SOURCE_KEYS` + `_managed_key_sources`（`data.py:3974` / `:4071`，缺则「继承自用户级」badge 失真）、`_DEFAULT_SELF_REVIEW` 同款缺省回显（`data.py:4171` / `:4457` 一带，缺则界面回显为空）；
- 验收 MUST 含**读写往返**断言（保存 → 重新 GET → 值仍在），而非只断言「保存返回 200」——两次历史事故都是保存成功但值消失。

### D8：架构师 run 不得污染自省的数据源与告警口径

`collect_runs_stats`（`core/self_review.py:293`）目前**只排除 `run_id.startswith("review-")`**。架构师 run 用独立前缀落在 `.fenix/runs/` 后若不加排除，会：

- 计入 `total` / `succeeded` / `failed`，进入 `collect_daily_summary` 注入自省 prompt——自省把自己的数据源统计进一个**非 SPEC run**；
- 更严重：点亮零活动防护的反面——`_execute_review`（`core/self_review.py:498`）在窗口内 `total == 0` 时走 `_skip_review` 不唤起自省。架构师 run 自身会让 `total > 0`，使「当日无 SPEC 活动」的判定失真（顺序依赖：架构师先跑则当日自省被误唤起）。

因此架构师 run_id 前缀 MUST 在 `collect_runs_stats` 的排除集中一并登记（与 `review-` 同处），并确认 `collect_failed_run_samples` 与 Dashboard run 视图口径。

**失败处置**：架构师 run 异常/超时/rc≠0 MUST 与自省同款——`_record_failure_alert` 记告警、当日不重试（防风暴），靠 D1 的 `architect_last_run_date` 独立键使次日自然重试。`admin_monitor._RUN_PREFIXES`（`core/admin_monitor.py:229`）是失败统计**子集**，架构师前缀建议纳入，否则架构师连续失败无人在失败 run 统计中察觉。

**成本归账**：沿用 `run_self_review` 的独立类目文件（`.fenix/cost/self_review_tokens.json`，见 `_accumulate_self_review_tokens`），条目 `agent_type: "architect"` 以便对账区分；写失败静默降级（观测增强，不阻断）。

## Risks / Trade-offs

- [注册表漏改致角色静默失效] → 任务的验收项显式列举全部注册表并逐一断言（config / prompt_builder / runner 映射 / run_files / 前端）。
- [架构师与自省互相抑制或窗口锚点漂移] → D1 状态键分离（`architect_last_run_date` 独立键；架构师不写 `last_run_date`/`last_run_at`）+ 整日早退门双键判定。
- [架构师 run 污染自省数据源与零活动防护] → D8 把架构师前缀加入 `collect_runs_stats` 排除集。
- [新增配置键保存后被静默丢弃] → D7 四处必改点 + 读写往返验收（本仓已有两次事故）。
- [审查范围失控导致成本上升] → D2 强制窗口受限 + 清单条数上限；prompt 明确禁止全仓扫描。
- [大重构日清单过大撑爆 prompt] → D2 条数上限 + 截断标注。
- [新增配置键无界面 / 无文档] → D4 强制同步界面与作用域；新增角色须同步 `docs/help/02-concepts.md` 角色表与 `docs/help/09-config.md` 的 `agents.models` 角色枚举（该处现写死「键取九角色」，新增角色后即成错误文档）。
- [与在飞 SPEC 争抢同一文件] → `AgentModelPanel.tsx` 正在被并行 SPEC 修改（工作树已有未提交改动）；`core/dashboard/data.py` 的拆包重构 `refactor-dashboard-data-module` 尚未实现（仅 drafted），故本 SPEC MUST 直接登记 `core/dashboard/data.py`。

## Migration Plan

1. 阶段 1：后端角色接线（config / prompt_builder / runner / run_files）+ `agents/architect.md`。
2. 阶段 2：调度接入 `self_review.py`（唯一门 + 状态键分离 + 窗口内变更清单 + run 统计排除）。
3. 阶段 3：建议产出与 `todo.md` 写入、失败告警与成本归账。
4. 阶段 4：前端模型分配卡片 + 自进化页签设置卡片（含作用域）+ 受管键四处必改点。
5. 阶段 5：文档同步（`docs/help/02-concepts.md`、`docs/help/09-config.md`）与测试实证（触发一次架构师 run 确认产出）。

**回滚**：逐阶段 commit；角色未启用时全链路零动作。
