## Why

验证器（verifier）在重试时总是从零开始：每次 attempt 都新建 worktree、agent 上下文全新，前一次已完成的验证场景全部作废。`improve-dashboard-sections` 的 re-verify 连续两次因 `claude CLI Max turns (150) reached` 失败（每次约 13 分钟跑满 150 轮），原因正是 32 个场景无法在 150 轮内完成、且重试无断点。此外 `agents.max_turns` 目前只能手工编辑配置文件，与并行度（`agents.max_concurrent`）的运维体验不一致。

## What Changes

- 将 `agents.max_turns` 默认值从 150 调整为 300（`.fenix/config.yaml` 显式值、未配置时的代码 fallback 统一为 300）。
- Dashboard 配置页的「并行度设置」区块新增 `max_turns` 数字输入与保存，与 `agents.max_concurrent` 并列编辑；保存复用 `POST /api/config`，并纳入受管子键清单，保留其它子键原值不变（扩展 add-parallelism 的配置页能力）。
- verifier 支持从 verify-progress 文件断点续跑：框架在重试构造 verifier prompt 时读取 `.fenix/verify-progress/<spec>.json`，将已完成进度（done/total/当前场景描述）注入提示词，新 agent 从断点序号继续验证，不再从头重跑。

## Capabilities

### New Capabilities
- `agent-run-params-config`: agents.max_turns 的默认值调整与 Dashboard 配置页可视化编辑（与并行度并列）
- `verifier-checkpoint-resume`: verifier 重试时读取并注入 verify-progress 断点，从上次完成场景续跑

### Modified Capabilities
<!-- 无：现有并行度 spec 不产生需求级变更，仅在其能力基础上扩展 -->

## Impact

- `core/config.py`：`agents.max_turns` 校验与默认值（当前默认 50）→ 300
- `core/agent_runner.py`：`_build_prompt` verifier 分支注入断点信息；`max_turns` 读取点（`agents.max_turns`，AgentRunResult 错误文本）
- `core/dashboard/data.py`：`_AGENTS_MANAGED_SUBKEYS` / `_SOURCE_KEYS` 增加 `max_turns`
- `core/dashboard/static/app.js` + `index.html`：配置页「并行度设置」区块增加 max_turns 编辑
- `.fenix/config.yaml`：`agents.max_turns: 150` → `300`
- 依赖：无新增依赖；行为向后兼容（未配置时默认 300）