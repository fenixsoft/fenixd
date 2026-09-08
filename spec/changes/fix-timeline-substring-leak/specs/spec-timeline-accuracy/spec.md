# spec-timeline-accuracy —— SPEC 详情时间轴名称隔离与方向保真

## ADDED Requirements

### Requirement: 时间轴日志行按 spec 名精确匹配

`get_spec_timeline` 解析 daemon 日志时 MUST 按完整 spec 名精确匹配行归属：`Updated SPEC` 行 MUST 以带引号的全名形态（`'<spec_name>'`，与 state_machine 日志文案一致）判定；`Transition:` 行 MUST 维持「名字后紧跟空白」的正则锚定。前缀名 spec（如 `add-foo`）MUST NOT 吸收更长名字姊妹 spec（如 `add-foo-ui`）的任何状态节点；姊妹 spec 自身时间轴 MUST 不受影响。

#### Scenario: 前缀 spec 不吸收姊妹 spec 状态更新

- **WHEN** 日志夹具同时含 `Updated SPEC 'add-foo'`（status=ready）与 `Updated SPEC 'add-foo-ui'`（status=implemented/testing/verified/done/pushed 级联）两类行，对 `add-foo` 调用 `get_spec_timeline`
- **THEN** 产出状态节点不包含任何源自 `-ui` 更新的条目（无 implemented/testing/verified/done/pushed 节点）；对 `add-foo-ui` 调用时其自身级联节点完整在场

#### Scenario: from 推演不被姊妹 spec 污染

- **WHEN** `add-foo` 在取消保持后（status=implementing、error=取消文案）有一条无 Transition 行的恢复直写更新（status=ready、error=Recovered from interrupted state），且日志中另有 `add-foo-ui` 的 pushed 更新在前
- **THEN** `add-foo` 时间轴中该恢复节点 from=implementing、to=ready（非 pushed→ready），reason 为同行 error 精确文案

### Requirement: 状态节点方向字段与回退文案语义

时间轴 state 节点 MUST 携带 `backward` 布尔（按生命周期序判定 to 是否早于 from），`Transition:` 解析与打回重建两条路径统一输出。打回重建分支：回退节点无同行 error 时 MAY 用规则兜底文案；前向节点 MUST NOT 得到「状态回退」类兜底文案——无同行 error 时 reason MUST 为空（可被折叠链合并），有同行 error 时 reason 为该 error 且不视为回退。就近 error 覆写（≤10 分钟）MUST 仅作用于回退节点或带同行 error 的节点。

#### Scenario: 前向直写节点不带回退文案

- **WHEN** 日志夹具含一条无 Transition 行的前向直写更新（如 status=implemented、无 error），且 10 分钟窗口内存在任一带 error 的更新行
- **THEN** 该节点 reason 为空、backward=false，未被就近 error 覆写

#### Scenario: 回退节点保留 reason 与方向（回归）

- **WHEN** 日志夹具含真实回退（Transition 行 testing→implementing，或直写 status=ready 且生命周期序回退）
- **THEN** 节点 backward=true，reason 为同行 error（有则）或规则兜底文案，行为与现状一致

### Requirement: 前端回退徽标按方向渲染

SPEC 详情页时间轴卡片的「↩ 状态回退」徽标 MUST 依据 `backward` 字段渲染（backward=true 才显示）；`backward` 缺失的存量数据 MUST 回退现有 `!!reason` 判定保持兼容。reason 文案展示不随方向变化。

#### Scenario: 带 reason 的前向节点不挂回退徽标

- **WHEN** 某前向 state 节点携带非空 reason（如恢复直写行的精确 error）且 backward=false
- **THEN** 卡片显示 reason 文案但不显示「↩ 状态回退」徽标；backward=true 的节点徽标照常显示
