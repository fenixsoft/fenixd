## Context

`improve-dashboard-sections` 的 re-verify 连续两次因 `claude CLI Max turns (150) reached` 失败：每次 attempt 都新建 worktree、agent 上下文全新，32 个验证场景无法在 150 轮内完成，且已完成的场景全部作废重跑（每次约 13 分钟）。现状：

- `agents.max_turns` 硬编码在 `.fenix/config.yaml:13`（150），代码 fallback 为 50（`agent_runner.py` 两处 `_get_config("agents.max_turns", 50)`）。
- `verify-progress/<spec>.json` 仅由 verifier agent 按提示词（`agent_runner.py` verifier prompt）写入，框架（core/ 下无任何 `verify-progress` 引用）从不读取，因此重试时无从续跑。
- Dashboard 配置页「并行度设置」区块（`static/app.js:1460` 起）已支持 `agents.max_concurrent` 可视化编辑，受管子键清单位于 `core/dashboard/data.py:1114`（`_AGENTS_MANAGED_SUBKEYS`）。

## Goals / Non-Goals

**Goals:**
- `agents.max_turns` 默认值统一为 300（config 显式值 + 代码 fallback）。
- Dashboard 配置页可编辑 max_turns，与并行度并列，复用既有保存链路。
- verifier 重试从 progress 文件断点续跑：注入 done/total/current，从 done+1 场景继续。

**Non-Goals:**
- implementer / planner 的断点续跑（范围仅 verifier）。
- 跨 attempt 保留 worktree 或浏览器验证证据（截图/报告仍以本 attempt 新产生为准）。
- 修改 planner 场景文件的生成与校验逻辑。

## Decisions

### D1: verifier 断点以「进度注入」实现，而非复用 worktree

在 `_build_prompt` verifier 分支构造提示词时，读取 `.fenix/verify-progress/<spec>.json`：文件存在、可解析、`done > 0` 时，插入断点段落（total/done/current），并把进度初始化指令由「Step 0 写 done=0」改为「Step 0 写 done=<断点>」；场景总数沿用断点 total，逐场景递增。文件缺失、done=0 或 JSON 损坏 → 无断点，全新开始。损坏文件移除或忽略，不阻塞 attempt。

**替代方案**：复用上次 worktree（保留运行环境）。弃用原因：worktree 每次重建是既定安全策略（干净基线），且 agent 上下文无法跨进程保留，环境复用的收益有限、状态管理复杂。

### D2: max_turns 通过既有配置链路扩展，不新建配置块

沿用 `agents` 受管配置模型：`ConfigLoader` 校验继续覆盖 `max_turns`（正整数），代码 fallback 从 50 改为 300；`.fenix/config.yaml` 现值 150 → 300；`core/dashboard/data.py` 的 `_AGENTS_MANAGED_SUBKEYS` 增加 `"max_turns"`，`_SOURCE_KEYS` 同步；`static/app.js` 配置表单在并行度输入框旁增加 max_turns 输入框，保存逻辑把 `agents.max_turns` 纳入回写对象。

**替代方案**：为 max_turns 单独建配置区块/路由。弃用原因：与现有配置编辑基础设施重复，且用户要求「放到并行度设置中」，同区块编辑最贴合。

### D3: 断点语义为「场景序号单调累积」

续跑时 `total` 保持断点值（不重数场景），`done` 单调不减，首个进度写入以断点值为起点。全部完成后 `done=total` 并正常写 `.fenix-run-result.json`（保持现有状态机链路：verified / bug-found）。

## Risks / Trade-offs

- [断点注入说明不准确导致 agent 误判跳过] → 提示词强调「跳过已完成场景，从 done+1 继续」，并以清晰格式列出当前场景描述。
- [重试次数耗尽后残留半新 progress 干扰下次 SPEC 验证] → 每次 attempt 开始时以文件实际的 done 为准读取；验证入口（pm_engine 派发前）可对已完成 SPEC 的 progress 做清理，保持幂等。
- [max_turns=300 使单次运行最长耗时变长（约 2 倍）] → 300 是「上限」而非目标值，强杀保护仍在（超时、强杀逻辑不变）；对 32 场景级别验证为合理预算。
- [不同 attempt 的 done 递增依赖 agent 如实写 progress] → 提示词强制要求，且重试失败后错误信息仍会显式报出 Max turns，便于人工核验。

## Migration Plan

1. 部署时同步修改 `.fenix/config.yaml`（max_turns 150 → 300）与代码默认值，避免新旧配置并存歧义。
2. 行为向后兼容：未配置时默认 300；已有显式配置不受影响。
3. 回滚：恢复 max_turns 旧值、移除 progress 注入段落即可，不涉及数据迁移。

## Open Questions

- 是否需要为 planner 生成的 `test_scenarios.json` 也做跨 attempt 复用（当前非目标，验证器续跑基于 progress JSON 已可覆盖）。