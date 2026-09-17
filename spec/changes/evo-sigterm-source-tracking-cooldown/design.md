# Design: sigterm-source-tracking-cooldown

## 背景与痛点

外部信号致死（Exit 143/-9）无来源记录、无熔断，一律 [provider-transient] 无限重试空转（2026-09-16 两个 admin 处置 run 实证）；产物硬门格式拒绝亦被注入瞬态通道（信号指纹污染）。runner.py:2119-2123 shutdown-interrupted 守卫只覆盖 daemon 关停。

## 目标

- 143/-9 死法带来源标签，记录可追溯。
- 信号死法连续触发冷却，不再无限重试。
- drain/重启对 in-flight run 标记全覆盖；格式拒绝与瞬态通道隔离。

## 非目标

- 不动 4xx/切换类熔断与正常瞬态退避。
- 不动 review 层熔断（819d8e85 已有）。

## 方案

1. core/agent_runner/runner.py 子进程终结捕获处：依据 returncode（143/负信号）、shutting_down 与产物 interrupted 标记、父进程存活检查，产出来源标签（daemon-drain/external-kill/unknown），错误文本注入标签；调用方（attempt 收口）按标签分支：shutdown → 既有守卫；external-kill → 信号熔断计数。
2. core/agent_runner/provider_circuit.py（或 infra_breaker 复用）：新增信号死法计数通道（阈值 3/冷却窗口延续既有语义），143/-9 达标即冷却、恢复自动。
3. 归类隔离：gate 格式拒绝在 result_gate.py 抛错出口即打独立前缀（[task-gate] 已存在，核对不落入 provider-transient 计数），run 错误文本保真透出。
4. 单测覆盖五类场景。

## 测试策略

- 新文件 tests/test_sigterm_source_tracking.py：外部 kill 带标签、daemon 关停不回归、143 连发冷却、正常瞬态不变、格式拒绝不进瞬态五类。
- 既有 tests/test_provider_circuit.py、test_agent_runner.py、test_agent_runner_gate.py 回归。