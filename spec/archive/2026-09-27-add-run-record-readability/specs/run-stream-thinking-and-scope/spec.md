## ADDED Requirements

### Requirement: thinking 折叠头带时长与内容预览

静态回放场景下，thinking 折叠头 SHALL 显示：

- 时长：用该 thinking 所在 assistant 事件与下一个 assistant 事件的 `timestamp` 差估算（秒，四舍五入）；下一事件缺失或时间戳缺失时显示「已思考数秒」
- 内容预览：thinking 文本首行（截断至约 40 字符）折叠头格式如「已思考 12 秒 · 先看 queue.py 的派发逻辑…」。

流式场景（思考中）沿用既有「思考中…」展示。展开后 MUST 呈现完整思考全文。

#### Scenario: 有相邻时间戳时显示估算时长

- **WHEN** thinking 块所在 assistant 事件 timestamp 为 05:12:24，下一个 assistant 事件 timestamp 为 05:12:37
- **THEN** 折叠头显示「已思考 13 秒」并附带首行预览

#### Scenario: 无下一事件时间戳时回退

- **WHEN** thinking 块是流的最后一个 assistant 事件（无后续时间戳）
- **THEN** 折叠头显示「已思考数秒」，不显示 NaN 或负数

### Requirement: 思考显示开关与无正文兜底

运行记录面板 SHALL 提供全局「显示思考过程」开关，默认关闭。关闭时 thinking 折叠块不渲染且不打断工具分组。

兜底规则：当 run 流中不存在任何含非空 `text` 块的 assistant 事件时（deepseek 系全程无正文形态），无论开关状态 MUST 渲染 thinking 块，避免界面看似「无 LLM 输出」。

开关状态 SHALL 在会话内保持（组件重挂载不丢失，持久化到 localStorage 可选）。

#### Scenario: 默认关闭时 thinking 隐藏且不断组

- **WHEN** 序列为 Bash、thinking、Bash 且开关为默认关闭
- **THEN** thinking 折叠块不渲染，两个 Bash 聚合为一组

#### Scenario: 全程无正文时强制显示 thinking

- **WHEN** run 流所有 assistant 事件均只有 thinking 块无 text 块，开关为关闭
- **THEN** thinking 折叠块仍然渲染

#### Scenario: 开关打开时恢复显示

- **WHEN** 用户打开「显示思考过程」开关
- **THEN** 全部 thinking 折叠块恢复渲染，显示时长与预览

### Requirement: 运行记录向前分页与总量计数

运行记录面板 SHALL 显示事件计数「显示尾部 N / 共 M 条事件」（N 为当前已加载条数，M 为 run 流总事件行数）。

面板 SHALL 提供「加载更早事件」操作：每次向前加载一批事件（默认批大小 300），新加载内容追加在现有内容之前，重复操作可到达流的开头；已到达开头时操作置为不可用。加载期间 MUST 展示加载态且不丢失已渲染内容与滚动位置的主体。

后端 run 流读取 SHALL 支持窗口化读取：`getRunTail` 既有语义不变（缺省取尾部 max_lines 条），新增向前翻页参数（返回指定窗口的事件与总行数），`stderr` 行容错语义沿用。

#### Scenario: 默认显示尾部窗口与计数

- **WHEN** run 流共 1499 条事件，面板以默认 tail=300 打开
- **THEN** 面板显示「显示尾部 300 / 共 1499 条事件」

#### Scenario: 加载更早事件

- **WHEN** 用户在上述状态点击「加载更早事件」
- **THEN** 面板加载并前置追加此前 300 条（计数变为「显示 600 / 共 1499 条」），且先前的渲染内容不丢失

#### Scenario: 到达流开头后操作不可用

- **WHEN** 用户连续向前翻页直至覆盖流首条事件
- **THEN** 「加载更早事件」置为不可用态，计数显示「显示 1499 / 共 1499 条」

#### Scenario: 后端窗口读取兼容既有语义

- **WHEN** 以既有参数调用 run tail 读取接口
- **THEN** 返回行为与改造前一致（尾部 max_lines 条 + status），新增翻页参数缺省时不影响既有消费方
