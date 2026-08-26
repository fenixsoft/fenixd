## ADDED Requirements

### Requirement: 项目概览表格表头可点击排序

项目概览页的 SPEC 表格各列表头 MUST 支持点击排序，点击同一表头 MUST 在升序/降序/默认（取消排序）间轮换，并按列语义正确排序：状态按生命周期顺序（drafted→ready→implementing→bug-found→implemented→testing→verified→done→pushed）、名称按字典序、优先级按数值、创建时间按时间、任务进度按完成百分比、验证按已测/总数、耗时按数值、错误按有无。表头 MUST 显示当前排序状态指示（方向箭头）。排序状态 MUST 在页面刷新/SSE 重绘后保持。缺失排序键值的行 MUST 恒排末尾。已按排序键排序后，原有「创建时间倒序」默认排序 MUST 仅在用户未选择任何排序时生效。

#### Scenario: 点击表头升序再降序再取消
- **WHEN** 用户点击「优先级」表头
- **THEN** 表格按优先级升序排列，表头显示升序箭头；再次点击变为降序；第三次点击恢复默认（创建时间倒序），表头不再显示箭头

#### Scenario: 状态列按生命周期排序
- **WHEN** 用户点击「状态」表头
- **THEN** 表格按 drafted→…→pushed 的生命周期顺序排列（如 ready 排在 implementing 之前、done 排在 pushed 之前）

#### Scenario: 缺失值排末尾
- **WHEN** 某 SPEC 无创建时间（created 为空），用户按创建时间排序
- **THEN** 该 SPEC 恒位于列表末尾，不参与升/降序位置

### Requirement: 项目概览新增「耗时」列

项目概览 SPEC 表格 MUST 新增「耗时」列，展示该 SPEC 消耗的总时间。服务端数据聚合 MUST 为该列提供 `total_duration` 字段：等于该 SPEC 全部运行记录（`get_runs` 按 spec 过滤后所有 run，含 implementer/verifier/planner/tester 等）的 `duration_seconds` 求和；无任何运行记录时 MUST 为 0。前端 MUST 以人类可读时长格式渲染（不足 1 分钟显示秒、不足 1 小时显示分秒、1 小时以上显示时分秒），0 时显示「—」。该列 MUST 参与表头排序（按数值）。

#### Scenario: 耗时等于全部运行时长之和
- **WHEN** 某 SPEC 有 3 条运行记录，时长分别为 60s、120s、300s
- **THEN** 该 SPEC 的 `total_duration` 为 480 秒，表格「耗时」列显示「8分」

#### Scenario: 无运行记录显示占位
- **WHEN** 某 SPEC（如草稿）没有任何运行记录
- **THEN** 「耗时」列显示「—」，且排序时按 0 处理

### Requirement: fix-* 规格树状挂载父规格

项目概览 SPEC 表格 MUST 将 fix-* 规格以树状结构显示在对应父规格之下：某规格的父规格通过递归去除其名称前导 `fix-` 得到（如 `fix-add-parallelism` → `add-parallelism`、`fix-fix-add-parallelism` → `add-parallelism`）。子规格行 MUST 缩进渲染并带「🔧」修复标记，父规格行 MUST 正常显示。表格排序 MUST 以根规格为粒度整体排序，子规格行 MUST 跟随其父规格位置不拆散。父规格不存在（孤立 fix，如父已从 STATE.md 移除）的 fix 规格 MUST 归入「无父级」分组，不得作为普通顶层行与真实规格混淆。fix 子规格自身的树关系（fix-fix-* 挂到 fix-* 下）MUST 同样成立。

#### Scenario: fix 规格缩进显示在父规格下
- **WHEN** 项目含规格 `add-parallelism` 与 `fix-add-parallelism`
- **THEN** 表格中 `add-parallelism` 为普通行，`fix-add-parallelism` 在其下方缩进显示并带 🔧 标记

#### Scenario: 多层 fix 递归嵌套
- **WHEN** 项目含 `add-parallelism`、`fix-add-parallelism`、`fix-fix-add-parallelism`
- **THEN** 三者构成两层子树：`fix-fix-add-parallelism` 缩进在 `fix-add-parallelism` 之下，后者再缩进在 `add-parallelism` 之下

#### Scenario: 排序不拆散树结构
- **WHEN** 用户按创建时间对表格排序，`fix-add-parallelism` 的创建时间晚于其它规格
- **THEN** `add-parallelism` 及其子树作为一个整体参与排序，`fix-add-parallelism` 不因自身时间被单独排到别处

#### Scenario: 孤立 fix 归入无父级分组
- **WHEN** 项目存在 `fix-some-parent` 但 `some-parent` 不在 STATE.md 中
- **THEN** `fix-some-parent` 显示在「无父级」分组中，不与正常顶层规格行混淆
