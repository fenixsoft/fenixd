## ADDED Requirements

### Requirement: 唤醒信号载体为每 SPEC 一文件

「清空定时拾取」与「激活待激活 SPEC」触发的即时唤醒信号 SHALL 以**每 SPEC 一个
文件**的形式落盘于目录 `.fenix/scheduling_kick/`，文件名 SHALL 为 `<spec>.json`
（`<spec>` 为 SPEC 名）。信号文件内容 SHALL 为 JSON 对象，含 `spec`（SPEC 名）、
`action`（`"clear-start-after"`）、`created`（写入时刻的 UTC ISO8601 时间戳）。

写入 SHALL 为原子操作（临时文件 + `os.replace`），与既有文件信号族同构。临时文件
MUST NOT 以 `.json` 结尾，且 MUST 与目标文件同目录；消费侧 SHALL 只识别 `.json`
后缀的信号文件，MUST NOT 把写入中的临时文件当作信号消费或删除。

写入侧 SHALL 校验 SPEC 名合法性：为空、含路径分隔符（`/`、`\`）、含 `..`
或与文件名规则不符者 MUST 拒绝写入并返回明确错误，MUST NOT 拼接成逃逸目录的路径。
判据 SHALL 复用仓库既有的 kebab-case 权威校验（`core.spec_gen._KEBAB_RE`），
MUST NOT 采用仅覆盖少数已知危险字符的黑名单。

不同 SPEC 的信号 SHALL 互不干扰：任一 SPEC 的写入 MUST NOT 因其它 SPEC 已有
未消费信号而失败或被丢弃。同一 SPEC 重复写入 SHALL 幂等（覆盖自身文件，语义
一致：均为「唤醒该 SPEC」）。

#### Scenario: 两个 SPEC 在同一窗口内先后清空定时

- **WHEN** SPEC A 与 SPEC B 在 daemon 的一次消费周期内先后清空 `start_after`
- **THEN** `.fenix/scheduling_kick/` 下同时存在 `A.json` 与 `B.json`，两次写入均返回成功，
  两个 SPEC 都被即时唤醒（MUST NOT 出现「后写入者被丢弃」）

#### Scenario: 同一 SPEC 重复清空幂等

- **WHEN** 对同一 SPEC 连续两次执行清空定时
- **THEN** 该 SPEC 的信号文件被覆盖（目录中仍只有一个该 SPEC 的文件），两次写入均返回成功

#### Scenario: 非法 SPEC 名拒绝写入

- **WHEN** 写入请求携带含路径分隔符或 `..` 的 SPEC 名
- **THEN** 写入被拒绝并返回明确错误，`.fenix/scheduling_kick/` 外 MUST NOT 产生任何文件

#### Scenario: 原子落盘

- **WHEN** 写入过程中进程被中断
- **THEN** 消费侧可见的要么是完整的合法 JSON，要么是该 SPEC 不存在文件（MUST NOT 出现半写文件）

### Requirement: 写入结果如实回报至调用方与用户

唤醒信号的写入结果 SHALL 被如实上报，MUST NOT 被静默吞掉。

写入助手 SHALL 返回 `{"ok": bool, "file": str|null, "error": str|null}`：成功时
`ok` 为 `true` 且 `file` 为落盘路径；失败时 `ok` 为 `false` 且 `error` 为非空说明。

触发写入的动作函数（`set_spec_start_after` 的清空分支、`activate_spec`）SHALL 在
其返回值中携带唤醒信号的结果（键名 `scheduling_kick`，值同上结构形状）。

Dashboard API（`POST /api/spec-start-after`、`POST /api/spec-activate`）SHALL 把
该结果透出到响应体：写入失败时响应 SHALL 携带非空 `warning` 字段说明「即时唤醒
未生效、将由后续扫描派发」，且 `ok` 仍为 `true`（`start_after` 的变更本身已成功）。
API MUST NOT 在信号写入失败时仍向客户端宣称「立即恢复调度」。

前端在清除定时 / 激活成功后，MUST 依据响应的 `warning` 字段选择文案：无该字段
（写入成功）时提示「立即恢复调度」；有该字段时提示「已清除定时，但即时唤醒信号
写入失败，将由下次扫描（缺省 ≤30 分钟，即 `schedule.poll_interval_minutes`）派发」。

#### Scenario: 信号写入成功时 API 不带警告

- **WHEN** 用户清空某 SPEC 的定时且信号成功落盘
- **THEN** API 响应 `ok` 为 `true` 且不含 `warning` 字段，前端提示「已清除定时，立即恢复调度」

#### Scenario: 信号写入失败时 API 如实告知

- **WHEN** 用户清空某 SPEC 的定时但信号写入失败（如目录不可写）
- **THEN** API 响应 `ok` 为 `true` 且携带非空 `warning` 字段，`start_after` 已置 null

#### Scenario: 前端不宣称未发生的即时派发

- **WHEN** 前端收到带 `warning` 的清除/激活响应
- **THEN** 提示文案说明将由后续扫描派发，MUST NOT 显示「立即恢复调度」

### Requirement: 消费侧逐条消费并兼容旧单文件路径

daemon SHALL 在每次主循环轮询中扫描 `.fenix/scheduling_kick/` 目录下的 `.json` 条目，
对每个信号文件执行「读取 → 按 SPEC 当前状态唤起派发 → 唤起成功后删除」：`drafted` 走晋升链，
其余状态走 `_on_spec_ready`；唤起后立即处理派发队列。逐条消费 SHALL 相互隔离——单条信号处理
异常 MUST NOT 阻止同轮其余信号的消费，且异常者的信号文件 SHALL 保留至下一轮重试。

消费侧 SHALL 兼容存量单文件路径 `.fenix/scheduling_kick_request.json`：该文件存在时
SHALL 按既有语义消费并删除，且与目录条目同受陈旧回收阈值约束（见「陈旧唤醒信号自动回收」
Requirement）。新写入 MUST NOT 再产生该单文件路径。

损坏 / 非法 JSON / 缺少 `spec` 字段的信号文件 SHALL 被删除（防每轮报错卡死），
删除失败时下轮重试。SPEC 已不在 STATE.md 时 SHALL 删除信号并记日志。

#### Scenario: 目录中多条信号在同一轮被消费

- **WHEN** `.fenix/scheduling_kick/` 下同时存在 A.json 与 B.json，daemon 执行一轮消费
- **THEN** 两个 SPEC 均被唤起派发，两个信号文件均被删除

#### Scenario: 单条信号异常不影响其余

- **WHEN** 目录中一条信号唤起过程抛出异常，另一条正常
- **THEN** 正常者照常消费，异常者留待下轮重试，主循环不中断

#### Scenario: 旧单文件路径仍被消费

- **WHEN** 存量项目主树残留 `.fenix/scheduling_kick_request.json`，daemon 执行一轮消费
- **THEN** 该文件被按既有语义消费（唤起其中 `spec`）并删除

#### Scenario: 损坏信号被清理

- **WHEN** 目录中存在内容非法的信号文件
- **THEN** 该文件被删除，主循环不报错卡死

### Requirement: 陈旧唤醒信号自动回收

daemon SHALL 在启动清扫与周期计时段（600 秒节拍，与既有孤儿清扫同时点）对
`.fenix/scheduling_kick/` 目录执行对账回收：

- 信号 `created` 距当前时刻在回收阈值内的条目 SHALL 先行消费（按既有语义唤起）
  再删除——唤醒为幂等操作，重复唤醒被下游 handler 的既有谓词吸收；
- 信号 `created` 早于回收阈值的条目判为陈旧，SHALL 仅删除、MUST NOT 唤起
  （防 daemon 长期停机后的病态集中派发）；该判据同样适用于旧单文件路径
  `.fenix/scheduling_kick_request.json`。

回收阈值 SHALL 为代码常量（值 1 小时），MUST NOT 进入项目配置。

#### Scenario: 启动时清理陈旧信号

- **WHEN** daemon 启动，目录中存在一条 `created` 早于 1 小时的信号
- **THEN** 该信号被删除且不触发任何派发，日志记录清理动作

#### Scenario: 启动时消费新鲜信号

- **WHEN** daemon 启动，目录中存在一条 `created` 在 1 小时内的信号
- **THEN** 该信号被消费（唤起对应 SPEC）后删除，不丢失唤醒

#### Scenario: 阈值不为配置项

- **WHEN** 检查配置 schema 与文档
- **THEN** 回收阈值不出现在任何用户可配置键中
