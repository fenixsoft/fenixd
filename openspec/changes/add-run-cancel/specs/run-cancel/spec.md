# run-cancel 能力规格

## ADDED Requirements

### Requirement: 外部专用 cancel_run 终止原语

AgentRunner SHALL 提供 `cancel_run(run_id, reason="", by="admin")` 方法，作为 run 粒度的人工终止原语。该方法 MUST 满足：

- **仅供外部管理动作调用**（dashboard API / 文件信号消费方）；状态机及一切自动链路（transition、recovery、stuck auto-recovery、gate、freeze）MUST NOT 调用本方法；
- 本方法自身 MUST NOT 执行任何状态转换、MUST NOT 写任何 spec 的 status 字段；
- run_id MUST 做基础归一化：剥掉 `-a<n>` attempt 后缀后再匹配；
- 目标 run 无活跃 attempt 时 MUST 返回结构化 `not_running` 结果，不得抛异常；
- 目标 run 存在活跃 attempt 时 MUST 登记取消旗标并立即返回 `cancel_requested`，终止动作由持有该 run 的线程完成（调用线程不做跨线程 kill）。

#### Scenario: 取消活跃 run 返回 cancel_requested

- **WHEN** 某 spec 的 implementer run 正在运行（`_running_agents` 中存在其 attempt 子进程），外部调用 `cancel_run(<基础run_id>, reason="测试取消")`
- **THEN** 方法返回 `{"status": "cancel_requested"}` 且旗标已登记，返回值中包含命中的活跃 attempt run_id 列表

#### Scenario: 取消已结束的 run 返回 not_running

- **WHEN** 目标 run_id 不存在对应活跃 attempt（run 已完成或从未存在），外部调用 `cancel_run`
- **THEN** 方法返回 `{"status": "not_running"}`，不抛异常，不登记旗标

#### Scenario: attempt 后缀归一化匹配

- **WHEN** 活跃 attempt 的 run_id 为 `<基础run_id>-a2`，外部调用 `cancel_run("<基础run_id>-a2")` 或 `cancel_run("<基础run_id>")`
- **THEN** 两种调用方式均命中同一取消旗标（按基础 run_id 归一化登记）

#### Scenario: cancel_run 不触碰状态机

- **WHEN** 对运行中 spec 的 run 调用 `cancel_run` 并等待 run 收尾
- **THEN** 该 spec 的 STATE.md 条目 status 字段保持取消前的值不变，STATE.md 中不出现任何由 cancel_run 引起的状态改写

### Requirement: 取消终止 attempt 子进程并落 cancelled 终态行

`_run_claude` 轮询环（缺省 1s 粒度）SHALL 在每次迭代检查取消旗标；命中时按序执行：

1. 对子进程发送 SIGTERM（terminate）；
2. 等待最多 `AGENT_TERMINATE_GRACE_SECONDS`（10s，复用既有优雅退出常量），仍未退出则 SIGKILL（kill）；
3. 向该 run 的 jsonl 产物追加终态行 `{"type": "cancelled", "reason": <reason>, "by": <by>, "timestamp": <ISO8601>}`；
4. 抛出专用异常 `RunCancelledError`（在 runner 模块定义，携带 reason）。

`cancelled` 终态行 MUST 与既有 `interrupted`（daemon 关停）及 `error`（超时/失败）终态行类型互斥，读侧可按 type 直接区分三种终止来源。

#### Scenario: 活跃子进程被终止

- **WHEN** 一个正在运行的 claude 子进程（测试用长跑替身进程）所在 run 被登记取消旗标
- **THEN** 轮询环在下一次迭代内对该子进程发送 SIGTERM；子进程在 grace 窗口内退出则不追加 SIGKILL，未退出则被 SIGKILL；`_run_claude` 以 `RunCancelledError` 结束

#### Scenario: jsonl 终态行为 cancelled 行

- **WHEN** 被取消 run 的 jsonl 产物写完终态后读取全部行
- **THEN** 最后一行 JSON 的 `type` 字段为 `"cancelled"`，且包含非空 `reason` 与 `by` 字段；该文件中不存在 `type` 为 `interrupted` 或 `error` 的行（未被其它路径终止时）

### Requirement: 被取消的 run 不重试不计秒挂

`_execute_agent` 重试链 SHALL 满足：

- attempt 循环每轮派发前（现有 frozen 检查同位置）MUST 检查取消旗标，命中则立即返回，不派发本 attempt、不创建 worktree；
- MUST 在通用 `Exception` 处理之前单独捕获 `RunCancelledError`：不进入重试循环、不调用秒挂计数（`_record_instant_fail` 与框架主动 SIGTERM 同待遇被跳过）、不触发 provider 链切换；
- 被取消 run 的返回结果 MUST 为 `AgentRunResult(success=False, cancelled=True, error` 含 `"cancelled by admin"` 字样及 reason`)`；
- run 收尾时 MUST 清理该 run 的取消旗标，防泄漏。

`AgentRunResult` SHALL 新增 `cancelled: bool = False` 字段并随 `to_dict` 序列化。

#### Scenario: attempt 1 被取消后无 attempt 2

- **WHEN** max_retries=3 的 run 在 attempt 1 执行中被取消
- **THEN** run 以 attempt 1 的取消结果收尾，jsonl 产物中仅存在 `-a1` 一个 attempt 文件，无 `-a2` 文件

#### Scenario: attempt 间隙设旗标则下一 attempt 不派发

- **WHEN** attempt 1 正常失败结束、attempt 2 尚未派发的间隙，外部登记该 run 的取消旗标
- **THEN** attempt 循环顶部检查命中，run 立即以 `cancelled=True` 失败结果收尾，无 `-a2` attempt 文件

#### Scenario: 秒挂计数不因取消增加

- **WHEN** 一个刚启动即被取消的 run（存活时长低于秒挂阈值）收尾
- **THEN** 该 spec 的秒挂连续计数（`_instant_fail_counts`）保持取消前的值不变

#### Scenario: AgentRunResult 序列化携带 cancelled 字段

- **WHEN** 被取消 run 的 `AgentRunResult` 调用 `to_dict`
- **THEN** 输出 dict 含 `cancelled: true` 键值对

### Requirement: dispatch 对已取消 run 的 hold-state 处置

pm_engine dispatch 侧（`_run_agent_worker` 的 implementer/fast-track 分支、verifier 验证流水线、repair worker）SHALL 对 `cancelled=True` 的 run 结果执行 hold-state 分支：

- 只更新该 spec 的 `error` 字段（内容含 `"run 被人工取消"` 及 reason），不翻转 status、不增减 `_retry_count`、不更新 `_merge_fp`/`_merge_streak`、不将 spec 入队重派；
- 后续重排完全交给既有机制（stuck 检测 / 恢复扫描）或管理员人工操作（freeze 等）。

#### Scenario: implementing spec 的实现 run 被取消后保持原状

- **WHEN** status 为 implementing 的 spec 其 implementer run 被 cancel 且收尾结果 `cancelled=True`
- **THEN** 该 spec 的 status 保持 `implementing`、`_retry_count` 数值与取消前一致、error 字段含 `"run 被人工取消"`，队列中无该 spec 的新条目

#### Scenario: testing spec 的 verifier run 被取消后保持原状

- **WHEN** status 为 testing 的 spec 其 verifier run 被 cancel 且收尾结果 `cancelled=True`
- **THEN** 该 spec 的 status 保持 `testing`、`tester_run` 字段不被回滚清空路径以外的方式改写为触发重派的状态，error 字段含 `"run 被人工取消"`

### Requirement: 文件信号跨进程入口

系统 SHALL 沿用 admin_invoke 文件信号模式提供跨进程取消入口：

- dashboard data 层 SHALL 提供原子写（临时文件 + rename）`request_run_cancel(project_root, run_id, reason)`，写入 `.fenix/cancel_run_request.json`（含 run_id/reason/source/created）；已存在未消费的请求文件时 MUST 拒绝并返回结构化冲突结果（对应 API 409）；
- daemon 主循环 SHALL 每轮检查该信号文件：读取 → 删除 → 校验 run_id 非空 → 调用 `agent_runner.cancel_run(run_id, reason, by=<source>)`；损坏 JSON 的信号文件 MUST 被删除且不阻塞主循环后续工作；删除失败（并发消费）时本轮跳过、下轮再试。

#### Scenario: 请求文件被消费且 cancel_run 被调用

- **WHEN** `.fenix/cancel_run_request.json` 存在合法内容 `{"run_id": "impl-x-123", "reason": "r", "source": "dashboard", "created": "<iso>"}`，daemon 主循环执行一轮消费检查
- **THEN** `cancel_run` 被以 run_id=`impl-x-123`、reason=`r` 调用一次，且信号文件已删除

#### Scenario: 损坏信号文件删除不卡主循环

- **WHEN** 信号文件内容为非法 JSON，daemon 主循环执行一轮消费检查
- **THEN** 信号文件被删除，主循环本轮后续工作继续执行，无未处理异常逃逸

#### Scenario: 重复请求返回冲突

- **WHEN** 信号文件已存在（未消费），再次调用 `request_run_cancel`
- **THEN** 第二次调用返回冲突结果（不覆盖既有请求文件），结果含既有请求的 created 时间戳

### Requirement: dashboard 取消 API 与终止按钮

Dashboard SHALL 提供 run 取消的人工入口：

- `POST /api/run-cancel?project=<name>&run_id=<id>`（可选 `reason` 参数）：校验项目存在（404）与 run_id 非空（400），受理后写入信号文件并返回 `{"requested": true}`；存在待消费请求时返回 409；
- runs 列表 SHALL 为活跃 run 提供「终止」操作，点击后 MUST 弹出确认弹窗（展示 run_id 与可选 reason 输入），确认后才发起请求；受理后在界面给出可感知的受理反馈。

#### Scenario: API 受理合法取消请求

- **WHEN** 对存在项目 POST `/api/run-cancel?project=<name>&run_id=impl-x-123&reason=测试`
- **THEN** 响应状态 200 且 JSON 含 `requested: true`，`.fenix/cancel_run_request.json` 被写入且 run_id 字段为 `impl-x-123`

#### Scenario: run_id 缺失返回 400

- **WHEN** POST `/api/run-cancel?project=<name>`（无 run_id 参数）
- **THEN** 响应状态 400

#### Scenario: 项目不存在返回 404

- **WHEN** POST `/api/run-cancel?project=不存在的项目&run_id=impl-x-123`
- **THEN** 响应状态 404

#### Scenario: 界面终止按钮带确认弹窗

- **WHEN** 用户在 runs 列表对活跃 run 点击「终止」并取消确认弹窗
- **THEN** 不发起任何取消请求；点击「终止」并在弹窗确认后，界面发起 `/api/run-cancel` 请求并在受理后展示受理反馈

### Requirement: 取消动作审计留痕

daemon 受理一次 run 取消（`cancel_run` 返回 `cancel_requested`）后，SHALL 向 admin_alerts 追加一条 `severity="minor"`、`signal_type="run_cancelled"` 的审计记录，内容含 run_id、spec（可解析时）、reason 与 by。

#### Scenario: 取消受理后出现审计记录

- **WHEN** `cancel_run` 对活跃 run 返回 `cancel_requested`
- **THEN** `.fenix/admin_alerts.json` 新增一条记录，其 `signal_type` 为 `"run_cancelled"`、`severity` 为 `"minor"`、内容含被取消的 run_id
