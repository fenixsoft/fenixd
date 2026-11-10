## Why

现行模型已支持图像输入，读图不再需要拦截。上一轮已移除项目级提示词中的「当前模型无法读图」描述，但两条车道上的读图拦截守卫仍在实际阻断读图：fenix 主车道经 `.fenix/agent-settings.json` 注册的 PreToolUse hook `block-image-read.py`，以及 dsh 通道 `dsh-bundle` 的等价读图守卫。守卫行为与真实模型能力相悖，误导 agent 回避合法读图，需整体退役。

## What Changes

- **BREAKING** 移除 dsh-bundle 读图拦截守卫（`dsh-bundle/src/guards.ts`）：read/read_image 图片类目标不再被阻断；「三守卫等价」契约收缩为「两守卫等价」，主树写守卫与场景批处理守卫语义不变。
- 移除 fenix 主车道读图 hook：删除 `.fenix/hooks/block-image-read.py`、`.fenix/agent-settings.json` 去除 Read 拦截项。二者为 gitignored 运行时文件，不可写入 SPEC 任务/Deliverables（worktree 不可达 + 主树只读），归 SPEC 合并后的主树人工收尾。
- 清理 `core/agent_runner` 中对 block-image-read 的过时注释/docstring；hook 复制逻辑本身通用（整体复制 agent-settings hooks），保留不动。
- 更新 `dsh-bundle/README.md` 与 `docs/help/07-safeguards.md` 的守卫清单（三守卫→两守卫），记录退役缘由（模型已支持图像输入）。
- 知识页 `fenix-dsh-bundle`（「三守卫等价」规则）由知识蒸馏管线随实现收尾更新，不在本 SPEC 内手改。

## Capabilities

### New Capabilities

（无——本 SPEC 为既有守卫能力的收缩退役，不引入新能力）

### Modified Capabilities

- `fenix-dsh-bundle`: 「三守卫等价」requirement 收缩为「两守卫等价」——移除读图拦截 requirement 语义与对应 scenario；守卫先于审批策略生效、主树写守卫双 env 消费、场景批处理校验等其余语义不变。
- `agent-llm-isolation`: 「隔离不丢失 agent 依赖的插件与技能」requirement 中「PreToolUse hooks（block-image-read）保留」的过时指称更新为按 agent-settings 现有配置保留；隔离保留插件/技能/钩子的语义本身不变。

## Impact

- 代码：`dsh-bundle/src/guards.ts`、`dsh-bundle/src/index.ts`、`dsh-bundle/tests/guards.test.ts`、`core/agent_runner/harness/claude_adapter.py`、`core/agent_runner/runner.py`
- 文档：`dsh-bundle/README.md`、`docs/help/07-safeguards.md`
- 运行时（人工收尾，不在任务内）：`.fenix/hooks/block-image-read.py` 删除、`.fenix/agent-settings.json` Read 项移除、dsh bundle 主树重建重装
- 行为影响：两车道 agent 恢复读图能力；主树写拦截与场景批处理守卫零回归
