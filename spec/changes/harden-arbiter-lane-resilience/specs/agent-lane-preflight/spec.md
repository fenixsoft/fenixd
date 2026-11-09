# 能力规格：agent-lane-preflight

## 需求

- **R1 探针**：`probe_lane_health` 两级检查——①适配器 CLI 二进制可达（which + 轻量版本探测，短超时）②config 显式链 provider route 凭据可解析（本地检查，不发 API 请求）；输出 `LaneHealth(ok, reasons)`。
- **R2 启动自检**：daemon 启动序列尾部执行探针，结果留痕；unhealthy 时发「车道环境不可用」告警（同一 unhealthy 周期单发，恢复自动关闭）。
- **R3 派发前置**：arbiter 裁决派发前查探针缓存（TTL `arbiter.preflight_ttl` 缺省 300s，超时重探）；unhealthy → 跳过本次派发（不消耗 infra 计数、不产半成品包、记「前置自检拦截」日志）；healthy 且有 infra 停机标记 → 触发 R4 复位。拦截检查置于派发入口最前（`submit_trigger` 的 dedup/`_recurrence_inflight` 复现标记消费之前、`process_chain_handoff` 入口），命中时零状态变更（不写 `_active`、不消费复现标记、不落台账、不计配额）；异步路径返回既有终态字 `deduped`（零新契约），信号靠既有触发面复报/回扫候选重扫自然回喂。
- **R4 fail-open**：探针自身异常按 unhealthy 处理并 WARNING，不抛出、不阻塞 daemon 主流程；禁内存定时器——周期重探挂靠既有周期节拍（scheduled-reverify-restart-durability 纪律）。

## 场景

- **S1** CLI 缺失/凭据缺失时启动 → 告警单发、daemon 正常起、后续裁决派发被拦截且不产生 dead-man/infra-failed 台账行。
- **S2** 探针 healthy → 派发放行；若此前 infra 停机 → 计数复位。
- **S3** 探针函数抛异常 → WARNING + 视为 unhealthy，daemon 不崩、派发安全跳过。
- **S4** TTL 内多次派发 → 只探一次（缓存复用）；TTL 过期 → 重探。
- **S5** unhealthy 拦截期到达的触发/回扫候选 → 零状态变更（`_active`/复现标记/台账/配额均不动），不产生 dead-man/infra-failed 台账行，恢复 healthy 后正常放行。

## Deliverables

- path: core/agent_runner/lane_preflight.py
  kind: new
- path: core/config.py
  kind: modify
- path: fenixd.py
  kind: modify
- path: core/pm_engine/arbiter.py
  kind: modify
- path: tests/test_arbiter_lane_resilience.py
  kind: new
