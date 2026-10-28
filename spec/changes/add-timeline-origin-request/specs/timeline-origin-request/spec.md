# timeline-origin-request — SPEC 立项原始一句话需求的持久化与时间轴展示

## ADDED Requirements

### Requirement: 立项原话持久化（request.md）

fenix-new 立项流程 MUST 把用户输入的原始一句话需求原文照录写入 `spec/changes/<name>/request.md`（UTF-8 纯文本，不做工程化改写），该文件随既有 spec 目录提交流程入库，归档时随目录整体迁移。

#### Scenario: fenix-new 立项时写入原话

- **WHEN** 用户经 /fenix-new 提出需求并完成确认（模式/时机），需求 Agent 创建 change 脚手架
- **THEN** `spec/changes/<name>/request.md` 被创建，内容为用户 ARGUMENTS 原文；后续 `git add spec/changes/<name>/` 提交自然包含该文件，无需新增提交逻辑

#### Scenario: --modify 不更新原话

- **WHEN** 用户经 /fenix-new --modify 更新既有 SPEC 的 artifacts
- **THEN** `request.md` 保持立项时刻内容不变（立项原话是历史快照，修改需求走 proposal/tasks 的正常更新）

### Requirement: 时间轴首个状态转移节点下展示原话

SPEC 详情「运行时间轴」数据中，排序与折叠后的**第一个 state 节点** MUST 在其 spec 目录（活跃或归档，经 resolve_spec_dir 解析）存在 request.md 时携带 `origin_request` 字段（内容为 request.md 原文）；前端在该节点内容区的 from→to 状态行下方渲染原话引用块。

#### Scenario: 有 request.md 的 SPEC 首个状态节点附原话

- **WHEN** SPEC 的 spec 目录下存在非空 request.md 且其时间轴含 state 节点
- **THEN** 时间轴数据中第一个 state 节点携带 `origin_request` 字段，值为 request.md 全文；其余 state 节点不携带该字段

#### Scenario: 无 drafted→reviewing 转移的 SPEC 同样展示

- **WHEN** SPEC 走 fast-track 或直接晋升，时间轴首个状态转移为 drafted→ready（无 reviewing）
- **THEN** 原话同样附在首个 state 节点（drafted→ready）上，展示位置规则与存在 reviewing 时一致

#### Scenario: 折叠链首节点同样附着

- **WHEN** 时间轴首个 state 节点是折叠链（chain 字段，如 drafted→ready→implementing 折叠）
- **THEN** origin_request 附在该折叠节点上（前端展示为链上首个转移即 drafted→…的原话）

#### Scenario: 无 request.md 静默降级

- **WHEN** SPEC 目录无 request.md（存量 SPEC、归档旧 SPEC、或绕过 skill 创建的 SPEC）
- **THEN** 时间轴节点不携带 `origin_request` 字段、前端不渲染任何占位，详情接口零报错（fail-open，读取异常同样静默省字段）

#### Scenario: 前端渲染原话引用块

- **WHEN** state 节点携带非空 origin_request 字段
- **THEN** 该节点内容区在状态转移行下方渲染原话引用块，多行原文保留换行完整显示；字段缺失或为空字符串时不渲染任何引用块结构
