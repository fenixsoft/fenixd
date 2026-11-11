# ADR-346：裁决自动执行策略引擎 daemon 侧单扫描环、执行复用单机器

date: 2026-11-11
status: accepted

## Context

升级处置链终点（Arbiter 产出明确推荐后的 pending 人工告警）无限期等人点击，实证空转 10h+ 且人工点击内容=机器推荐原文、信息量为零。需要策略引擎对满足判据的告警到点自动执行推荐 choice。引擎宿主有两个候选：dashboard 进程（常驻独立服务）与 daemon（告警生命周期与车道派发权威所在）；执行动作已有三处同源的单一机器（人工 alert-resolve、admin_monitor 直接路径、链 closed 出口共用 execute_choice_for_disposition）。备选形态：挂 30 分钟周期 full_scan（grace 30 分钟下实际到点延迟最坏 60 分钟，价值折半）、逐告警定时器（复杂度不值）。

## Decision

- 策略引擎为 daemon 侧独立模块 + 60 秒轻量扫描环（文件读 + 内存判据），装配于 daemon 主进程：引擎必须与 STATE 写权威同侧，不落 dashboard 进程——不随 dashboard 独立重启失联。
- 自动执行 MUST 复用 execute_choice_for_disposition 单机器（第四同源处），禁止为自动执行复制分支逻辑；留痕与人工点击同构，仅 actor=auto-policy 区分。
- fail-open：单告警判定异常单条捕获隔离；存储读失败整轮放弃；引擎构造/启动异常在 daemon 装配处降级为 None、缺位不阻塞其他车道；`auto_exec.enabled` 开关一键回退纯人工语义。

## Consequences

- 到点执行延迟上界 = grace 窗 + 一个扫描间隔（60 秒），可接受。
- dashboard 侧只做读时投影（auto_exec 字段读面合并），不持有执行权威。
- 后续一切新增裁决 choice 执行入口（人工、链、自动之外的新通道）一律复用同一执行机器，同源处随通道扩展；复制分支逻辑须显式 supersede。
- 引擎与告警生命周期同进程共生死：daemon 停机即自动执行暂停，存量 pending 由人工兜底、无状态残留（grace 窗读时计算不落盘，见 ADR-348）。
