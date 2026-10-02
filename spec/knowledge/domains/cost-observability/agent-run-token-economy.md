# Agent Run 上下文经济性与缓存探针
<!-- knowledge: capability=agent-run-token-economy rev=1
     sources=spec/archive/2026-09-25-fix-agent-lane-efficiency -->

逐 run 量化上下文经济性指标，使「上下文成本随轮数平方增长」的结构可见，并提供可复现的网关前缀缓存能力探针。

## 规则

- **逐 run 经济性指标（纯读侧）**：`_run_claude` 在流式读取环内统计本次 run 的轮数（assistant 事件数）、对话上下文峰值（token 估算）、累计 `input_tokens`、累计 `cache_read_input_tokens`。run 终结时（成功/失败/取消三路径）落一行结构化指标（日志 + run 转录），至少含 `run_id` / `turns` / `context_peak_tokens` / `per_turn_input_tokens`。
- **阈值诊断告警**：`per_turn_input_tokens` 超过配置阈值时打一条诊断 WARNING（含 run_id 与实测值），提示该 run 上下文成本接近 O(轮数²) 结构。该告警不阻断 run、不触发独立人工告警；指标采集不得改变流式处理时序。
- **网关前缀缓存探针**：`bin/probe_prompt_cache.py` 可重复执行，对指定 provider 发送带 `cache_control` 的稳定前缀两轮请求，解析第二轮 `usage.cache_read_input_tokens`，输出确定性 JSON 判据（`provider` / `cache_supported` / `evidence`）。探针可离线对配置内任一 provider 单独执行，不依赖 daemon 运行。
- **探针结论与实现解耦**：探针结论仅作记录与复验依据（当前定案：直连网关不产生可复用前缀缓存命中，缓存优化明确不做）；不得因探针结论改变 run 的派发/路由行为。网关升级后可用探针复验。

## 溯源

- 2026-09-25 2026-09-25-fix-agent-lane-efficiency（spec/archive/2026-09-25-fix-agent-lane-efficiency） — 新增 run 级上下文经济性指标、超阈值诊断告警与 `bin/probe_prompt_cache.py` 缓存能力探针，并固化「不依赖前缀缓存」的定案结论。
