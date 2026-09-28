# proposal：fix-transient-break-unseal-backoff

## Why

2026-09-22 凌晨两场 provider 瞬断风暴（fenixd.log:7060 02:04:24Z、:7180 02:20:59Z），各冻结全部新 run 派发 600 秒、合计约 21 分钟，10 条 attempt 失败全打在 provider=inferaiapi.com（auto-fix ×4、relocation-writeback ×6；冻结期内另有 6 次同指纹失败记账，全程至少 16 次）。

熔断本身按设计保护（fix-provider-transient-backoff D4），缺口在解封节奏：core/agent_runner/provider_circuit.py:665-698 到期分支清零后立即 _wake_dispatch_after_break（:700-728 直接 _process_queue）一次性放出全部积压——02:14:30Z 解封后 35.9 秒即再吃失败，16 分 34 秒后第二场触发，「5 连败→冻结→解封→立即重蹈」完成一轮实证。per-spec 600 秒重派延迟（backoff.py:224-260）在冻结期内已耗完，积压在解封瞬间天然同批并发重撞同一 provider；指纹归一（provider_circuit.py:488）剥掉 model 名后任何同型 SDK 错误收敛同一指纹，进一步放大合流。

## What Changes

- **A｜解封次数记忆与渐进 hold**：ProviderCircuit 记录同归一化指纹的解封次数（稳定窗内无新熔断则衰减复位）；熔断到期后不立即放行，先进入 post-unseal hold，时长 60 秒×已解封次数、封顶 600 秒。
- **B｜探针放行**：hold 期满先只放最高优先级单条派发作为探针（类比对齐 per-provider 4xx 熔断既有 half_open 语义，provider_circuit.py:152-160）；观察窗内探针的 provider 调用未再产生同指纹瞬断失败，才按队列优先级顺序放行其余积压；探针再失败则按现行规则重新熔断且解封次数+1。
- **C｜错峰放行**：其余积压按既有 _run_queue 优先级（含 aging 加权）顺序放行，MUST NOT 同拍全量放出。
- **D｜配置与测试**：新增 agents.transient_unseal_* 配置键（缺省启用、数值保守）；修订 tests/test_transient_backoff.py:780/:858/:872 锁定的「到期即清零+立即全量唤醒」用例到新语义，新增解封节奏专项测试。

**BREAKING**：无。既有三层退避（原地 30/60/120、per-spec 600s 延迟、全局熔断冻结期）语义不变；仅新增全局层解封后的恢复节奏。
