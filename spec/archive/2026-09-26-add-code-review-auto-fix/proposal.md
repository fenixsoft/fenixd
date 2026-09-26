## Why

周期性代码审查（`add-code-review-agent-and-quality-tab`）已能把问题沉淀为可追踪台账，但台账里的 `open` 条目**只能人工逐个勾选「生成修复 SPEC」**再走完整 PM 流水线——问题积压越多，人工分诊成本越高，审查结果的时效价值越低（本仓当前 428 条台账、open 数百条）。用户需要一条**受控的自动修复通道**：审查结束即自动派出修复 Agent，分批修复、每批必过全量回归、通过才合回主树，把「审查发现问题」闭环成「问题被修复且未引入回归」。

## What Changes

- **新增 `code-fix` 一等公民 agent 类型**：与 `code-review` 同形的四处注册点（`AGENT_PROMPT_FILES` / `RUN_ID_AGENT_PREFIXES` / `KNOWN_AGENT_TYPES` / config 模板）+ 框架根 `agents/code-fix.md`。其模型配置**复用 code-review 的 LLM 配置**（`agents.models.code-review` → `self-review` → `administrator` → 默认网关的同一解析链）。
- **新增自动修复车道（框架编排）**：daemon 拾取台账 `open` 条目，**每 `batch_size`（缺省 20）条为一批**，派一次 `code-fix` agent run 在独立 worktree 内修复并提交；框架在该 worktree 上跑**全量回归**，通过则 `merge-back` 回主树并把该批条目置 `resolved`，随后进入下一批，直至无 `open` 条目。
- **两路激活**：(a) **审查 run 收尾时同步触发**——`run_code_review` 完成且产生 `open` 条目时立即激活；(b) **30 分钟 full scan 周期兜底检查**——daemon 的 full_scan 每轮检查是否存在未处理的 `open` 条目，自动激活。
- **单飞与幂等**：开关关闭、已有 `code-fix` run 在跑、无 `open` 条目 → 不重复激活；daemon 重启后下一轮 full scan 自动续做剩余条目。
- **回归不通过处置**：该批修正**不**合回主树，自动**重试一次**；仍不通过则丢弃该批、worktree 保留待人工，条目保持 `open`。
- **回归契约缺失处置**：项目 `verify.yaml` 无 `regression` 段时，**复用既有 AI 自动起草通道**（`verify_contract_missing` 信号 → administrator agent 起草 regression 段并自证落位）；起草未完成前本批 **fail-closed** 不合回，并记录原因，下一轮周期检查再试。
- **新增配置键群 `admin.code_review_fix.*`**：`enabled`（缺省 false）+ `batch_size`（缺省 20，可改），配置归设置页；开关落在设置页「质量」页签「周期性代码审查」**下方**，名为「自动修复代码问题」。
- **进度呈现**：项目页「代码审查」页签展示自动修复的工作情况——**已处理数量 / 总数 / 进度条**（复用既有 `Progress` 呈现形态）。

## Capabilities

### New Capabilities

- `code-fix-agent`: `code-fix` agent 类型注册（四处注册点 + 提示词文件）与模型链复用（复用 code-review 的 LLM 配置），以及其 run/worktree/合回形态。
- `code-fix-lane`: 自动修复编排车道——两路激活（审查收尾 + 30 分钟 full scan）、批次循环（每 `batch_size` 条一批）、单飞与幂等、全量回归门、失败重试一次、合回与条目 `resolved` 终态、回归契约缺失的自动起草复用与 fail-closed。
- `code-fix-progress`: 自动修复进度上报（`total`/`done`/`current`/`running`/批次阶段）、只读 API、项目页「代码审查」页签的进度条呈现。
- `code-fix-config`: `admin.code_review_fix.enabled` / `batch_size` 两键的读取、Dashboard 受管键读写回显与校验、设置页「质量」页签开关与数值输入。

### Modified Capabilities

- 无——本次全部为新能力；对既有 `code-review` 台账/审查车道的复用不改变其 spec 级行为（`code-review` 车道仍只读审查、不改码；自动修复是独立新车道）。对 `verify.yaml` 的结构复用既有 `regression` 段契约（`add-test-regression-tab`），不新增字段。

## Impact

- **配置契约**：`.fenix/config.yaml` 新增可选 `admin.code_review_fix.*` 段（缺省关闭零动作，旧配置零迁移）。
- **代码**：
  - `core/code_fix.py`（新模块：条目选择、批次状态、进度读写、激活判据、编排循环）
  - `agents/code-fix.md`（新：修复者角色提示词 + 输出/提交契约）
  - `core/agent_runner/maintenance_runs.py`（`run_code_fix` 执行函数，对齐 `run_code_review`/`run_regression` 形态）
  - `core/agent_runner/prompt_builder.py` / `run_files.py` / `runner.py`（agent 类型注册与门面转发表）
  - `core/config.py`（`KNOWN_AGENT_TYPES` + `get_code_review_fix_config`）
  - `core/event_bus.py`（full scan 兜底激活检查）
  - `fenixd.py` / `core/admin_monitor.py`（审查收尾同步触发点与 executor 注入）
  - `core/dashboard/data/config_admin.py`（受管键读写回显/校验）
  - `core/dashboard/data/code_review.py` + `core/dashboard/routes/code_review_routes.py` + `core/dashboard/routes/base.py`（进度 API）
  - 前端 `core/dashboard/static/src/services/dashboard.ts`、`pages/settings/components/QualityPanel.tsx`、`pages/settings/components/PromptsPanel.tsx` + `AgentModelPanel.tsx`（两个硬编码 agent 角色列表须与后端同步，否则新角色在提示词/模型编辑器中不可见）、`pages/projects/components/QualityTab.tsx` + 新建 `pages/projects/components/CodeFixProgressCard.tsx`（进度卡片独立成文件，避免扰动既有 `QualityTab` 渲染面与其测试）
  - `.fenix/config.template.yaml`、`docs/help/09-config.md`（配置模板与映射表）
- **兼容性**：`admin.code_review_fix.enabled` 缺省 false 时全链路零动作；无 `regression` 段项目 fail-closed 不合回、不报错刷屏。
- **依赖**：复用既有 `verify.yaml regression` 契约、`worktree_manager` 的 create/merge-back、`core/regression.run_regression` 执行原语、既有 AI 契约起草通道；不引入新第三方依赖。
