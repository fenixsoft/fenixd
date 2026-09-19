# Design: add-code-review-agent-and-quality-tab

## Context

项目页「质量」分面目前是空态占位（`add-project-detail-tabs` 定义）。框架已有两条与"代码质量"沾边的能力，但都不是本需求：

1. **`verify.impl_code_review`（已落地）**：单 SPEC 实现收尾时用 `ocr` 审本次 diff，是一次性、局部、随 run 消亡的。产物 `.fenix/verify-progress/<spec>/code-review.json`，硬门在 `core/agent_runner/result_gate.py:423`。
2. **每日自省（`admin.self_review`）**：`self-review` agent 跑在 main 树，产物写 `.fenix/todo.md`，硬约束 **MUST NOT 派发 agent**（`core/self_review.py` 模块 docstring）。周期口径：`run_at` 当日触发点 + 增量窗口 `window_start = last_run_at`（首跑回退 24h）。

本设计新增第三条独立车道：**周期性仓库级 code review**，与自省同周期触发、独立台账、可在 Dashboard 呈现与消费。

## Goals

- 每日自省时点额外派一个 `code-review` agent，审查本周期内开发 SPEC 的代码质量。
- 问题沉淀为可追踪台账，去重、可核销、可人工处置。
- 项目页「质量」分面表格呈现 + 复选 + 一键生成修复 SPEC。
- 两个手动触发按钮（全仓 / 本周期），运行中真实进度条 + 取消。
- 与既有机制严格解耦：不替换 `impl_code_review`，不改自省产物语义。

## Non-Goals

- 跨项目聚合（只在项目页呈现当前仓）。
- 引入静态分析器/向量库依赖（`ocr` 仅作可选辅助）。
- 把 code-review 结果接入 push/approve 门禁（本变更只做呈现与消费入口）。

## Decisions

### D1：引擎 = LLM agent 为主 + ocr 辅助（用户已确认）

新增一等公民 agent 类型 `code-review`。逐文件 LLM 审查为主；agent 可自行调用 `ocr`（alibaba open-code-review）作为辅助手段，缺失降级。

**四处强制注册点**（探查确认，缺任一即退化）：
- `core/agent_runner/prompt_builder.py:26` `AGENT_PROMPT_FILES` + 框架根 `agents/code-review.md`
- `core/agent_runner/run_files.py:28` `RUN_ID_AGENT_PREFIXES`（否则时间线退化为泛型 `agent`）
- `core/config.py:114` `KNOWN_AGENT_TYPES`（否则 `agents.models.code-review` 被静默跳过、回退默认网关）
- `.fenix/config.yaml` + `.fenix/config.template.yaml` 的 `agents.models.code-review`

**模型链回退**：`code-review` → `self-review` → `administrator` → 默认网关（与 `evolution` 同型，`maintenance_runs.py:373`）。

**理由**：LLM agent 能给出语义级、可读的修复建议（生成修复 SPEC 需要），`ocr` 静态规则单独用覆盖面与可解释性不足；二者结合而非二选一。

### D2：独立台账 + 复用 evolution 生成链路（用户已确认）

存储独立为 `.fenix/code-review/items.jsonl`（对标 `.fenix/evolution/items.jsonl`），**不复用 evolution 的 items.jsonl**（语义混淆、水位/扫描逻辑不通用）。但"生成修复 SPEC"**复用** evolution 的材料化/同源 lint/复制/注册机制（`materialize_draft` / `lint_draft` / `_git_commit` / `add_spec` 的形态），命名前缀改为 `fix-cr-` 与 `evo-` 隔离。

**理由**：存储各有语义（evolution 条目来自 todo.md 文本、code-review 条目来自代码审查），强行合并会把两套去重/水位逻辑搅在一起；而 SPEC 材料化与注册是纯粹的机械流程，重复实现无收益。

### D3：周期窗口与自省同源（复用 `self_review_state.json`）

`window_start` 直接读 `.fenix/self_review_state.json` 的 `last_run_at`（与 `core/self_review.py:507` 同一口径），首跑回退 `now - 24h`。触发点绑定在 admin 巡检判定到达自省时点之后（同一 `run_at`），复用同一自然日防重与开关守卫形态。

**派发位置**：daemon/admin_monitor 层（`fenixd.py` / `core/admin_monitor.py`），**不在 `core/self_review.py` 内**——该模块硬约束 MUST NOT 派发 agent。在 admin 侧新增一个 `_check_code_review_checkpoint`，与 self_review checkpoint 并列。

**理由**：用户明确"周期计算逻辑与自省一致"；复用同一状态源保证两者永远同窗口，不引入漂移。

### D4：manifest 驱动真实进度

派发前框架侧算出待审文件清单（manifest），写入 prompt 且作为进度 `total` 权威来源。agent 逐文件审查、每完成一个文件即向 `.fenix/code-review/out-<run_id>.jsonl` 追加一行。进度 `done` = 该 jsonl 行数 / manifest 长度。

对比 `verify` 的进度（`.fenix/verify-progress/<spec>.json` 的 `{total,done,current}`）复用同型结构。

**理由**：文件数确定是用户点名的前提（"因为文件数是确定的，所以应当能做真实的进度条"），逐文件增量落盘让进度实时、且取消后部分结果不丢。

### D5：全仓快照核销，窗口只增不增

`manual_full` 是本仓全量观测，作权威快照：本轮未再观测到的 open 项置 `resolved`。`scheduled` / `manual_window` 只观测窗口内文件，未观测 ≠ 已修复，**只增不核销**。

**理由**：窗口审查范围小于全仓，据此判 resolved 会把窗口外的问题误核销。核销必须由全量观测驱动。

### D6：取消复用既有 run-cancel

不另立取消通道。前端拿 `review_id` → `POST /api/run-cancel` → `.fenix/cancel_run_request.json` 旗标 → daemon 消费终止。已落盘的部分 jsonl 保留。

**理由**：`run-cancel` 是既有、已验证的通用机制，对 `code-review-*` run 天然适用。

### D7：配置开关 UI 落点 = 项目页质量分面

新增 `admin.code_review.enabled`（缺省 false，对标 `admin.self_review.enabled`）。开关放**项目页质量分面的控制区**（与两个触发按钮同区），不放设置页——因为它是"本仓是否参与周期审查"的项目级语义，且与问题表格同屏更直观。

> ⚠️ **协同风险**：设置页「质量」面板（`QualityPanel.tsx` + `settings/index.tsx` + `config_admin.py` 的 `quality` 同步页）当前是**未提交的在飞改动**。本变更触碰 `config_admin.py` / 设置页文件族，实现前须先把在飞改动合并/对齐，避免并发同文件冲突（`.fenix/todo.md` 已有 `80070fbb` 丢开关前科）。

### D8：修复 SPEC 命名 `fix-cr-<slug>`

与 `evo-` 区分。`<slug>` 由选中问题推导（如首个问题的 `category` 或短标题），满足 `^[a-z0-9][a-z0-9-]*$`。冲突时追加 `-<fingerprint[:6]>`，仍冲突返回错误不覆盖。判重三处口径复用 evolution `resolve_spec_name` 的形态。

## Components

| 组件 | 文件 | 职责 |
|------|------|------|
| 台账读写/指纹/状态机/窗口/manifest | `core/code_review.py`（新增） | 纯逻辑，被 daemon 与 dashboard 复用 |
| 配置读取 | `core/config.py` `get_code_review_config` | `admin.code_review.enabled` 等 |
| agent 注册/prompt | `prompt_builder.py` / `run_files.py` / `agents/code-review.md` | 四处登记 + prompt 构建 |
| run 实现 | `core/agent_runner/maintenance_runs.py` `run_code_review` | 派发、读增量产物、ingest 入台账 |
| 调度 | `fenixd.py` / `core/admin_monitor.py` `_check_code_review_checkpoint` | 时点对齐、单飞、守卫 |
| Dashboard 读取器 | `core/dashboard/data/code_review.py`（新增） | items / progress 读取 |
| Dashboard 路由 | `core/dashboard/routes/code_review_routes.py`（新增） + `routes/base.py` | 5 个端点注册 |
| 前端分面 | `pages/projects/list.tsx` + `components/QualityTab.tsx`（新增） | 表格/按钮/进度/取消/生成入口 |

## Data Flow

1. **周期触发**：admin 巡检到 `run_at` → `_check_code_review_checkpoint` → 读 `self_review_state.json` 窗口 → 收集窗口内 SPEC 变更文件 → `run_code_review`。
2. **审查**：manifest 注入 prompt → `code-review` agent 逐文件审 → 增量写 `out-<run_id>.jsonl`。
3. **落账**：run 结束 → `ingest` 读增量 → 指纹去重 upsert `.fenix/code-review/items.jsonl`。
4. **核销**：`manual_full` 收尾执行快照核销。
5. **展示**：前端 `GET items` → 表格；`GET progress` → 进度条；`POST run` → 触发；`POST generate-spec` → 生成修复 SPEC。

## Risks

| 风险 | 缓解 |
|------|------|
| 大仓全仓审查耗时长/烧钱 | manifest 上限截断 + 全仓审查仅手动触发；窗口审查是每日默认 |
| agent 输出夹带疑似指令 | 台账无 raw transcript 回流；ingest 只消费结构化字段（不注入下游 prompt） |
| 与在飞设置页改动冲突 | 实现前对齐（D7 协同风险），或把质量开关完全落在项目页避开设置页文件 |
| 增量 jsonl 被 `-rN`/`-aN` 后缀混淆 | run_id 归一化复用既有 `_normalize_run_id` 口径 |
| 空场景/空 manifest 白洗 | manifest 为空时 MUST NOT 记为"全绿"，明确置 `no_files` 或跳过并告警 |

## Testing Strategy

- 单元：指纹稳定性、去重 upsert、快照核销 vs 窗口不核销、命名冲突消解、lint 同源、窗口计算与自省一致。
- 契约：四处 agent 注册点一致性（含 `KNOWN_AGENT_TYPES` / `RUN_ID_AGENT_PREFIXES`）。
- 端点：5 个 API 的 happy path + 409 + 幂等 + skipped。
- 前端：多选、按钮禁用逻辑、进度条渲染、取消流程（可用 fixture）。
- 集成：`verify.yaml` 三段式场景，含开关关闭零动作、取消保留部分结果。
