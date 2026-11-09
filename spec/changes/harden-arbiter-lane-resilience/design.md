# Design — arbiter 车道故障分级复位与前置自检

## 总体思路

两个能力：**arbiter-infra-failure-reset**（失败分级 + infra 资格复位）与 **agent-lane-preflight**（车道前置自检）。分级依赖探针产出的健康信号，故 preflight 模块先行落地、arbiter 分级消费其结论；两能力共享同一「环境指纹」口径（单一来源）。

## 能力一：arbiter-infra-failure-reset

### 失败分级（改 `ArbiterEngine._on_run_failed`，arbiter.py:1290）

新增分类函数（建议放 agent_runner 侧供两能力共用）：

```
classify_lane_failure(result) -> "infra" | "judgment"
```

判据（满足任一即为 infra）：
- **0 rounds**：run 无任何 API 往返样本（复用 core/agent_runner/latency.py:235-247 的「无样本」判定口径，不从文案反解）；
- **环境指纹**：error/stderr 命中固定指纹集——`MISSING_CREDENTIAL`、`No such file or directory`（CLI 缺失）、`skipping profile bundle`（bundle 不兼容被跳过）、exit_code=1 且 rounds==0（评审注：此条为 0 rounds 判据的子集，冗余保留仅作归因可读性）。

落地面（评审补约）：`run_arbiter` 信封现为 `{"ok","run_id","report","error","usage_info","elapsed_s"}`，**无 rounds 字段**（core/agent_runner/maintenance_runs.py:712 起；内部 turns 计数已有，:800 附近）——分级判定所需 rounds 须由信封透传（补 `rounds` 键）或按 run_id 复用 latency 统计读取，MUST NOT 从 error 文案反解。

预算耗尽（tokens/wallclock）**不**判 infra——那是真实车道在真实消耗，保持现行 dead-man 语义。

### infra 通道（与 dead-man 通道并行、互斥）

- 独立计数 `_infra_failure_counts`（内存，与 `_failure_counts` 分离）+ 独立上限（config `arbiter.max_consecutive_infra_failures`，缺省沿用 `ARBITER_MAX_CONSECUTIVE_FAILURES_DEFAULT` 同值）。
- infra 失败：写台账 kind=`infra-failed`（复用 `_write_ledger`，action_or_upgrade 注明「环境不可用，待健康探针复位后重试」），**不**加 `_deadmanned`、**不**升级人工 alert（改记 WARNING 日志 + 一次性「车道环境不可用」告警，见能力二）。
- infra 达上限：同样只写 `infra-failed` + 告警，不升级人工——资格保留，等探针复位。
- judgment 失败：现行路径原样（连败 → dead-man → 永久升级）。
- infra 路径终态字与链消费（评审补约，防「不升级人工」在链交接形态失效）：`_on_run_failed` 返回新终态字 `"infra-failed"`。异步路径 `_process_trigger` 忽略返回值、零影响（arbiter.py:912-913/:926）；链同步路径经 `process_chain_handoff` 透传（arbiter.py:971/:985）。链驱动 `_run_arbiter_phase`（escalation_chain.py:1563-1594）现状是循环见 `outcome != "failed"` 即 break（infra 终态无死循环风险）、随后非 closed 一律 `_endpoint_escalate` 上升人工（escalation_chain.py:902-910）——MUST 新增 `"infra-failed"` 消费分支：不循环重派、不上升链终点、不升级人工，链件按 deferred 让行范式留痕（escalation_chain.py:920-923），等探针复位/下次触发面回喂。
- 持久读侧（:383-388、:626-671、:671、:715）：只认 dead-man kind，不变；新 kind=infra-failed 对既有消费者透明（台账 append-only 纪律 :180-184 不破坏——新 kind 是追加行，不与既有「任意 kind 即已调查过」判定冲突，回扫排除逻辑以 dead-man 为唯一永久口径）。

### 复位消费

- 探针成功（见能力二）→ 清 `_infra_failure_counts` 全量 + 记日志「车道健康，infra 计数复位」；judgment `_failure_counts` 与 `_deadmanned` **不动**。
- 复位触发点：daemon 启动探针、周期扫描（对齐 scheduled-reverify-restart-durability 纪律：**不引入内存定时器**，挂靠既有周期节拍）、派发前置（能力二 3）。

## 能力二：agent-lane-preflight

### 探针模块（新 `core/agent_runner/lane_preflight.py`）

```
probe_lane_health(config) -> LaneHealth(ok: bool, reasons: list[str])
```

两级检查（对应今日实证的两种根因）：
1. **CLI 可达**：适配器声明的二进制可执行（which + 轻量 `--version` 类探测，超时短平快）；
2. **凭据路由可解析**：config 显式链的 provider route 凭据可解析（复用 dsh_adapter 对 MISSING_CREDENTIAL 的既有识别面做本地检查，不真发 API 请求）。

任一失败 → `ok=False` + reasons。探针本身 **fail-open**：异常按 unhealthy 处理并 WARNING，不抛出、不阻塞 daemon（与推送凭证自检同范式）。

### 接线点（改 fenixd.py）

- **启动自检**：daemon 启动序列尾部调用，结果 WARNING/OK 留痕；unhealthy 时发「arbiter/repair 车道环境不可用」告警（alert 去重：同一 unhealthy 周期只发一次，恢复时自动关闭）。
- **派发前置**：arbiter 裁决派发前查探针缓存（TTL 内复用，超时重探）；unhealthy → **跳过本次派发**（不消耗 infra 计数、不产生半成品包），记「前置自检拦截」日志。healthy → 正常派发，且若此前有 infra 停机标记则触发复位（能力一）。
- **拦截点位与零状态变更**（评审补约）：前置检查置于两派发入口最前——`submit_trigger` 入口（任何 dedup/`_recurrence_inflight` 复现标记消费之前，arbiter.py:394-425）与 `process_chain_handoff` 入口（arbiter.py:960-963）。命中拦截零状态变更：不写 `_active`、不消费复现标记、不落台账、不计配额；异步路径返回既有终态字 `deduped`（零新契约，调用方零改动）＋「前置自检拦截」日志，信号闭环靠既有触发面复报/回扫候选重扫自然回喂，不新增持有队列；链路径返回 `"infra-failed"`（消费分支见能力一）。
- **周期消费**：挂靠既有周期节拍重探 + 复位消费（禁内存定时器）。

## 测试策略（tests/test_arbiter_lane_resilience.py）

1. 0 rounds + MISSING_CREDENTIAL 指纹 ×N → 台账 infra-failed、`_deadmanned` 空、无人工升级；
2. 有 API 往返的失败 ×cap → dead-man 永久（现行语义回归）；
3. 预算耗尽 → dead-man（不误判 infra）；
4. 探针 healthy → infra 计数清零、签名恢复派发资格；
5. 探针 unhealthy → 派发被跳过、告警单发、fail-open（探针抛异常不炸 daemon）；
6. 台账读侧回归：infra-failed 行不改变 dead-man 判定与回扫排除行为。
7. 链交接 infra 终态与拦截零状态变更：`infra-failed` 不上升链终点、不重派、deferred 留痕等复位；unhealthy 拦截期触发零状态变更（`_active`/复现标记/台账/配额均不动）。

## 配置面

新增 `arbiter.max_consecutive_infra_failures`（缺省 = 既有连败上限同值）与探针 TTL（缺省 300s）；两键 MUST 经 `ConfigLoader.get_arbiter_config` 白名单扩展接入（core/config.py:2850 起，现为四键白名单 dict——不加白名单则旋钮恒缺省、配置面失效；旁路直读违反「经 ConfigLoader 单源」纪律，arbiter.py:267-273）；全部 get-or-default，无配置时行为完全向后兼容。
