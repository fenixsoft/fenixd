# dashboard-read-path-performance

## MODIFIED Requirements

### Requirement: SPEC 摘要索引缓存随 STATE 变化全量失效

（原语义，来自 `dashboard-spec-summary-index`：索引在 STATE 签名变化时丢弃全部缓存并全量重建。）

现改为：`SummaryIndex` 在 STATE.md 签名变化时 MUST **保留既有 spec 缓存条目**，仅对以下三类 spec 重算：新增的、已删除的、或其自身状态/依赖签名发生变化的。全量重建 MUST 仅用于索引损坏或首次构建场景。

#### Scenario: STATE 变化不触发全量重建

- **WHEN** 220 个 spec 中仅 1 个 spec 的状态发生变化，STATE.md 签名随之变化
- **THEN** 本次 `SummaryIndex.get` 只重算该 1 个 spec，其余 219 个复用缓存

#### Scenario: 缓存结果与全量重建等价

- **WHEN** 对同一 STATE 快照分别走「增量重算」与「全量重建」两条路径
- **THEN** 两者产出的 spec 摘要集合逐条一致

#### Scenario: 仅 STATE 条目字段变化也必须重算

- **WHEN** 某 spec 的依赖文件签名（tasks.md / .spec.yaml / specs/ / verification-report.md / verify-progress / config.yaml / 该 spec 的 run 产物）全部未变，仅 STATE.md 中该 spec 的条目字段（如 `status`、`error`、`frozen_until`）发生变化
- **THEN** 该 spec MUST 被重算，摘要中的 `status` 等由条目派生的字段 MUST 反映新值，MUST NOT 返回陈旧摘要

> 说明：本条不可由「缓存结果与全量重建等价」替代——后者是同快照对比，两条路径读同一 `entry`，即便漏了条目指纹也必然一致。现状依赖文件签名集合（`core/dashboard/data.py:2937` `_spec_dep_sigs`）不含 `entry` 内容，而摘要输出由 `entry` 决定（`data.py:2819` `spec_summary`），故「条目变、文件未变」是必须独立覆盖的场景。

#### Scenario: 首次构建与损坏回退

- **WHEN** 索引为空（首次）或检测到索引损坏
- **THEN** 执行一次全量重建

### Requirement: 每个 spec 摘要独立扫描 runs 目录

（原语义：`spec_summary` 各自 glob runs 与 archive 目录再按名过滤。）

现改为：`spec_summary` MUST 复用已预扫描的 `_runs_by_spec_sigs` 映射（每个目录每轮只 glob 一次），MUST NOT 为每个 spec 重新遍历整个 runs 目录。

#### Scenario: 单轮只扫一次目录

- **WHEN** 计算 N 个 spec 的摘要
- **THEN** runs 目录的 glob 次数为常数（不随 N 增长）

### Requirement: run 元数据尾读为全文件读取

（原语义：`_read_run_lines` 逐行读完整个 run 文件以取末 N 行。）

现改为：`_read_run_lines` MUST 优先从文件尾部按字节窗口 seek 读取，仅在窗口内无法取得完整末 N 行（行长超过窗口）时回退全量逐行读取。正确性约束不变：MUST NOT 从行的中间截断导致末行被误解析（避免把已完成 run 误判为 running）。

#### Scenario: 大文件尾读不全读

- **WHEN** 对 12MB 的 run 文件取末 3 行
- **THEN** 读取的字节量不超过尾部窗口大小（行长未超窗时），结果与全量读取一致

#### Scenario: 超长末行回退且不误判

- **WHEN** 末行长度超过字节窗口
- **THEN** 回退全量读取并正确解析末行，`classify_run` 判定与全量读取一致

### Requirement: runs 产物保留上限未生效

（新增/修正语义。）

配置项 `runs.keep` MUST 有真实消费点：daemon 周期任务 MUST 将终态 run 产物移入归档，并按配置数量上限清理归档。当前实现中 `runs.keep` 无任何消费者、runs 目录无界增长，属缺陷。

上限语义 MUST 明确：`runs.keep` 约束的是**归档目录条目数**（活跃 runs 目录的有界性由「终态即移出」保证）。清理 MUST 记录日志（删除数量与条目名可追溯），MUST NOT 静默大批量删除——缺省上限 50、当前归档实测 343 个条目，首次执行会一次删除约 293 个文件，属需可观测的破坏性动作。被删除的归档 run 会影响 `spec_summary` 耗时回退、spec 时间轴与运行历史（`core/dashboard/data.py:2824`/`:3416`/`:3686`、`core/pm_engine/engine.py:621`）；终态 spec 有 STATE 固化耗时不受影响，非终态 spec 的历史视图会缩水，此取舍须在实现记录中确认。

#### Scenario: 终态 run 被归档

- **WHEN** run 进入终态且 daemon 周期任务运行
- **THEN** 该 run 产物被移入归档目录，活跃 runs 目录条目数不无界增长

#### Scenario: 归档按上限清理

- **WHEN** 归档目录条目数超过 `runs.keep` 上限
- **THEN** 最旧的条目被清理

#### Scenario: 清理动作可观测

- **WHEN** daemon 周期任务清理归档条目
- **THEN** 日志记录本次删除的条目数量（条目名可追溯），且单轮删除量有上限或分批，不出现静默大批量删除

#### Scenario: 注释与实现一致

- **WHEN** 审阅 watcher 中关于 runs 保留数量的注释
- **THEN** 注释描述与 `runs.keep` 的实际生效行为一致
