# Design: add-run-cancel

## Context

run 执行链完全位于 daemon 进程内部：event_bus/pm_engine 在 worker 线程中调 `AgentRunner._execute_agent`（重试链，attempt run_id 带 `-a<n>` 后缀）→ `_run_claude`（`subprocess.Popen` 启动 claude CLI，句柄登记于 `self._running_agents[attempt_run_id]`，1s 粒度轮询环处理超时/max_turns/退出）。目前唯一的终止路径是 daemon 整体关停（`LivenessSupervisor.wait_for_running_agents`：全员 SIGTERM + 写 `interrupted` 标记），无单 run 粒度手段。

run 失败后 dispatch worker（`_run_agent_worker`）走既有失败分支：status 翻回 ready、`_retry_count++`、自动重派——若取消被当作普通失败，管理员的取消会被自动重派立即抵消。

Dashboard server 与 daemon 是**独立进程**（`AdminStore` docstring 明确），跨进程触达 daemon 内存态的既有模式是文件信号：`restart_request`（supervisor 轮询）、`.fenix/admin_invoke_request.json`（`fenixd._check_admin_invoke_requests` 主循环 1s 粒度消费，读→删→投递）。

本设计的完整交互设计已在 SPEC 立项前与用户对话中批准。

## Goals / Non-Goals

**Goals:**

- 管理员可安全终止单个运行中的 run：子进程被优雅终止、终态可追溯、重试链与自动重派不被触发。
- 终止原语与状态机生命周期严格解耦：cancel 不做任何状态转换，后续处置交给既有机制（stuck 检测/恢复扫描/freeze）。
- 跨进程入口 + UI 与审计留痕一次交付完整（能力与界面同批，见 fenix-new-config-needs-dashboard-ui 约定）。

**Non-Goals:**

- 不做 spec 级批量取消（既有并发控制保证每 spec 同时至多一个活跃 run，run 粒度即够）。
- 不改 `VALID_TRANSITIONS`、不新增状态值、不新增状态机方法。
- 不新增 worktree 处置逻辑（取消 run 走与普通失败一致的既有清理路径）。
- 不让自动链路（recovery/stuck/gate/freeze）获得调用 cancel 的能力。

## Decisions

### D1: 旗标协作式取消，调用线程不做跨线程 kill

`cancel_run` 只做三件事：归一化 run_id（正则剥 `-a\d+$`）→ 前缀匹配 `_running_agents` 活跃 attempt → 登记旗标（`_cancel_requested: set[str]`，`threading.Lock` 保护，键为基础 run_id）并立即返回。终止动作由持有 run 的 worker 线程在 `_run_claude` 轮询环内完成。

- **为什么不用调用线程直接 kill**：run jsonl 的终态行落盘、读线程 join、异常分类全部依赖属主线程序；跨线程 kill 会造成「取消者写终态行 vs 读线程仍在追加」的竞态（result 终态必须是文件最后一行的既有契约被破坏），且超时/supervision/取消三种终止来源的异常分类会在 kill 方线程与属主线程间扯皮。旗标方案把全部收尾留在属主线程，跨线程共享状态只有一个旗标集合。
- 取消受理到 SIGTERM 的延迟 ≤ 2 个轮询周期（缺省 ~2s），对人工操作可感知无害。

### D2: 专用异常 `RunCancelledError` 三分离

`_run_claude` 命中旗标 → `terminate()` → 最长 `AGENT_TERMINATE_GRACE_SECONDS`（10s，复用既有优雅退出常量）→ 存活则 `kill()` → jsonl 追加 `{"type":"cancelled", reason, by, timestamp}` 终态行 → 抛 `RunCancelledError`。`_execute_agent` 在通用 `Exception` **之前**单独捕获：不重试、不计秒挂、不触发 provider 切换，返回 `AgentRunResult(cancelled=True)`。

- **为什么复用 RuntimeError 不够**：通用失败路径会触发重试与秒挂退避——取消必须绕开这两条自动行为，异常类型是唯一可靠的分叉点。
- **为什么新增终态行类型而不是复用 `interrupted`**：`interrupted` 语义是「daemon 关停导致的框架 SIGTERM」，被 `_run_was_interrupted` 用于秒挂豁免与重启恢复判定；取消是人工动作，审计与展示都需要独立可辨。三分类型（cancelled/interrupted/error）让 dashboard 状态分类直读 type。

### D3: attempt 链整体终止 + 基础 run_id 归一化

旗标键为基础 run_id（`_execute_agent` 的 run_id 入参，attempt 文件为其 `-a<n>` 后缀）。两处检查点：

1. `_run_claude` 轮询环（运行中终止当前 attempt）；
2. `_execute_agent` attempt 循环顶部（与既有 `_spec_is_frozen` 检查同位置，覆盖 attempt 间隙/准备阶段）。

run 收尾（正常/失败/取消）清理旗标。dashboard 可见的是 attempt run_id，`cancel_run` 接受任一形态（归一化后等价）。

### D4: dispatch hold-state 分支（用户拍板语义）

`_run_agent_worker`（implementer/fast-track）、verifier 流水线、repair worker 对 `cancelled=True` 结果：只写 `error`（含「run 被人工取消」），不翻 status、不动 `_retry_count`/`_merge_fp`/`_merge_streak`、不入队。

- 备选「视作普通失败」被否：重试预算被人工干预烧掉 + 取消后几分钟内自动重派抵消取消意图。
- 备选「取消即冻结」被否：cancel 自身触碰状态字段违背解耦定位，且掐单个坏 run 会误伤整个 spec。
- hold-state 的代价：spec 停在 implementing/testing 直到 stuck 检测/恢复扫描按既有节奏接管——这是有意的（管理员想永久停止就 freeze，想让它继续就不动）。

### D5: 跨进程入口完全镜像 admin_invoke 模式

- `data.py: request_run_cancel()`：tmp+rename 原子写 `.fenix/cancel_run_request.json`；存在未消费请求时返回冲突结构（409），不覆盖——与 admin_invoke 的「进行中返回 409」语义一致，天然节流。
- `fenixd.py: _check_cancel_requests()`：镜像 `_check_admin_invoke_requests`（损坏文件删除防卡死、先读后删、删除失败下轮再试）。取消受理只是设旗标，微秒级，**不投 worker 池**（区别于 admin invoke 的重处置投递）。
- 审计：`cancel_run` 返回 `cancel_requested` 时落一条 minor 级 admin_alerts（signal_type=`run_cancelled`），运维记录页可见；spec 字段从 run_id 归一化失败时留空不强解。

### D6: API 与 UI

`POST /api/run-cancel?project=&run_id=`（400/404/409/200 语义）；runs 列表活跃 run 行加「终止」按钮 + 确认弹窗（沿用 admin-invoke-dialog 交互模式与样式语言）；受理后行内反馈。dist 产物按惯例重建并提交（fenixd-dashboard-verify-serves-main-dist）。

## Risks / Trade-offs

- [取消与 run 自然收尾竞态：旗标刚登记 run 就正常完成] → 取消只在未来路径生效（轮询环/attempt 顶部）；已收尾的 run 不受影响，`cancel_run` 前置检查与旗标双保险，最坏结果是 not_running 返回或旗标登记后无害失效（收尾即清）。
- [轮询环旗标检查增加每秒一次的锁开销] → 单 set 成员判断，纳秒级，1s 粒度下可忽略。
- [SIGTERM 后 claude 收尾写流与取消终态行交错] → 终态行在属主线程 join 读线程**之后**落盘（沿用 result 终态后置的既有次序），cancelled 行保证是文件最后一行。
- [hold-state 后 spec 停留原状，管理员忘记处置导致长时间滞留] → stuck 检测按既有阈值最终接管重排；审计记录与 error 字段让滞留在 dashboard 可见。
- [文件信号文件名与未来其它请求冲突/残留] → 单一固定路径 + 消费即删 + 损坏即删，与 admin_invoke 同款生命周期。

## Migration Plan

纯新增能力，无数据迁移。回滚 = revert 提交；信号文件与旗标为运行时态，不留持久残留。

## Open Questions

无——交互语义（hold-state）已在立项前由用户拍板。
