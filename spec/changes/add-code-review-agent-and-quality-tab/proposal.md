## Why

项目页的「质量」分面（`core/dashboard/static/src/pages/projects/list.tsx` 的 `quality` 分页）目前只是「质量视图建设中」的空态占位，框架没有一个集中呈现「当前代码仓代码质量」的地方。既有的 `verify.impl_code_review` 只在**单个 SPEC 实现收尾**时用 `ocr` 审本次 diff，是一次性、局部、随 run 消亡的——既无跨周期的仓库级视角，也无历史问题台账，用户无法回答"这个仓库现在有哪些代码质量问题""上周开发的代码质量如何"。

本变更新增一条**周期性代码审查车道**，与每日自省同周期运行：自省时除 `self-review` agent 外再派一个 `code-review` agent，审查本周期内开发 SPEC 产生的代码质量，把问题沉淀为可追踪的台账（items），并在项目页「质量」分面以表格呈现，支持复选后一键生成修复 SPEC；用户还能手动触发「全仓库审查」或「立即审查本周期」，手动触发时展示基于文件总数的真实进度条与取消按钮。

## What Changes

- **新增 `code-review` agent 类型**：登记进 `AGENT_PROMPT_FILES` / `RUN_ID_AGENT_PREFIXES` / `KNOWN_AGENT_TYPES`，新增 `agents/code-review.md` 提示词；模型分配写入入库的 `.fenix/config.template.yaml`（`.fenix/config.yaml` 为 gitignored 运行时文件，由用户按模板配置）。审查引擎以 **LLM agent 为主**（逐文件审查），`ocr` 作为 agent 可自行调用的辅助手段（缺失降级，不阻塞）。
- **周期性调度**：admin daemon 在每日自省时点追加一个 code-review 检查点，窗口计算与 `admin.self_review` 完全同源（复用 `.fenix/self_review_state.json` 的 `last_run_at` 作为 `window_start`，首跑回退 24h），只审查窗口内开发 SPEC 的代码。派发逻辑落在 daemon/admin_monitor 层，**不在 `core/self_review.py` 内**（该模块硬约束 MUST NOT 派发 agent）。
- **独立问题台账**：`.fenix/code-review/items.jsonl`，指纹去重（同 fingerprint 只更新 `last_seen_at`）；`manual_full`（全仓审查）作为权威快照，未再观测到的 open 项自动置 `resolved`，窗口审查只增不核销。
- **真实进度与取消**：审查 manifest（文件清单）由框架侧算好写入 prompt 并作为 `total`；agent 逐文件增量落盘 `.fenix/code-review/out-<run_id>.jsonl`，`done` = 已落行数，构成真实进度条。取消复用既有 `POST /api/run-cancel` + `.fenix/cancel_run_request.json` 旗标。
- **Dashboard 后端**：新增读取器与路由——`GET /api/code-review/items`、`GET /api/code-review/progress`、`POST /api/code-review/run`、`POST /api/code-review/generate-spec`、`POST /api/code-review/items/status`。
- **项目页「质量」分面**：替换空态为 `QualityTab`——可复选问题表格 + 右上角两个触发按钮（全仓库 / 本周期）+ 运行中真实进度条与取消按钮 + 底部「生成修复 SPEC」。
- **生成修复 SPEC**：复用 evolution 的草稿材料化 / 同源 lint / 复制到 `spec/changes` / `git commit` / `add_spec(drafted)` 链路，命名 `fix-cr-<slug>`（与 `evo-` 区分）。tasks.md 内联被选 findings 与 `file:line`。
- **配置项**：新增 `admin.code_review.enabled`（缺省 false）+ `agents.models.code-review`，并在项目页质量分面提供开关（遵循"新增配置项必须带 Dashboard 界面"）。

## Capabilities

### New Capabilities

- `code-review-agent`：周期性代码审查 agent 的派发、窗口计算、逐文件审查、增量落盘、进度与取消。
- `code-review-items`：代码质量问题台账的存储、指纹去重、状态机（open/in_spec/resolved/ignored）与权威快照核销。
- `code-review-quality-tab`：项目页「质量」分面的问题表格展示、复选、手动触发（真实进度条 + 取消）与生成修复 SPEC。
- `code-review-spec-generation`：由选中的问题条目机械生成修复 SPEC（复用 evolution 材料化/注册链路）。

### Modified Capabilities

- `project-page-tabs`：「质量」分面由「空态占位、MUST NOT 发起请求」变更为「承载代码审查质量视图、主动拉取数据」。

（「周期时点追加一个 code-review agent」的语义已并入 `code-review-agent` 能力，不单列 self-review 的 delta。）

## Impact

- **前端**：`core/dashboard/static/src/pages/projects/list.tsx`（quality 分面）、新增 `components/QualityTab.tsx` 及子组件；复用 `RunCancelModal` / `Progress` / `StatusTag` 范式。构建产物 `core/dashboard/static/dist/` 不随库提交，验证时本地 `npm run build`。
- **Dashboard 后端**：新增 `core/dashboard/data/code_review.py`、`core/dashboard/routes/code_review_routes.py`、在 `routes/base.py` 注册路由。
- **框架核心**：新增 `core/code_review.py`（台账读写、指纹、状态机、窗口计算、manifest 构造、SPEC 生成）；`core/config.py`（`get_code_review_config`、`KNOWN_AGENT_TYPES`）；`core/agent_runner/`（`prompt_builder.py` 的 `AGENT_PROMPT_FILES` 与 prompt 构建、`run_files.py` 的 `RUN_ID_AGENT_PREFIXES`、`maintenance_runs.py` 新增 `run_code_review`）；`fenixd.py` / `core/admin_monitor.py`（检查点）；`agents/code-review.md`。
- **配置**：`.fenix/config.template.yaml`（模板）+ `docs/help/09-config.md`（文档）。
- **依赖/协同**：设置页「质量」面板（`QualityPanel.tsx` 等）当前是**未提交的在飞改动**，本变更触碰同文件族，实现前须先对齐/合并以避免并发冲突。既有 `verify.impl_code_review`（收尾 ocr 审 diff）链路不在本变更范围。
- **非目标**：不做跨项目聚合；不替换 `verify.impl_code_review`；不引入向量/静态分析器依赖（`ocr` 仅为可选辅助）。
