# turn-limit-lifecycle — 增量规格（续期活性证据 b 的 tool_result 识别修复）

## MODIFIED Requirements

### Requirement: 轮次上限活性感知续期

轮询环判定 run 达到轮次上限时 MUST 按封闭决策矩阵判定续期或终止，不得无差别 kill：run 表现出真实推进活性（判定窗口内分支有新提交，或有新 tool_result 事件流量——后者按 `tool-result-stream-detection` 统一识别，即 `user` 事件包裹 `tool_result` content block 或兼容的顶层 `tool_result` 事件）且续期次数未达封顶时，执行轮次续期（extend 上限量），以 `turn_extension` 事件落 run 产物文件留痕；无活性或续期封顶时才执行 kill + 锚点 C 收口。判定 MUST 与超时路径既有 `_supervision_deadline_action` 封闭矩阵语义同构（extend 有据、封顶有限、每次续期留痕），具体窗口/步长/封顶为配置常量并在 design 固化。流量活性证据 MUST 对真实 stream-json 形态的 tool_result 事件生效（不得因事件类型假设错误而恒判无活性）。

#### Scenario: 健康推进中的 run 获得续期

- **WHEN** run 达到 400 轮上限，判定窗口内分支有新提交（如 add-ssh-foundation a1 第 378 轮仍在勾选任务、每任务稳定出提交）
- **THEN** 不 kill，轮次上限按固定步长 extend，run 产物文件新增 `turn_extension` 记录（含 extension 序号、步长、活性证据摘要、新上限）

#### Scenario: 仅工具流量活性亦获得续期

- **WHEN** run 达到轮次上限，判定窗口内分支无新提交，但 run 转录尾部存在真实形态的 tool_result 事件（`user` 事件包裹 `tool_result` block，timestamp 落在窗口内）
- **THEN** 判为有流量活性，不 kill，按固定步长 extend 并在 run 产物文件留 `turn_extension` 记录（证据摘要标注 tool_result 流量）

#### Scenario: 无活性 run 直接终止并保全

- **WHEN** run 达到轮次上限且判定窗口内既无新提交也无新 tool_result 流量（如卡死空转）
- **THEN** 执行既有 kill 序列 + 锚点 C 收口 + 既有 turn_limit_error 失败收口，行为与现行一致

#### Scenario: 续期封顶后终止

- **WHEN** run 已连续用尽全部续期次数（封顶），再次触及新上限
- **THEN** 不再 extend，执行 kill + 锚点 C 收口 + 失败收口

#### Scenario: 续期与超时矩阵互不干扰

- **WHEN** run 同时受超时死线与轮次上限约束
- **THEN** 超时路径既有 `_supervision_deadline_action` 行为不变（其 extend 计数与 turn 续期计数相互独立），两者任一命中均按各自矩阵处置
