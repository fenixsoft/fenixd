## MODIFIED Requirements

### Requirement: 评审结论的机械消费

框架 SHALL 在评审 run 收工并通过结果硬门与写入边界校验后，按 `status` 机械收口，MUST NOT 交由 LLM 二次解释：

- `approved` → `transition(spec, "ready")`，随后直调 `_on_spec_ready(spec)` 进入实现调度。
- `repaired` → 同上（`transition ready` → 直调 `_on_spec_ready`）。
- `rejected` → `transition(spec, "blocked")`，并把 `findings` 中 `severity: blocking` 条目的 `aspect` / `detail` / `evidence` 摘要写入 STATE 的 `error` 字段，前缀为 `spec-review-rejected:`。

收口动作 MUST 与既有晋升成功路径同语义（直调 `_on_spec_ready` 而非依赖事件循环），保证晋升后立即进入实现调度。

**执行模型**：评审 run SHALL 经**派发队列**在独立 worker 线程中异步执行，与 implementer 同构。`dispatch_review` 的「锚点先落盘 → 快照 → 执行 → 机械收口」四步链 SHALL 保持完整——四步 MUST 在同一调用栈内闭合（收口依赖本轮 attempt 的 `run_started_at` 做结果新鲜度校验），但该调用栈 MUST NOT 是调用方线程：派发入口 MUST 在入队后立即返回。

四步链内的执行异常 MUST 走与其它 agent 类型相同的失败回滚路径（`_rollback_failed_dispatch`），MUST NOT 静默吞掉。

#### Scenario: approved 收口到 ready

- **WHEN** 评审结论为 `approved` 且校验通过
- **THEN** 状态变为 `ready`，随即派发 implementer 调度

#### Scenario: repaired 收口到 ready

- **WHEN** 评审结论为 `repaired` 且校验通过
- **THEN** 状态变为 `ready`，SPEC 目录保留评审者的修补，随即派发 implementer 调度

#### Scenario: rejected 收口到 blocked

- **WHEN** 评审结论为 `rejected`
- **THEN** 状态变为 `blocked`，`error` 字段以 `spec-review-rejected:` 开头并含 blocking 条目的维度与证据摘要

#### Scenario: 不进入实现调度

- **WHEN** 评审结论为 `rejected`
- **THEN** MUST NOT 派发 implementer，MUST NOT 执行 `_on_spec_ready`

#### Scenario: 派发入口不阻塞调用线程

- **WHEN** 任一触发通道（启动期全量扫描、STATE watcher、周期扫描、定时拾取唤起）请求派发评审
- **THEN** 该调用 SHALL 在入队评审条目后立即返回，MUST NOT 等待评审 run 收工

#### Scenario: 收口依赖的 attempt 基准不丢失

- **WHEN** 评审 run 在 worker 线程中执行完毕并进入机械收口
- **THEN** 结果硬门的 mtime 新鲜度校验 SHALL 使用本轮 attempt 的启动时刻作为基准，与四步链闭合于同一调用栈时行为一致

#### Scenario: worker 内异常走统一回滚

- **WHEN** 评审 run 在 worker 线程中抛出未捕获异常
- **THEN** 系统 MUST 调用 `_rollback_failed_dispatch` 收口滞留状态，MUST NOT 让 spec 停留在 `reviewing` 且无锚点、无 error

### Requirement: 评审故障的重试与标记

评审 run 未通过结果硬门或写入边界校验时，本**轮**评审 SHALL 判定为「未完成」，MUST NOT 被归入任何评审结论（尤其 MUST NOT 按 `approved` 放行）。框架 SHALL 递增内部字段 `_review_attempts` 并重试，累计尝试上限为 3 次（首次派发 + 最多 2 次重试）。达到上限后 SHALL `transition(spec, "blocked")` 并把失败原因写入 `error`，前缀为 `spec-review-incomplete:`。

失败原因 SHALL 具体可辨，至少区分：进程非零退出、结果文件缺失或为空、JSON 非法、`status` 越白名单、mtime 陈旧、`repairs` 路径越界、SPEC 目录外越界写入、`status` 与改动不一致。

**异步化约束**：重试 SHALL 经派发队列重新入队，MUST NOT 在收口线程内递归调用派发入口。重试入队前 MUST 已清除 `reviewer_run` 锚点（否则队列候选筛选会把该条目判定为「已有在飞评审 run」而拒派）。

#### Scenario: 首次失败后重试

- **WHEN** 评审 run 首次未完成
- **THEN** SPEC 保持 `reviewing`，`_review_attempts` 递增、`reviewer_run` 被清空，随后经队列重试派发

#### Scenario: 达上限转 blocked

- **WHEN** 评审 run 累计 3 次尝试均未完成
- **THEN** 状态变为 `blocked`，`error` 以 `spec-review-incomplete:` 开头并含具体失败原因

#### Scenario: 故障不被当作放行

- **WHEN** 评审 run 失败且结果文件缺失
- **THEN** MUST NOT 因「无否决证据」而将 SPEC 放行到 `ready`

#### Scenario: 重试成功后恢复正轨

- **WHEN** 首次评审失败，重试轮返回 `approved` 且校验通过
- **THEN** 状态变为 `ready` 并进入实现调度，`_review_attempts` 清零

#### Scenario: 重试不被在飞锚点阻塞

- **WHEN** content 类失败触发重试入队
- **THEN** 该条目 SHALL 能被队列候选筛选放行（`reviewer_run` 已清空、无在飞评审），MUST NOT 永久滞留在队列中

## ADDED Requirements

### Requirement: 评审的运行不占用实现并发槽位

评审 run 是 SPEC 晋升为 `ready` 的前置门禁，SHALL NOT 占用实现车道的并发名额。

- 评审条目在派发与运行期间 MUST NOT 增减 `_active_runs`。
- 评审条目 MUST NOT 进入 `_active_priorities` / `_active_priority_counts`，因而不参与宽松优先级档位比较，MUST NOT 以「更重要的活动任务」身份阻塞低优先级的实现派发。
- 评审条目 SHALL 以其优先级参与队列内的排序（同档 FCFS），即评审之间仍有确定顺序。
- 评审在飞状态 SHALL 由独立集合 `_active_reviews`（spec 名）登记，出队时置位、worker 收尾时释放；该集合 MUST 由队列锁保护。
- 评审并发 MUST NOT 设置上限（用户决策：评审次数稀疏，每个 SPEC 晋升时一次）。

#### Scenario: 评审不挤压实现派发

- **GIVEN** `agents.max_concurrent` 为 3 且已有 3 个实现 run 在跑
- **WHEN** 一个新 SPEC 完成晋升并需要评审
- **THEN** 评审 run SHALL 正常开始执行，MUST NOT 因实现槽位占满而排队等待

#### Scenario: 评审不被实现挤占

- **GIVEN** 已有多个实现 run 在跑
- **WHEN** 队列中同时存在低优先级的实现条目与评审条目
- **THEN** 评审条目的存在 MUST NOT 改变实现条目的可派发性判定（`min(active_priorities)` 不含评审档）

#### Scenario: 评审在飞状态可观测

- **WHEN** 评审 run 处于在飞状态
- **THEN** 该 SPEC 名 SHALL 出现在 `_active_reviews` 中，评审收尾后 MUST 被移除

#### Scenario: 评审并发无上限

- **WHEN** 多个 SPEC 在同一时间窗口内完成晋升
- **THEN** 各自的评审 run SHALL 无需等待其它评审完成即可开始
