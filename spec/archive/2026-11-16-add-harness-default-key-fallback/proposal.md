# Proposal: add-harness-default-key-fallback

## Why

任一 Agent 无 `agents.models` 分配时，claude 形态靠环境继承天然工作，dsh 形态却在适配器预检处 fail-fast（`DshSpawnConfigError`，实证 2026-11-02 dsh-plugins arbiter run 0.001s/0 tokens 秒败）——回落语义不对称，违背用户 2026-11-03 裁定的「开箱即用」原则：只要 harness 自身配置了模型/key，无分配即应以 harness 自身配置启动，与是否配了 fenixd 级 provider 链无关。原「绝不回退 dsh 默认档」纪律（D9）被该裁定正式取代。

## What Changes

- dsh 适配器预检放宽：`SpawnRequest` 无 provider 链（model/baseurl/apikey 任一缺失）不再抛 `DshSpawnConfigError`，改为**省略 `--patch`**（不写 patch 文件、argv 不携带），由 dsh 按 profile 自身配置的默认模型启动
- claude 适配器：现状已环境继承，无代码行为变化；补齐对称的回落留痕
- WARN 观察钩子（两 harness 对称）：无分配回落时每 daemon 进程一次性 `WARNING` + 事件留痕（不拒 spawn）；10-09 CLI 默认档别名拒识教训的观察面
- run metrics 归因降级标记：回落 run 的 metrics 上下文附 `harness-default` 归因标记（provider=null 形态既有），供计费/健康检查消费侧识别
- **BREAKING**（行为语义，非接口）：`DshSpawnConfigError` 三要素预检不再对「无分配」形态触发——显式传了部分链但仍缺要素的形态仍报错（配置笔误防护保留）

## Capabilities

### New Capabilities

- `harness-default-fallback`: harness 对称的默认 key 回落——无 `agents.models` 分配即按 harness 自身配置启动（claude=环境继承/CLI 默认档；dsh=省略 `--patch` 按 profile 默认档），对称 WARN 留痕与 metrics 归因降级标记

### Modified Capabilities

<!-- 无 spec 级行为变更的既有能力；dsh 显式链渲染行为不变（回归保障见 design） -->

## Impact

- `core/agent_runner/harness/dsh_adapter.py`：预检三处条件放宽 + 省略 patch 路径 + `build_env` 无 apikey 桥接分支
- `core/agent_runner/harness/claude_adapter.py`：回落留痕钩子
- `core/agent_runner/runner.py`：metrics 上下文归因标记
- `tests/test_harness_claude_snapshot.py`、dsh adapter 既有测试：无分配形态新用例 + 既有显式链形态快照回归
- 上游依赖：无（纯适配器层，`add-escalation-chain-admin-arbiter` depends_on 本 SPEC）
