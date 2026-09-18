# Spec Delta: concurrent-suite-isolation

## ADDED Requirements

### Requirement: 端口分配不得存在 TOCTOU 窗口
测试/验证所用的空闲端口分配 MUST 消除「先申请、释放、再绑定」的竞态窗口：要么把已绑定的 socket 直接交给使用方，要么在最终绑定失败时按可重试策略重取，MUST NOT 让「探测到的端口」在被真正使用前处于无主状态而可被其他进程抢占。端口来源 MUST 可经环境变量覆盖（沿用既有 `FENIX_VERIFY_PORT` 语义）。

注释：现实现 `core/proc_utils.py:find_free_port()` 以 `bind(("127.0.0.1", 0))` 取端口后立即关闭 socket，探测与使用之间存在抢占窗口；并发跑套件时表现为随机伪失败。

#### Scenario: 并发取端口不产生被抢占
- **WHEN** 多个进程并发调用端口分配并被使用方绑定
- **THEN** 每个使用方 MUST 获得自己可独占绑定的端口，MUST NOT 出现「探测到的端口已被他人占用」导致的失败

#### Scenario: 绑定失败可重试
- **WHEN** 端口在使用方最终绑定前被其他进程抢占
- **THEN** 分配路径 MUST 支持重取并成功，MUST NOT 直接把抢占暴露为测试失败

#### Scenario: 端口可经环境变量覆盖
- **WHEN** 调用方设置了端口相关环境变量
- **THEN** 端口 MUST 采用该环境变量指定的值/段，而非自行探测

### Requirement: 同主机并发全量套件须有隔离或串行手段
框架 MUST 为「同一主机多个 worktree 并发执行全量套件」提供隔离或串行手段（如按 run/worktree 派生端口段与独立临时目录，或主机级互斥串行化），并 MUST 在 implementer/repair 契约中引导使用。隔离/串行 MUST NOT 依赖「机器负载恰好不高」的假设。

#### Scenario: 并发全量套件不产生伪失败
- **WHEN** 多个 worktree 在同一主机并发运行全量套件
- **THEN** 各套件结果 MUST 反映被测代码真实状态，MUST NOT 出现因端口/临时目录/单例文件争抢导致的伪失败

#### Scenario: 隔离策略可观测
- **WHEN** 一次全量套件运行采用了隔离或串行策略
- **THEN** 该策略 MUST 在日志/run 文件中可观测（如记录所用端口段或互斥获取结果），供事后复盘区分真实失败与资源争抢
