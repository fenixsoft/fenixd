# 提案：车道探针稳态降噪与告警生命周期对齐

## 背景

repair 车道环境前置探针（core/agent_runner/lane_preflight.py）在本部署形态下结构性永判 unhealthy：daemon 进程环境无 ANTHROPIC_BASE_URL/AUTH_TOKEN/API_KEY 路由变量、config.yaml 无 agent.harness 段（CLI 默认档），探针按「不可判定」（FALLBACK_VERDICT_INDETERMINABLE，lane_preflight.py:143-145）→ unhealthy（:229-232）判定，自 2026-11-16T16:18:46Z 起每 60 秒重判并双组件各打一条 WARNING（发射点 A lane_preflight.py:250-253 component=agent_runner；发射点 B fenixd.py:1187-1191 _lane_preflight_consume component=fenixd），两处均无状态边沿去重，7.1 天累计逾 2 万对，占留存日志 WARNING 行 93.2%、窗口字节 88.4%，约 1.6MB/天挤占 10MiB×5 滚动留存（约 3.5 天即可填满一轮，持续挤占排障留存窗口）。

告警生命周期同样失真：lane_env_unavailable major 告警正文承诺「随恢复自动关闭，无需人工处置」，但人工 handled 后周期 tick 依「人工已处理条目不再抑制新告警落地」设计 8 秒即重开新条（c15ad38d3e01 于 2026-11-22T03:58:11Z 关闭、3b3a4abe8b0b 03:58:19Z 重开并挂起至今）；「超 24h 未处理」每日提醒（core/self_review.py:250、:254-283）无 signal_type 豁免分支，对该告警每日重翻，与正文承诺互相矛盾，形成假工单。

窗口内零实际损失（arbiter_ledger.jsonl 末条 2026-11-13T04:09Z，lane_env_unavailable 拦截=0），损失形态是纯观测面：日志留存被挤占、信噪比劣化、台账假工单每日重翻。

## 目标

1. 探针稳态边沿发射：判定结论变化（含首判）即时打 WARNING；同一结论稳态期不再逐拍重打，降为每小时 1 条携带持续时长的心跳。判定结论本身与派发回落冻结闸拦截语义保持不变（不回退在途 evo-provider-fallback-dispatch-gate「不可判定→拦截+告警优于静默秒挂」的设计意图）。
2. 双发射点对齐：fenixd.py 自检消费点复用同一稳态判定，仅在边沿/心跳拍发射，消除同拍双行。
3. 告警生命周期对齐稳态：结构性稳态（不可判定且环境形态未变）的告警在人工 handled 后不因同一稳态被周期 tick 重开（一次性终态登记）；环境形态实测变化（路由变量出现/消失）才按新边沿重新登记；正文「自动关闭/无需人工处置」承诺与实际生命周期一致。
4. 提醒豁免：「超 24h 未处理」每日提醒对自动关闭型（负载明示无需人工处置语义）告警豁免或降级展示，停止每日重翻假工单。

## 非目标

- 不改探针判定结论、回落冻结闸与派发拦截行为（在途 evo-provider-fallback-dispatch-gate 管辖）。
- 不做 daemon 环境变量改配（部署侧动作由人工按需决定；放行键 agents.allow_harness_default_fallback 只被派发闸消费、探针不读，本 SPEC 不依赖配置面）。
- 不改 AdminStore 告警存储结构与 dedup_key 机制本体。