<!-- knowledge: capability=run-cancel rev=3
     sources=spec/archive/2026-09-10-add-run-cancel,spec/archive/2026-09-14-fix-run-cancel-retry-flag-miss,spec/archive/2026-10-04-evo-add-run-stop-loss -->

# run 人工取消

run 粒度的人工终止原语与全链路取消语义：进程终止、产物终态、调度 hold-state、跨进程信号与界面入口。

## 现行规则

- `AgentRunner.cancel_run(run_id, reason, by)` 为外部专用终止原语，仅供 dashboard API / 文件信号消费方调用；状态机及一切自动链路（transition、recovery、stuck auto-recovery、gate、freeze）不得调用。方法自身不执行任何状态转换、不写任何 spec 的 status 字段。
- run_id 归一化：登记与消费共用同一归一化，剥掉尾部**连续多组** `-a<N>`（attempt）与 `-r<N>`（瞬态重试）后缀后按基础 run_id 匹配；对带 `-r<N>` 后缀的在飞子 run 登记取消同样被持有线程的轮询环消费并终止子进程。目标 run 无活跃 attempt 时返回结构化 `not_running`（不抛异常）并仍按 base_run_id 登记取消旗标（返回值附 `flag_registered: true`），attempt 间隙的取消对随后复活/重派的 attempt 同样生效；有活跃 attempt 时登记取消旗标并立即返回 `cancel_requested`，终止动作由持有该 run 的线程完成（调用线程不做跨线程 kill）。
- 终止序列：`_run_claude` 轮询环（缺省 1s 粒度）命中旗标后按序执行——SIGTERM（terminate）→ 等待最多 `AGENT_TERMINATE_GRACE_SECONDS`（10s）→ 仍未退出则 SIGKILL → 向 run jsonl 追加终态行 `{"type": "cancelled", reason, by, timestamp}` → 抛专用异常 `RunCancelledError`。cancelled 终态行与 `interrupted`（daemon 关停）、`error`（超时/失败）类型互斥，读侧按 type 区分终止来源。
- 不重试不计秒挂：attempt 循环每轮派发前检查取消旗标，命中立即返回（不派发本 attempt、不创建 worktree）；`RunCancelledError` 在通用 `Exception` 之前单独捕获——不进重试循环、不调秒挂计数（与框架主动 SIGTERM 同待遇）、不触发 provider 链切换；结果为 `AgentRunResult(success=False, cancelled=True, error 含 "cancelled by admin")`，`cancelled` 字段随 `to_dict` 序列化；run 收尾时清理该 run 的取消旗标防泄漏。
- dispatch hold-state 处置：implementer/fast-track/verifier/repair 各分支对 `cancelled=True` 的 run 结果只更新该 spec 的 `error` 字段（含「run 被人工取消」及 reason）——不翻转 status、不增减 `_retry_count`、不更新 `_merge_fp`/`_merge_streak`、不入队重派；后续重排交给 stuck 检测/恢复扫描或管理员人工操作。
- 跨进程文件信号：dashboard data 层原子写（临时文件 + rename）`.fenix/cancel_run_request.json`（run_id/reason/source/created）；已存在未消费请求时拒绝并返回结构化冲突结果（API 409，不覆盖既有请求）。daemon 主循环每轮读取 → 删除 → 校验 run_id 非空 → 调用 `cancel_run`；损坏 JSON 的信号文件被删除且不阻塞主循环；删除失败（并发消费）本轮跳过、下轮再试。
- dashboard 入口：`POST /api/run-cancel?project=<name>&run_id=<id>`（可选 `reason`）——项目不存在 404、run_id 缺失 400、受理 200 `{"requested": true}`、已有待消费请求 409。runs 列表为活跃 run 提供「终止」操作，点击后弹确认弹窗（展示 run_id + 可选 reason 输入），确认才发起请求，受理后给可感知反馈。
- 审计留痕：`cancel_run` 返回 `cancel_requested` 后向 admin_alerts 追加一条 `severity="minor"`、`signal_type="run_cancelled"` 的审计记录（含 run_id、spec（可解析时）、reason 与 by）。

## 溯源

- 2026-09-10 add-run-cancel（spec/archive/2026-09-10-add-run-cancel） — 确立 cancel_run 原语与归一化匹配、cancelled 终态行、attempt 链不重试不计秒挂、dispatch hold-state、文件信号入口、dashboard API 与审计留痕
- 2026-09-14 fix-run-cancel-retry-flag-miss（spec/archive/2026-09-14-fix-run-cancel-retry-flag-miss） — 旗标归一化扩展为剥离连续多组 `-a<N>`/`-r<N>` 后缀，补齐瞬态重试轮在飞 run 的取消覆盖
- 2026-10-04 evo-add-run-stop-loss（spec/archive/2026-10-04-evo-add-run-stop-loss） — not_running 分支改为仍按 base_run_id 登记取消旗标（attempt 间隙取消不再放行复活 attempt），返回值附 flag_registered
