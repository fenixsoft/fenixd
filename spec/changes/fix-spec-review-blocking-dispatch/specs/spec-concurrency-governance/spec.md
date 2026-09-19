## ADDED Requirements

### Requirement: 评审派发的同 spec 单飞守卫

评审 run 经派发队列异步执行后，同一 SPEC  MUST NOT 存在两个并发评审 run。守卫 SHALL 由**两条互补判据**构成，任一命中即拒绝本次派发：

1. `_active_reviews` 集合包含该 SPEC 名（已入队或已出队未收口）；
2. STATE 的 `reviewer_run` 锚点非空（锚点先于 run 启动落盘，覆盖「锚点已写但 run 尚未注册进进程表」的窗口）。

两条判据的生命周期 MUST 与评审 run 对齐：`reviewer_run` 在收口路径（`consume_review_result` 或 `_handle_review_failure`）清除；`_active_reviews` 在 worker 的 `finally` 中释放（保证异常路径也释放）。

守卫 MUST NOT 因异步化而退化——改造前它依赖「调用方线程同步阻塞整个评审期」成立，改造后 MUST 显式覆盖从入队到收口的全窗口。

#### Scenario: 已入队未出队时拒绝重复派发

- **GIVEN** 某 SPEC 的评审条目已入队但尚未出队
- **WHEN** 第二条触发通道（如 STATE watcher 与定时拾取同时到达）请求派发该 SPEC 的评审
- **THEN** 第二次派发 SHALL 被拒绝，MUST NOT 产生第二条评审条目

#### Scenario: 入队窗口内不被双重派发判断穿透

- **GIVEN** 某 SPEC 的评审条目已在 `_active_reviews` 中，但 `reviewer_run` 锚点尚未落盘
- **WHEN** 实现派发入口（`_on_spec_ready`）或队列候选筛选（`_should_defer_for_reviewer`）校验该 SPEC 是否存在在飞评审
- **THEN** 守卫 SHALL 命中并顺延实现派发，MUST NOT 因「锚点仍为空」而跳过判定

#### Scenario: 已出队未落锚点时不被队列静默跳过

- **GIVEN** 某 SPEC 的评审条目刚被 `_process_queue` 出队、`reviewer_run` 锚点尚未落盘
- **WHEN** 任何路径再次触发队列处理
- **THEN** 重复条目 SHALL 按「存在在飞评审」被拒绝，MUST NOT 被判定为「无在飞评审」而重复派发；且合法条目 MUST NOT 因锚点写入晚于该窗口而被永久静默跳过

#### Scenario: run 已启动时拒绝重复派发

- **GIVEN** 某 SPEC 的评审 run 正在执行
- **WHEN** 任一触发通道请求再次派发评审
- **THEN** 派发 SHALL 被拒绝并记录 INFO 日志

#### Scenario: 锚点已写但 run 未注册的窗口被覆盖

- **GIVEN** 评审条目已出队、`reviewer_run` 已写入 STATE，但该 run 尚未注册进 `_running_agents`
- **WHEN** 任一触发通道请求再次派发评审
- **THEN** 派发 SHALL 被拒绝（由 `_active_reviews` 或 `reviewer_run` 判据命中）

#### Scenario: 收口后可再次派发

- **GIVEN** 某轮评审已收口（`reviewer_run` 清除、`_active_reviews` 释放）
- **WHEN** 该 SPEC 因人工重评或自动复评需要再次派发评审
- **THEN** 派发 SHALL 被放行

### Requirement: 在飞评审判据覆盖入队窗口

`reviewer_in_flight` 判定（用于实现派发前的顺延校验）SHALL 在既有分层判据（进程表 → 流文件 → 陈旧锚点）之前，先检查 `_active_reviews`：该 SPEC 出现在集合中即判为在飞。

设置该前置判据的动因：「已入队 → 出队 → `run_spec_review` 首次注册进进程表」之间存在窗口，期间进程表与流文件均判否，会使判定落入 `stale` 分支并诱导调用方清理锚点、放行并发派发。补齐后 `stale` 语义 MUST 仅在「确无在飞评审」时触发。

该前置判据 MUST NOT 被「锚点为空即短路返回」的既有顺序屏蔽：`_active_reviews` 命中时，即使 `reviewer_run` 为空也 SHALL 返回在飞结论（`"queued"`）。

#### Scenario: 入队窗口内判为在飞

- **GIVEN** 某 SPEC 的评审条目已入队，评审进程尚未启动
- **WHEN** 调度器校验该 SPEC 是否存在在飞评审
- **THEN** 判定 SHALL 为「在飞」，实现派发 SHALL 被顺延

#### Scenario: 陈旧锚点语义收窄

- **GIVEN** 某 SPEC 的 `reviewer_run` 非空，但其 run 已终态且该 SPEC 不在 `_active_reviews` 中
- **WHEN** 调度器校验在飞评审
- **THEN** 判定 SHALL 为「陈旧锚点」，按无在飞评审放行并记 WARNING

#### Scenario: 在飞判据不因调用方前置条件失效

- **GIVEN** 某 SPEC 的评审条目已在 `_active_reviews` 中，且其 `reviewer_run` 为空或读取异常
- **WHEN** 调度器校验在飞评审
- **THEN** 判定 SHALL 为「在飞」，MUST NOT 因锚点为空或判定异常而 fail-open 放行并发派发
