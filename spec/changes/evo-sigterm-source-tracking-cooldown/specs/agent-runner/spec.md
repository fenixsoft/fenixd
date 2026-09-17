# Spec Delta: agent-runner

## NEW Requirements

### Requirement: SIGTERM/SIGKILL 死法记录信号来源

agent_runner 捕获 CLI 子进程终结时，MUST 按**闭集**判定死法归属并记录：

- **框架自身终止**（cancel 旗标命中 → `RunCancelledError`；supervision 超时/轮次上限判定 kill →
  returncode=-9 且错误文本为 `Timeout after …` / `Max turns …`）MUST 维持既有语义，MUST NOT 打
  信号来源标签、MUST NOT 计入信号通道；
- **daemon 关停**（shutting_down 置位 / 产物 interrupted 标记）MUST 沿用 `[shutdown-interrupted]`
  守卫语义；
- **其余信号致死**（returncode 143 或负信号）→ 归类为带信号来源标签的错误
  （形如 `[signal-kill: SIGTERM/143]`、`[signal-kill: SIGKILL/-9]`），MUST 在 run 错误文本、日志
  与告警 evidence 中透出来源；MUST NOT 一律归 `[provider-transient]`；
- 来源归属 MUST 只由可实测的三源（shutting_down 旗标 / 产物 interrupted 标记 / 框架自身终止留痕）
  推导；无判别力时 MUST 标 `unknown` 并如实携带 returncode，MUST NOT 猜测声称 external-kill。

**背景（实测依据）**：2026-09-16 admin-refactor-dashboard-data-module-1789511370（Exit 143）与
admin-refactor-agent-runner-module-1789520256（Exit -9）两 run 无 cost 无来源记录（据 .fenix/todo.md
自省条目转述；对应 run 文件已不在 `.fenix/runs/`，具体信号发出者不可考 → 按 unknown 归类）；
`Exit 143 秒挂` 形态在 runner.py:3196 既有注释中另有旁证。

#### Scenario: 外部 kill 带来源标签

- **WHEN** CLI 子进程以信号死法结束（143/-9）且非 daemon 关停、非框架自身终止场景
- **THEN** 错误文本含信号来源标签（signal-kill / unknown），run 产物与告警 evidence 可追溯；
  不归 [provider-transient]

#### Scenario: daemon 关停仍走 shutdown 标记

- **WHEN** shutting_down 置位或产物 interrupted 标记存在
- **THEN** 维持 [shutdown-interrupted] 语义（不回归既有守卫）

#### Scenario: 框架自身强杀不打信号标签

- **WHEN** run 因 supervision 超时/轮次上限被框架 kill（returncode=-9，错误文本 `Timeout after …` /
  `Max turns …`），或由 cancel 旗标终止
- **THEN** 沿用既有超时/取消终态语义，不打信号来源标签、不计入信号通道（框架自己强杀不得冷却链路）

### Requirement: 信号死法连续出现触发熔断冷却

Exit 143/-9 类（信号死法）失败 MUST 计入信号类熔断计数：同 spec 连续出现（阈值 3）时触发该 spec
的冷却（复用/扩展 infra_breaker 或 provider_circuit 计数通道，沿用既有窗口/冷却量级），冷却期内
该 spec 重派被跳过（不无限原地重试），冷却到期自动恢复；涵 admin/impl 处置 run 路由（既有秒挂冷却
只跳过 implementer/fast-track/repair 派发，未覆盖处置 run），MUST NOT 因瞬态通道而反复撞运气至
预算耗尽。

MUST NOT 复用/触发全局瞬断指纹熔断通道（`record_transient_error` / `_transient_break_until`，
达阈值冻结全项目新派发：provider_circuit.py:334-425、dispatch.py:366-375）——信号计数的爆炸半径
限于该 spec。

与既有秒挂冷却（`_record_instant_fail`，runner.py:3194-3215）的关系 MUST 明确：同一事件允许累加，
但 MUST NOT 相互覆盖冷却截止时间（取更晚者生效）。

#### Scenario: 143/-9 连发触发冷却

- **WHEN** 同一 spec/链路的信号死法失败连续达阈值
- **THEN** 该 spec 冷却启动（不再原地重试），告警登记，冷却到期自动恢复；全局派发闸门不受影响

#### Scenario: 正常瞬态不受影响

- **WHEN** provider 网络抖动类瞬态（非信号死法）
- **THEN** 既有退避重试不变

### Requirement: 非内容/非网关质量失败不进瞬态指纹通道

产物硬门失败按既有两类各自处理，两类 MUST NOT 记入**全局瞬断指纹**（对齐 `[terminal-no-commit]`
已合入的 carve-out 先例，runner.py:2042-2051），错误文本 MUST 保真透出归因：

- **任务完成度类**（已有 `[task-gate]` 前缀：tasks.md 未勾任务 / completed_tasks 不一致 / partial
  申报不一致，result_gate.py:559-716）MUST NOT 注入 `[provider-transient]` 标签、MUST NOT 就地
  消耗瞬态退避预算；重试由既有 gate 降级语义（`TASK_GATE_DEGRADE_THRESHOLD=2`）与 attempt 层重试承担；
- **结构类**（结果文件缺失/为空/非法 JSON/顶层非对象/status 白名单外；按 result_gate.py:39-43
  既有划分**无前缀**，不是 `[task-gate]`）MUST 保留既有原地退避重试与 `[provider-transient]`
  标签（add-judge-artifact-gate D1 契约，见 tests/test_agent_runner_gate.py:11-12、:160-192），
  不得改为零重试；仅新增结构类归因标签 + 停止全局瞬断指纹记账。

#### Scenario: 格式拒绝独立归类

- **WHEN** 失败为产物硬门失败（任务完成度类或结构类，非网关质量、非内容判定）
- **THEN** 不记全局瞬断指纹、不触发全局瞬断熔断；错误文本带可识别归类标签；
  结构类保留既有原地退避重试恢复路径（注：task-gate 相关语义另由 fix-impl-tasks-completion-gate
  指定，此处仅管归类通道隔离）
