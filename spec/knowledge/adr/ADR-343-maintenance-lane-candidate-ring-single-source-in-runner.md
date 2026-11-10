# ADR-343：车道 provider 候选环单源于 runner 且与 dispatch attempt 环分层

date: 2026-11-10
status: accepted

## Context

八条 LLM 车道（六条维护车道 administrator / arbiter / self-review / evolution / code-review / code-fix，两条判官范式车道 spec-review / dispute-judge）此前各自手写「解析分配→取链首→单发」，无链 failover：provider 限流期间车道只能反复打链首候选直至终态失败，链上兜底候选不可见。dispatch attempt 环的链选择/切换判定/冷却/记账原语已事故验证，但该环绑定 worktree、spec 重试计数、result gate 与 dispatch 观察钩子。候选环若逐车道复制实现必然漂移（同因先例：`_apply_provider_env` 去重、marker 写点抽取）；若直接复用 dispatch 环本体，则会把 worktree/spec 会计/结果门语义拖进维护车道，污染 spec accounting。

## Decision

候选环本体只在 AgentRunner 实现一次（`_run_agent_with_chain_failover`）：切换判定（`_switch_signal_text` + `classify_switch_error`）、冷却记账（switch/限流/拒模型）与链选择全部复用 dispatch 环原语，禁止车道本地文本匹配或私有冷却实现。维护车道只经 `maintenance_runs._run_lane_agent_with_failover` 薄封装传入差异参数（角色回退顺序、fallback_model、post_provider_env、max_turns、marker 专用名）；判官范式两镜像方法直调同一环。车道环与 dispatch attempt 环保持分层：不并入 dispatch 环；不引入 `-aN` 子 run（单 run 单 jsonl 多 attempt 事件流）；候选间不续会话（每候选开新会话，dispatch 环的跨 attempt resume 语义不外溢）；车道专属 env 经 `post_provider_env` 在 provider env 组装之后后置注入。

## Consequences

- 后续新增 LLM 车道（或把外部二进制如 `run_impl_ocr` 纳入链 failover）的接入面收窄为「调候选环/薄封装」，判定与冷却零新实现。
- 判官范式镜像方法（`run_spec_review` / `run_dispute_judge`）的共性行为必须两处同步，靠契约断言测试守卫；各自收口语义不得挪入候选环 helper。
- 候选间上下文不接力是接受代价（跨 provider session 不可复用）；车道总时长随链长线性放大，不新增计时器与后台线程，沿用既有调度器/supervisor 看护。
- 全部消费面（manifest、terminal-salvage、证据读取、429 重派）继续以 run_id 单文件为准，多 attempt 依 provider_marker 的 additive `attempt` 字段区分。
