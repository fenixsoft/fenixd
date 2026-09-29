# 同 SPEC 评审并发治理（单飞守卫与竞态兜底）
<!-- knowledge: capability=spec-concurrency-governance rev=2
     sources=spec/archive/2026-09-24-evo-spec-concurrency-flight-guard,spec/archive/2026-09-24-fix-spec-review-blocking-dispatch -->

保证同一 SPEC 任一时刻至多一个在飞评审 run，并治理评审与实现车道之间的三处竞态窗口。

## 规则

- 同 SPEC 单飞守卫（两条互补判据，任一命中即拒绝本次评审派发）：
  1. `_active_reviews` 集合包含该 SPEC 名（已入队或已出队未收口）；
  2. STATE 的 `reviewer_run` 锚点非空（锚点先于 run 启动落盘，覆盖「锚点已写但 run 尚未注册进进程表」的窗口）。
- 判据生命周期与评审 run 对齐：`reviewer_run` 在收口路径（`consume_review_result` 或 `_handle_review_failure`）清除；`_active_reviews` 在 worker 的 `finally` 中释放（异常路径也释放）。登记覆盖「条目出队 → 锚点落盘」窗口，锚点落盘后由 `reviewer_run` 接力；登记不得覆盖整个 worker 生命周期——同一 worker 线程内的续 attempt 经 `dispatch_review` 入口重判在飞时必须放行，否则评审被自己挡在门外。
- `reviewer_in_flight` 判定（实现派发前的顺延校验）在既有分层判据（进程表 → 流文件 → 陈旧锚点）之前先查 `_active_reviews`：命中即判在飞（`"queued"`），即使锚点为空也不得因「锚点为空即短路」而 fail-open 放行并发派发；`stale`（陈旧锚点）判定仅在「确无在飞评审」时触发——`reviewer_run` 非空但 run 已终态且不在 `_active_reviews` 中时，判无在飞放行并记 WARNING，不得永久顺延。
- 审核收尾回退守卫：评审 run 收口（approved/repaired）时，在结果硬门与写入边界校验之后、执行回退之前重读 SPEC 当前 status——若已为 `implementing` / `implemented` / `testing`（在飞实现 run 或已进实现后段），不回退 ready，仅记 in-flight 日志并清除 `reviewer_run` 锚点（残留锚点会阻塞后续派发）；跳过回退以 `_` 前缀侧车字段留审计痕迹，且不调用实现派发入口。SPEC 仍处 `reviewing`（无在飞实现）时按既有 reviewing→ready 路径回退并触发实现派发。
- 派发前在飞评审校验：派发 implementer（含 fast-track）前校验同 SPEC 无在飞评审 run；存在时顺延本次派发（不创建实现 run、不写 `error`、不消耗实现尝试预算），待评审收尾事件经既有 `_on_spec_ready` 重触发通道重判；校验同时覆盖 `_on_spec_ready` 与 dispatch 队列候选筛选两处入口。
- 合并收尾 ready 态兜底：实现 run 合并完成推进状态时，若 SPEC 当前 status=ready（因评审收尾竞态被回退过），先补记合法转移 `ready → implementing`、再执行既有 `implementing → implemented`，严禁以 `ready → implemented` 非法转移报错；补记留审计痕迹（WARNING 日志 + 项目日志），不静默吞掉。
- 兜底仅由实现 run 的合并收尾路径调用（implementer / repair / fast-track 三条落点）；文档或管理操作合并不触发兜底——非法转移仍被拒绝，暴露真实异常。

## 溯源

- [2026-09-24 2026-09-24-evo-spec-concurrency-flight-guard](spec/archive/2026-09-24-evo-spec-concurrency-flight-guard/) — 新增并发治理：审核收尾回退守卫、派发前在飞评审校验（双入口）、合并收尾 ready 态补记兜底与非实现合并不触发
- [2026-09-24 2026-09-24-fix-spec-review-blocking-dispatch](spec/archive/2026-09-24-fix-spec-review-blocking-dispatch/) — 评审异步化后的单飞守卫补全：`_active_reviews` + `reviewer_run` 双判据、在飞判据前置覆盖入队窗口、陈旧锚点语义收窄
