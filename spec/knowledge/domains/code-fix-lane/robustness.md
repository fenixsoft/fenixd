# CR 健壮性缺陷修复批

<!-- knowledge: capability=robustness rev=1
     sources=spec/archive/fix-cr-robustness-1789899978 -->

面向代码审查台账 robustness 类条目的专项修复批，页内固化该类修复落定的现行规则。

## 规则

- 批范围由 code-review 台账选中的 robustness 类条目决定，验收口径为修复提交后对应条目不再出现在 open 列表；批内容随台账选中集变化，本页不固化具体条目清单。

### 超时监督判定对门面契约漂移免疫
- `core/agent_runner/liveness.py` 的 `_supervision_deadline_action` 解析生效 run 超时时，门面 `_effective_run_timeout(agent_type)` 返回 `None`、非数值、非正数，或调用本身抛出异常时，该函数回退 `core.config.RUN_TIMEOUT_FALLBACK_SECONDS`（9000）作为 `run_timeout`（与 `ConfigLoader.supervision_floor` 的派生口径同源，不得手写字面常数），异常不得逃逸出本函数（否则一次 deadline 判定升级为 run thread crashed 终态）。
- 兜底发生时留一条 WARNING 日志（component `agent_runner`，含 `agent_type` 与收到的原始值），保证契约漂移可归因。
- 正常路径（门面返回有效数值）的 `run_timeout` 取值与既有口径逐位一致，`absolute_max_seconds` 兜底与 ERROR 文案数值不变。

## 溯源

- 2026-09-20 fix-cr-robustness-1789899978 — 新建本页：超时监督判定对门面契约漂移免疫（None/非数值/非正数/异常一律回退 9000 兜底 + WARNING 归因，正常路径数值不变）。
