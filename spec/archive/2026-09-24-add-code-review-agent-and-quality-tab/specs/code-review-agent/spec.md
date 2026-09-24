## ADDED Requirements

### Requirement: code-review agent 类型注册

系统 SHALL 新增一等公民 agent 类型 `code-review`，在全部四处注册点保持一致，缺任一注册点均视为实现不完整。

- `core/agent_runner/prompt_builder.py` 的 `AGENT_PROMPT_FILES` MUST 含 `"code-review": "code-review.md"`。
- `core/agent_runner/run_files.py` 的 `RUN_ID_AGENT_PREFIXES` MUST 含 `("code-review-", "code-review")`。
- `core/config.py` 的 `KNOWN_AGENT_TYPES` MUST 含 `"code-review"`。
- `.fenix/config.template.yaml` 的 `agents.models` MUST 含 `code-review` 模型分配示例（用户级/项目级 `.fenix/config.yaml` 为 gitignored 运行时文件，由用户按模板自行配置，不进交付声明）。
- 框架根 `agents/code-review.md` 提示词文件 MUST 存在。
- 未登记 `agents.models.code-review` 时，模型链 MUST 依次回退 `self-review` → `administrator` → 默认网关，MUST NOT 静默走默认网关而无回退。

#### Scenario: run_id 前缀被正确归属

- **WHEN** 存在 run_id 为 `code-review-1758211200` 的 run
- **THEN** `infer_run_agent_type("code-review-1758211200")` MUST 返回 `("code-review", "1758211200")`，Dashboard 时间线 MUST 显示该 agent 类型而非泛型 `agent`

#### Scenario: 模型分配生效

- **WHEN** 配置 `agents.models.code-review` 分配了模型
- **THEN** 派发 code-review run 时 MUST 使用该模型；配置缺失时 MUST 回退 `agents.models.self-review`，再缺失回退 `administrator`，均缺失才走默认网关

### Requirement: 周期窗口与自省同源

code-review 的审查周期 SHALL 与每日自省（`admin.self_review`）完全同源，MUST NOT 另立一套周期口径。

- `window_start` MUST 取 `.fenix/self_review_state.json` 的 `last_run_at`；无 `last_run_at`（首跑/旧格式）MUST 回退 `now - 24h`，与 `core/self_review.py` 的窗口计算一致。
- 周期窗口内「开发 SPEC 的代码」MUST 定义为 `window_start` 之后合并/产出到主树的 SPEC 所变更的文件集合。
- 触发时点 MUST 与自省时点对齐：在 admin 巡检判定到达自省时点（`run_at`）时同步触发 code-review 检查点。
- 调度守卫 MUST 与自省一致：同一自然日不重复触发；未到 `run_at` 不触发；`admin.code_review.enabled` 为 false 时全链路零动作（不派发、不写产物）。

#### Scenario: 窗口起点取上次自省时刻

- **WHEN** `.fenix/self_review_state.json` 的 `last_run_at` 为 `T0`，当前触发 code-review
- **THEN** 审查窗口 MUST 为 `[T0, now]`，审查对象 MUST 为 `T0` 之后合并的 SPEC 所变更文件

#### Scenario: 首跑回退 24 小时

- **WHEN** `.fenix/self_review_state.json` 无 `last_run_at` 字段
- **THEN** 审查窗口 MUST 为 `[now - 24h, now]`

#### Scenario: 开关关闭零动作

- **WHEN** `admin.code_review.enabled` 为 false
- **THEN** 到达自省时点 MUST NOT 派发 code-review run、MUST NOT 写任何 code-review 产物

### Requirement: 派发与增量落盘

`code-review` agent SHALL 由 daemon/admin_monitor 层派发，审查 manifest（文件清单）由框架侧先行算出并注入 prompt，agent 逐文件审查并增量落盘。

- 派发逻辑 MUST 位于框架调度层（daemon/admin_monitor），MUST NOT 位于 `core/self_review.py`（该模块硬约束 MUST NOT 派发 agent）。
- run_id MUST 采用 `code-review-<epoch>` 形式。
- 框架侧 MUST 在派发前算出 manifest（待审文件绝对/相对路径列表），并写入 prompt；manifest 长度 MUST 作为进度 `total` 的权威来源。
- agent MUST 每审查完一个文件就向 `.fenix/code-review/out-<run_id>.jsonl` 追加一行结果（增量落盘），MUST NOT 仅在 run 结束时一次性写出。
- agent MAY 调用 `ocr` 作为辅助审查手段；`ocr` 缺失或不可达时 MUST 降级继续（不因辅助工具缺失而整轮失败）。

#### Scenario: manifest 驱动进度总数

- **WHEN** 框架侧算出待审文件 42 个
- **THEN** prompt MUST 含该 42 个文件的清单，且本次 review 的进度 `total` MUST 为 42

#### Scenario: 逐文件增量落盘

- **WHEN** agent 审查完第 5 个文件（共 42 个）
- **THEN** `.fenix/code-review/out-<run_id>.jsonl` MUST 已含 5 行结果，进度 `done` MUST 为 5，MUST NOT 等到 42 个全审完才落盘

#### Scenario: ocr 缺失降级

- **WHEN** 环境未安装 `ocr` 或 provider 不可达
- **THEN** agent MUST 仍以 LLM 审查完成本次审查，MUST NOT 因辅助工具缺失而整轮失败

### Requirement: 审查进度与取消

系统 SHALL 对外暴露 code-review 的运行状态与真实进度，并支持取消在跑的审查 run。

- 进度结构 MUST 含 `{running, review_id, review_kind, total, done, current}`。
- `running` 判定 MUST 基于该 run 产物 `.fenix/runs/<review_id>.jsonl` 的末行终态：终态集合 MUST 取既有运行终态全量四类（`result` / `error` / `interrupted` / `cancelled`），并叠加既有 stale 阈值兜底；MUST NOT 以「产物/manifest 文件是否存在」近似判定（否则已取消或已停机的 run 会永远显示为运行中，进度条与取消按钮永不收起，且手动触发的 409 守卫恒真、后续触发全部被拒）。
- 取消 MUST 复用既有 run 取消机制：写 `.fenix/cancel_run_request.json` 旗标后由 daemon 消费，MUST NOT 另立取消通道。
- 取消后该 run MUST 终止，已落盘的部分结果 MUST 保留（不丢已完成的审查条目）。

#### Scenario: 运行中可查真实进度

- **WHEN** 一次全仓审查运行中（total=42，已审 17）
- **THEN** `GET /api/code-review/progress` MUST 返回 `running=true, total=42, done=17`，前端据此渲染真实百分比进度条

#### Scenario: 取消在跑审查

- **WHEN** 用户在审查运行中点击取消
- **THEN** 系统 MUST 经 `/api/run-cancel` 写入取消旗标，daemon MUST 终止该 `code-review-*` run，已落盘的部分结果 MUST 保留，进度 MUST 转为 `running=false`
