## Context

2026-11-03 `add-knowledge-inbox-pipeline::verify_env_blocked` 首例真实链路事件取证
（全文见 `spec/knowledge/_inbox/escalation-chain-orphan-watchdog-double-path.md`）
暴露三缺口：孤儿看护对链在办件重复出件（19:28 看护 critical 早于链终点裁决包
3 分钟）、冻结×链头派发竞态烧配额（admin run 0.016s 空壳仍记失败 1/2）、deferred
让行静默挂起（链空转 5 分钟至 daemon 重启回扫）。三处修改点集中在
`core/pm_engine/escalation_chain.py` 让行/入链段与 `core/admin_monitor.py` 孤儿
接管路径，共享「链痕」这一新概念：能证明「该签名正被链接管」的状态痕迹。

## Goals / Non-Goals

**Goals**：

1. 同签名链痕在场时，孤儿看护抑制重复出件；链痕消失后兜底升级语义保留
2. deferred 让行从「静默丢弃等复发」改为「留痕 + 看护扫描重派」，消除挂起
3. 冻结竞态不再烧配额：派发前预检 + frozen-terminated 空壳不计尝试双保险
4. 孤儿告警归因按 run 终态证据生成，废弃误导性固定模板

**Non-Goals**：

- 不做通道归一：孤儿升级仍是链外直写人工队列（不入链、不走咽喉层）——看护是
  链的电路保护器，链死了的报警不能让链自己接（防自环）
- 不改链终点上升件语义、黑名单 kill switch、降级 fail-open 既有口径
- 不改链配额数值（2/2）与复位窗语义

## Decisions

**D1 链痕单源查询口**：看护抑制与重派判定共用一个查询函数（输入签名，输出
`{in_flight: bool, deferred: list, arbiter_active: bool}`）。in_flight/deferred
读 `.fenix/escalation_chain_state.json` 同名区；arbiter 在飞读 arbiter 单飞队列
既有注册（`pm_engine/arbiter` 队列状态的只读访问，不新建注册表）。链状态文件
缺失/损坏按零命中降级（fail-open，对齐看护既有链缺席口径）。

**D2 deferred 留痕形态**：in_flight 区条目扩展 `phase: "deferred"` +
`yield_to`（被让行对象标识：admin_run_id 或通道标记）+ `deferred_at`。现行
`mark_in_flight` 写的条目视为 `phase: "admin"`（缺字段向后兼容）。让行分支从
「clear 整条」改为「改写 phase」；reap 逻辑按既有超时阈值一视同仁清理（不因
phase 特判放行）。

**D3 重派挂看护巡检节拍**：不新增线程/定时器（对齐本仓「挂既有巡检循环」范式）。
AdminMonitor 巡检中、`_reap_chain_inflight` 同拍新增 deferred 扫描：被让行 run
已终态（复用孤儿路径的 run 末事件终态读法）且信号未收口（spec 仍 blocked/frozen
或 pending 告警在场）→ 调链派发器入口重派（单飞/互斥守卫生效，防重派风暴）；
spec 已解冻且信号已收口 → 仅清条目。frozen 预检转 deferred 的条目（yield_to
为空）按「spec 已解冻」作为重派条件，同一扫描覆盖。

**D4 frozen 预检与配额语义**：`_run_admin_phase` 派发前查 spec 态（既有
`_resolve_state_machine` 通路），frozen=True → 不派发、转 deferred 留痕、不计
配额。防御纵深：Admin 失败计点处判 run 终态——0 API 轮次 + frozen-terminated
双条件成立才视为未尝试（跑过若干轮后被冻结击杀仍计失败，防误伤）。

**D5 归因生成**：孤儿升级写点读 run 文件末事件终态（复用 `_run_last_result_event`
同型尾部窗口读法），映射归因文案并附终态原文摘录入 evidence；读失败/无终态 →
保守「死因不明（run 证据缺失）」。interrupted=已知中断不告警口径原样前置。

## Risks

- **重派风暴**：deferred 重派经链派发器单飞+互斥守卫天然限流，且扫描挂 5 分钟
  巡检节拍；最坏情况是每轮巡检一次重派尝试，可接受
- **签名口径漂移**：deferred 留痕、看护查询、重派入参三处必须同源构造签名
  （复用链派发器既有签名函数），评审重点
- **旧形态兼容**：daemon 滚动窗口内状态文件可能同时存在新旧条目形态，读侧按
  缺 phase=「admin」兼容；测试覆盖混合形态
- **误伤计失败**：frozen-terminated 判据用「0 轮」硬条件兜底，避免把「跑了大半
  被冻结终止」的真实失败也豁免

## Migration

无存量数据迁移：deferred 是新增条目形态，现行状态文件无 deferred 条目；in_flight
区现存条目读侧自动按 admin 相待。daemon 合并后需重启生效（restart_request 交付项，
supervisor 消费信号完成实际重启）。
