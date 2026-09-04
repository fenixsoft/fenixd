## ADDED Requirements

### Requirement: 广播增量语义

watcher 的 `state` 事件改为增量形态：`{type:"state", project, specs:[{spec, summary}...], overview:null, details:{spec:detail}}`。
`specs` 仅含变更 spec 的摘要（含新增/删除的 spec，删除以 `summary:null` 标记）；`details` 仅含变更 spec 的详情；
不再全量下发 specs+details+overview。

#### Scenario: 日志追加只推差异
- **WHEN** fenixd.log 追加一条 Transition 记录（无 spec 文件变化）
- **THEN** watcher 广播的 state 事件 payload < 2KB（原 ~100KB），specs 与 details 为空或仅含受影响的 spec

#### Scenario: 单 spec 变更推单条
- **WHEN** 某 spec 的 tasks.md 修改
- **THEN** 广播中 specs 数组仅 1 项且等于该 spec 的实时摘要

#### Scenario: spec 删除推送剔除
- **WHEN** spec 从 STATE.md 移除（或目录被删除）
- **THEN** 广播 specs 数组含 `{spec:<name>, summary:null}` 标记，前端据此从本地表删除

### Requirement: watcher 目录级签名跳层

文件监视改为两级签名：每项目每轮先 stat 顶层数据源集合（STATE.md、spec/changes、.fenix/logs、.fenix/runs、
.fenix/verify-progress、.fenix/admin_alerts.json），目录签名（mtime_ns, size, ctime_ns）未变则跳过整棵子树；
仅对签名变化的目录进入子级枚举（spec 目录级同样签名跳层）。

#### Scenario: 目录未变零文件遍历
- **WHEN** 项目文件全部无变化，watcher 执行一轮 scan_once
- **THEN** 该轮除顶层目录 stat 外不发生任何 spec/changes 内文件级 stat（对 spec 目录级别断言统计）

#### Scenario: 变更检测不丢
- **WHEN** 修改某 spec 的 tasks.md（父目录 mtime 随之更新）
- **THEN** watcher 在 ≤2 扫描周期内检测到并触发该 spec 的增量广播

### Requirement: 目录签名增量规模达成

10000 个 spec 目录时，watcher 单轮文件系统调用次数与 spec 数解耦：
每轮 stat 数 = O(顶层数据源 8 + spec 目录数)，spec 目录级 stat 走页缓存路径 ≤10ms/轮。

#### Scenario: 规模基准
- **WHEN** 构造 1000 个假 spec 目录（含 tasks.md 与空 specs/ 目录）后运行一轮 scan_once
- **THEN** 单轮耗时 <50ms，且未变更的项目不做文件级遍历（以目录签名命中统计断言）