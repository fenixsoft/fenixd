<!-- knowledge: capability=run-cancel rev=4
     sources=spec/archive/2026-09-10-add-run-cancel,spec/archive/2026-09-14-fix-run-cancel-retry-flag-miss,spec/archive/2026-10-04-evo-add-run-stop-loss,spec/archive/2026-10-30-evo-add-run-cancel-wip-checkpoint -->

# run 人工取消

run 粒度的人工终止原语与全链路取消语义：进程终止、取消前现场保全、产物终态、调度 hold-state、跨进程信号与界面入口。

## 现行规则

- `AgentRunner.cancel_run(run_id, reason, by)` 为外部专用终止原语，仅供 dashboard API / 文件信号消费方调用；状态机及一切自动链路（transition、recovery、stuck auto-recovery、gate、freeze）不得调用。方法自身不执行任何状态转换、不写任何 spec 的 status 字段。
- run_id 归一化：登记与消费共用同一归一化，剥掉尾部**连续多组** `-a<N>`（attempt）与 `-r<N>`（瞬态重试）后缀后按基础 run_id 匹配；对带 `-r<N>` 后缀的在飞子 run 登记取消同样被持有线程的轮询环消费并终止子进程。目标 run 无活跃 attempt 时返回结构化 `not_running`（不抛异常）并仍按 base_run_id 登记取消旗标（返回值附 `flag_registered: true`），attempt 间隙的取消对随后复活/重派的 attempt 同样生效；有活跃 attempt 时登记取消旗标并立即返回 `cancel_requested`，终止动作由持有该 run 的线程完成（调用线程不做跨线程 kill）。
- 终止序列：`_run_claude` 轮询环（缺省 1s 粒度）命中旗标后按序执行——SIGTERM（terminate）→ 等待最多 `AGENT_TERMINATE_GRACE_SECONDS`（10s）→ 仍未退出则 SIGKILL → 取消收口前 WIP 现场保全（见下条）→ 向 run jsonl 追加终态行 `{"type": "cancelled", reason, by, timestamp}` → 抛专用异常 `RunCancelledError`。cancelled 终态行与 `interrupted`（daemon 关停）、`error`（超时/失败）类型互斥，读侧按 type 区分终止来源。
- 取消收口前现场保全：取消旗标命中且当前 attempt 持有专属 worktree 时，在 terminate/grace/kill 序列完成（agent 已被终止、可证明不再写盘）后、构造收口异常前，经强杀保全助手执行一次 WIP checkpoint——锚点 `cancel`，提交消息 `fenix(wip): checkpoint cancel <spec>`，便于审计区分「用户取消但现场已保全」。保全必须经该助手接入（自带主树排除），不得直连 checkpoint 提交内核——内核缺省不含主树排除，spec-review/dispute-judge 等主树车道被取消时会把主树无关脏状态卷进主分支提交。`RunCancelledError` 收口分支兜底：worktree 路径仍在作用域时再补一次（早于任何分型清理，空变更自动跳过、幂等）；attempt 顶部取消的终态分型收口对不保留的 worktree 同样在 `cleanup(success=False)` 前先保全。checkpoint 失败仅 WARNING 降级，不阻断、不延迟取消收口。attempt 间隙（无 worktree 载体）与主树车道（cwd 即主工作树）无现场可保全，跳过保全直接按既有取消收口。
- 不重试不计秒挂：attempt 循环每轮派发前检查取消旗标，命中立即返回（不派发本 attempt、不创建 worktree）；`RunCancelledError` 在通用 `Exception` 之前单独捕获——不进重试循环、不调秒挂计数（与框架主动 SIGTERM 同待遇）、不触发 provider 链切换；结果为 `AgentRunResult(success=False, cancelled=True, error 含 "cancelled by admin")`，`cancelled` 字段随 `to_dict` 序列化；run 收尾时清理该 run 的取消旗标防泄漏。
- dispatch hold-state 处置：implementer/fast-track/verifier/repair 各分支对 `cancelled=True` 的 run 结果只更新该 spec 的 `error` 字段（含「run 被人工取消」及 reason）——不翻转 status、不增减 `_retry_count`、不更新 `_merge_fp`/`_merge_streak`、不入队重派；后续重排交给 stuck 检测/恢复扫描或管理员人工操作。
- 跨进程文件信号：dashboard data 层原子写（临时文件 + rename）`.fenix/cancel_run_request.json`（run_id/reason/source/created）；已存在未消费请求时拒绝并返回结构化冲突结果（API 409，不覆盖既有请求）。daemon 主循环每轮读取 → 删除 → 校验 run_id 非空 → 调用 `cancel_run`；损坏 JSON 的信号文件被删除且不阻塞主循环；删除失败（并发消费）本轮跳过、下轮再试。
- dashboard 入口：`POST /api/run-cancel?project=<name>&run_id=<id>`（可选 `reason`）——项目不存在 404、run_id 缺失 400、受理 200 `{"requested": true}`、已有待消费请求 409。dashboard 上的 run 取消入口一律二次确认且确认控件带危险（danger）标识：runs 列表为活跃 run 提供「终止」操作，点击后弹确认弹窗（展示 run_id + 可选 reason 输入），确认才发起请求；项目页质量分面的「取消」按钮同样先弹 danger 确认框、确认后才调用取消 API（错误处理按 `ApiError.code` 稳定错误码分支，不做展示文案子串匹配）。受理后均给可感知反馈。
- 审计留痕：`cancel_run` 返回 `cancel_requested` 后向 admin_alerts 追加一条 `severity="minor"`、`signal_type="run_cancelled"` 的审计记录（含 run_id、spec（可解析时）、reason 与 by）。recommended_action 如实描述现场去向：取消收口前已尽力执行 WIP checkpoint（未提交改动以锚点 cancel 提交进入 attempt 分支，可从分支恢复；无 worktree 载体或主树车道则无保全）；worktree 目录去向按车道——fast-track/transient 等车道经 keep_for_reuse 登记为复用遗产保留（宽限期后回收），其余车道维持既有收口处置，分支与 wip 提交不受影响。

## 溯源

- 2026-09-10 add-run-cancel（spec/archive/2026-09-10-add-run-cancel） — 确立 cancel_run 原语与归一化匹配、cancelled 终态行、attempt 链不重试不计秒挂、dispatch hold-state、文件信号入口、dashboard API 与审计留痕
- 2026-09-14 fix-run-cancel-retry-flag-miss（spec/archive/2026-09-14-fix-run-cancel-retry-flag-miss） — 旗标归一化扩展为剥离连续多组 `-a<N>`/`-r<N>` 后缀，补齐瞬态重试轮在飞 run 的取消覆盖
- 2026-10-04 evo-add-run-stop-loss（spec/archive/2026-10-04-evo-add-run-stop-loss） — not_running 分支改为仍按 base_run_id 登记取消旗标（attempt 间隙取消不再放行复活 attempt），返回值附 flag_registered
- 2026-10-30 evo-add-run-cancel-wip-checkpoint（spec/archive/2026-10-30-evo-add-run-cancel-wip-checkpoint） — 取消收口前新增 WIP 现场保全（锚点 cancel，经强杀保全助手带主树排除，失败降级不阻断；RunCancelledError 收口与终态分型清理前兜底，attempt 间隙/主树车道跳过）；取消审计文案如实化（三句失实旧表述全部废除：取消路径无保全、未提交现场随清理丢弃、失败 implementer 登记 legacy 保留）；QualityTab 取消按钮补 danger 二次确认
