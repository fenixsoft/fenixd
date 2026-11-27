# 提案：车道探针稳态降噪与告警生命周期对齐

## 背景

repair/arbiter 车道环境前置探针（core/agent_runner/lane_preflight.py）在「daemon 进程环境无 ANTHROPIC_BASE_URL/AUTH_TOKEN/API_KEY 路由变量、config.yaml 无 agent.harness 段（CLI 默认档）」的部署形态下恒判不可判定（FALLBACK_VERDICT_INDETERMINABLE，lane_preflight.py:139-149）→ unhealthy（:264）判定，且探针逐拍重判、无状态边沿去重：每 60 秒节拍双发射点各打一条 WARNING（发射点 A lane_preflight.py:266-273 component=agent_runner；发射点 B fenixd.py:1290-1294 _lane_preflight_consume component=fenixd），约 1.6MB/天挤占 10MiB×5 滚动留存（约 3.5 天即可填满一轮，持续挤占排障留存窗口）。

**归属与现状对账（2026-11-27 评审实测修正）**：上述爆量现场为 dsh-plugins 与 fenix-desktop 两部署（与本仓共享同一框架源）——dsh-plugins 现存日志该 WARNING 16161 条、fenix-desktop 15823 条（含翻滚剪除的更早期段，累计与「逾 2 万对」量级吻合），台账告警 c15ad38d3e01（created 2026-11-16T16:18:46Z，与噪音起点同刻）即在 dsh-plugins；本仓 fenixd 部署自身进程环境含 10 个 ANTHROPIC_* 键、2026-11-08→11-27 日志窗口（1912 条 WARNING）零车道前置噪音、台账零在案条目——爆量与部署 env 形态强相关，而逐拍重发缺陷面是全部署共享的框架代码。在途 evo-repair-lane-credential-probe-fix 1.1 已于 2026-11-27T09:02Z 完成两部署 systemd.env 注入，daemon 重启后探针转 healthy、在案告警经 auto_resolve 收口（44186fac8677 handled_by=auto-resolve 即此）——本部署矩阵当前已无在燃噪音。但代码级缺陷仍在共享框架源中：任何后续环境劣化形态（dsh harness 默认档结构性不可判定、CLI 缺失、凭据缺失、env 代差回退等）会原样重放同型噪音循环，本 SPEC 据此收窄为**观测面机制硬化与生命周期对齐**。

告警生命周期失真同样实锤于 dsh-plugins 台账：lane_env_unavailable major 告警正文承诺「随恢复自动关闭，无需人工处置」（lane_preflight.py:407-420），但人工 handled 后周期拍依「人工已处理条目不再抑制新告警落地」设计（_lane_env_alert_inflight 的 not-handled 判据 :371-381）即重开同文新条——同型三度重开（c15ad38d3e01 于 2026-11-22T03:58:11Z 人工关闭、3b3a4abe8b0b 03:58:19Z 重开；再次人工关闭后 8508da76f772 于 11-25 重开；44186fac8677 于 11-26 重开），前两次为人工重复误工，三条 evidence 均 origin=periodic 且 reasons 同文（同判稳态重开实锤）。「超 24h 未处理」每日提醒（core/self_review.py:259、:263-292）无 signal_type 豁免分支，对该告警每日重翻，与正文承诺互相矛盾，形成假工单。

窗口内零实际损失（arbiter_ledger.jsonl 末条 2026-11-13T04:09Z，lane_env_unavailable 拦截=0），损失形态是纯观测面：日志留存被挤占、信噪比劣化、台账假工单反复重生。

## 目标

1. 探针稳态边沿发射：判定结论变化（含首判）即时打 WARNING；同一结论稳态期不再逐拍重打，降为每小时 1 条携带持续时长的心跳。判定结论本身与派发回落冻结闸拦截语义保持不变（不回退 evo-provider-fallback-dispatch-gate「不可判定→拦截+告警优于静默秒挂」的设计意图）。
2. 双发射点对齐：fenixd.py 自检消费点复用同一稳态判定，仅在边沿/心跳拍发射，消除同拍双行。
3. 告警生命周期对齐稳态：结构性稳态（不可判定且环境形态未变）的告警在人工 handled 后不因同一稳态被周期拍重开（一次性终态登记，闸覆盖全部告警登记入口）；判定改变（环境形态实测变化，或 evo-repair-lane-credential-probe-fix 1.2 试呼裁决翻转）才按新边沿重新登记；正文「自动关闭/无需人工处置」承诺与实际生命周期一致。
4. （撤销）原「>24h 提醒豁免」目标不再由本 SPEC 裁决：已提交的 evo-repair-lane-credential-probe-fix 1.3 对同一告警的 >24h 生命周期给出相反方向（超 24h 翻转「需人工升级」话术，制造真实升级工单以破无人值守挂账死锁）；本 SPEC 原拟的「豁免提醒消除假工单」与之冲突，撤销该目标并不改 core/self_review.py（Deliverables 同步移除）。如未来对其他告警形态的每日重翻噪音需治理，另立 SPEC。

## 非目标

- 不改探针判定结论、回落冻结闸与派发拦截行为（evo-provider-fallback-dispatch-gate 承辖）。
- 不做 daemon 环境变量改配与不可判定试呼（evo-repair-lane-credential-probe-fix 1.1/1.2 承辖；本 SPEC 与其组合而非重复）。
- 不改 core/self_review.py 提醒面：>24h 告警生命周期方向由 evo-repair-lane-credential-probe-fix 1.3 承接，本 SPEC 不与其竞裁。
- 不改 AdminStore 告警存储结构与 dedup_key 机制本体。
- 放行键 agents.allow_harness_default_fallback 只被派发闸消费、探针不读，本 SPEC 不依赖配置面。
