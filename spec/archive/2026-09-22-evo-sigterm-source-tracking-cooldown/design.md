# Design: sigterm-source-tracking-cooldown

## 背景与痛点

外部信号致死（Exit 143/-9）无来源记录、无熔断，一律走 [provider-transient] 通道空转
（2026-09-16 两个 admin 处置 run 实证：run 文件尾部 error 仅 `Exit code: 143` /
`Exit code: -9`，无 cost、无来源）；产物硬门失败亦被记入全局瞬断指纹通道（信号指纹污染）。
runner.py:2117-2143 shutdown-interrupted 守卫只覆盖 daemon 关停（shutting_down 旗标 +
产物 interrupted 标记）两类信号。

已有机制（本方案 MUST 说明关系，不得重复造通道）：

- 守卫（runner.py:2126）：shutting_down（fenixd.py:1932 置位；liveness.py:919-935 同步写
  产物 interrupted 标记）→ `[shutdown-interrupted]`，短路瞬断通道。
- 秒挂冷却（runner.py:3194-3215，`_record_instant_fail`）：按进程存活时长判定，默认连续 3 次
  进冷却；docstring 直指「Exit 143 秒挂」。但其冷却只跳过 implementer/fast-track/repair 派发
  → **admin 处置 run 路由未覆盖**（这正是本次要补的缺口）。
- 全局瞬断指纹熔断（provider_circuit.py:334-425 `record_transient_error`）：达阈值冻结**全部**
  新派发（dispatch.py:366-375）。本方案 MUST NOT 复用该通道做信号计数（爆炸半径过大）。

## 目标

- 143/-9 死法带来源标签，记录可追溯（错误文本 + 日志 + 告警 evidence）。
- 信号死法连续触发冷却，不再无限重试（覆盖 admin/impl 处置 run 路由）。
- daemon 存活期内的框架主动终止（drain / cancel / supervision 强杀）全部留痕、可判定归属；
  产物硬门失败不再污染全局瞬断指纹通道。

## 非目标

- 不动 4xx/切换类熔断与正常瞬态退避。
- 不动 review 层熔断（819d8e85 已有）。
- 不承诺覆盖「daemon 已死（硬杀/崩溃）」场景的 runner 侧归类：该场景 runner 线程随 daemon
  一并消失、**不存在归类动作**（不产生误标），遗留 run 的终态由读侧清扫补写
  （liveness.py:104-130 启动清扫、liveness.py:200-230 runtime 清扫），本方案不改读侧语义。

## 方案

### 1. 信号来源判定（core/agent_runner/runner.py，attempt 失败收口处）

判定为**闭集**，按序短路，先排除框架自身终止（否则框架自己强杀的 run 会被误标外部 kill）：

1. **框架主动终止（不改语义、不打信号标签、不计信号熔断）**：
   - cancel 旗标命中 → `RunCancelledError` / `[cancelled-by-admin]`（runner.py:2760-2786 已走
     独立异常通道）；
   - supervision 超时 / 轮次上限判定 kill（runner.py:2833、2874 `proc.kill()` → returncode=-9，
     runner.py:2942-2971 收口，错误文本为 `Timeout after …` / `Max turns …`，异常不带
     stderr_lines）——既有代码已特意把该路径排除在瞬断之外（runner.py:2984-2988 注释），
     MUST 同样排除在信号通道外。
2. **daemon 关停**：shutting_down 置位或产物 interrupted 标记存在 → 沿用既有
   `[shutdown-interrupted]` 守卫（runner.py:2126），不新增标签、不计数。
3. **外部/未知信号致死**：returncode 命中 143（SIGTERM 由 CLI 自身转写为 143，见
   runner.py:3196 既有实测注释）或负信号（-9/-15 等）且非上述两类 → 打信号来源标签
   `[signal-kill: SIGTERM/143]` / `[signal-kill: SIGKILL/-9]`，错误文本、日志与告警
   evidence 透出，并进入下方信号计数通道。

来源归属 MUST 只由可实测的三源闭集（shutting_down 旗标 / 产物 interrupted 标记 / 上述框架
自身终止留痕）推导；环境不具备判别力时（如运行进程内的 runner 线程无法反查信号发出者——
其父进程恒为 daemon）MUST 标 `unknown` 并如实带 returncode，MUST NOT 以猜测声称
`external-kill`。2026-09-16 两 run 的 run 文件已不在 `.fenix/runs/`（仅 todo.md 转述），
实现期不得据其断言具体信号发出者。

### 2. 信号死法冷却通道（core/agent_runner/provider_circuit.py）

- 计数键 = **spec 维度**（同 spec 同 agent 族的信号死法连续计数），阈值 3、窗口/冷却沿用既有
  语义（`TRANSIENT_BREAK_WINDOW_SECONDS`/`TRANSIENT_BREAK_COOLDOWN_SECONDS` 同量级常量，
  可配键沿用 `agents.*` 命名）。
- 冷却只作用于**该 spec 的重派**（复用秒挂冷却同款「跳过派发、不耗预算、不起进程」语义），
  MUST NOT 写 `record_transient_error` / `_transient_break_until` 全局瞬断熔断（不得因此冻结
  全项目新派发）。
- 与既有 `_record_instant_fail` 的关系 MUST 明确：信号死法若同时是秒挂，走既有秒挂计数，
  本通道只补「信号维度」计数与冷却触发，MUST NOT 让两条通道对同一事件互相覆盖冷却截止时间
  （同一事件双记仅允许累加，取更晚的冷却截止）。
- 冷却到期自动恢复；触发与恢复各写一条 major 告警（节流沿用既有 15 分钟语义）。

### 3. 产物硬门失败的通道隔离（core/agent_runner/runner.py）

既有 `[task-gate]` 前缀（result_gate.py:46）**只覆盖「任务完成度类」失败**
（tasks.md 未勾任务 / completed_tasks 不一致 / partial 申报不一致，result_gate.py:559-716），
**不含结构类**（结果文件缺失/为空/非法 JSON/顶层非对象/status 白名单外，result_gate.py:39-43
注释明确划为另一类、无任何前缀）。两类按各自既有契约处理，MUST NOT 混为一谈：

- **任务完成度类（已带 `[task-gate]`）**：MUST NOT 注入 `[provider-transient]` 标签、MUST NOT
  记全局瞬断指纹；重试由既有 gate 降级语义（`TASK_GATE_DEGRADE_THRESHOLD=2`，
  result_gate.py:490-505）与 attempt 层重试承担，不消耗原地瞬态退避预算。
- **结构类（无前缀）**：承载「agent 未完成落盘、重试可恢复」的真实恢复需求，MUST 保留既有
  原地退避重试与 `[provider-transient]` 标签（契约见 tests/test_agent_runner_gate.py:11-12、
  :160-192），但 MUST NOT 记全局瞬断指纹——对齐已合入的 `[terminal-no-commit]` carve-out
  先例（runner.py:2042-2051）；错误文本 MUST 补齐机械归因标签（结构类）供读侧区分。
- result_gate.py 本方案只做**核对（只读）**，不新增/改动前缀语义；故交付清单不含该文件。

## 测试策略

- 新文件 tests/test_sigterm_source_tracking.py：
  1. 外部信号致死（143/-9，无 shutdown 标记）→ 错误含 `[signal-kill: …]` 标签且不进全局瞬断指纹；
  2. shutting_down / 产物 interrupted → 维持 `[shutdown-interrupted]`（不回归既有守卫）；
  3. 143/-9 连续达阈值 → 该 spec 冷却启动、冷却期不重试、到期自动恢复，且**全局瞬断熔断未被触发**；
  4. provider 网络抖动瞬态 → 既有退避不变；
  5. supervision 超时/轮次上限强杀（returncode=-9、错误文本 `Timeout after …`/`Max turns …`）
     → 不打信号标签、不计入信号冷却（不得因框架自己强杀而冷却链路）；
  6. 任务完成度类（`[task-gate]`）失败 → 无 `[provider-transient]` 标签、不记全局瞬断指纹、走降级语义；
  7. 结构类产物硬门失败 → 保留原地退避重试与 `[provider-transient]` 标签，但不记全局瞬断指纹。
- 既有 tests/test_provider_circuit.py、test_agent_runner.py、test_agent_runner_gate.py、
  test_transient_backoff.py 回归。
