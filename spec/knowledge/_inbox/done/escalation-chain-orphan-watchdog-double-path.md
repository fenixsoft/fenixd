# 处置链孤儿看护与链终点双通道重复出件（首例实证，2026-11-03）

## 背景

add-escalation-chain-admin-arbiter 落地后首例真实链路事件：spec
add-knowledge-inbox-pipeline 的 `verify_env_blocked` 升级边信号入链后，链头
Admin run 与 spec 冻结竞态秒死，用户在人工队列看到「Administrator 处置中断」
critical 告警（孤儿看护产出），提问「为什么没有被 arbiter 处理」。全链取证还原
了看护通道与链通道的并行关系，暴露三个结构性缺口。

## 结论（当前事实）

- **AdminMonitor 孤儿看护的 pending 超时升级是链外直写出口，不经 arbiter**：
  实现在 `core/admin_monitor.py`（≈L6600）以 `store.append(kind=ESCALATION)`
  直写人工队列。触发面黑名单制注册在两个咽喉层（`freeze_for_human` 全族 +
  `_send_human_escalation_alert` 调用点，arbiter-lane.md L10）——契约按**发射
  通道**治理而非告警语义，孤儿看护是第三个更老的发射通道（09-02 起存在），
  链 SPEC 显式豁免（「pending 超时升级语义不变」）。豁免对「链死了报警」场景
  是必要设计（链无法处置自己的死讯，入链即自环）；但看护对**链在办件**开火时
  完全链盲——SPEC 1.2 装的链感知（`_reap_chain_inflight`）只用于超时清除在办
  登记，孤儿接管路径开火前不查链/arbiter 状态，且链让行（deferred）时清空
  in_flight 不留转级痕迹，无从查起。「看护通道存在=设计内；对链在办件重复
  出件=实现缺口」——链在飞时人工队列出现看护 critical 告警（早链终点 3 分钟）
  违背「人工只是链终点失败后的例外出口」的门面承诺。
- **孤儿看护告警的归因模板不可信**：模板固定写「疑似 daemon 重启/崩溃连带杀死
  admin」，而本例 admin run 死因是 spec 冻结击杀（frozen-terminated，先于
  daemon 重启 5 分钟；daemon 是 restart_request 优雅重启 rc=0）。排查以 run
  终态证据为准，勿按告警叙事方向查。
- **链 deferred（让行）无唤醒路径**：链头失败后若命中「同 spec 在飞 admin
  run」互斥守卫即让行退出（`core/pm_engine/escalation_chain.py` ≈L665，注释
  「信号若复发由下一次触发重新入链」）；被让行对象不是链成员，其死亡不回喂链，
  信号也不复发——链静默挂起，直到 daemon 重启的启动回扫才把在办件转派
  arbiter。
- **冻结×链头派发竞态烧配额**：spec frozen 落盘后 ~100ms 内链头 Admin run
  spawn 即被 frozen-terminated（0.016s 空壳，0 轮），链记 失败(1/2)——一次
  配额被纯竞态烧掉。
- **看护不感知链内转级**：链已把在办件转派 arbiter（在飞调查中），看护仍按
  pending 处置条目的 15 分钟宽限独立升级人工，产出与链终点裁决包平行的重复
  人工告警（本例早链终点 3 分钟）。「链上任一级后续成功闭环时自动收口」只覆盖
  链终点上升件，不覆盖看护件。

## 证据（时间轴，2026-11-03 本地时；日志为 UTC）

- 19:13:04.758 admin_monitor choice 消费拒绝（revise_scenario_reverify 未注册
  manual-intervention 桶）+「进程代码陈旧已请求重启（重启在途）」
- 19:13:05.079 spec frozen=True 落盘；05.198 链入链（链头 Admin）→ run 4385
  05.368 即被冻结击杀（0 轮空壳）→ 05.381 链记 失败(1/2) → 05.392 链让行
  （同 spec 在飞 admin run=4386，manual-intervention 通道）
- 19:13:06.096 run 4386 同样冻结秒死；此后链零动作直至重启
- 19:18:08 supervisor 检出 restart_request → 19:18:16 daemon 重启完成；
  16.671 arbiter 启动回扫入队（source=startup）
- 19:18:16–19:31:05 arbiter 调查 768s/1.44M tokens，判「三重白名单外」，立项
  2 个 drafted（register-revise-scenario-choice-on-intervention-signals /
  judge-repair-scenario-writeback-gate）
- 19:28:17 孤儿看护升人工（critical，id=36ce0eb408ea）+ 原 pending 处置翻
  escalated（id=c0ee3b337203）；run 4386 的 pending（id=58a6bebc956d，宽限界
  晚 0.3s 错过当轮巡检）仍挂，后续巡检可能再产一条孤儿告警
- 关键文件：`.fenix/escalation_chain_state.json`（该签名 admin_attempts=1 /
  arbiter_rulings=1）、`.fenix/arbiter_ledger.jsonl`（arb-ledger-1793705465700
  主裁决）、`.fenix/admin_alerts.json`、`.fenix/logs/fenixd.log`
  2026-11-03T11:13–11:31 段、`core/admin_monitor.py` 孤儿升级写点、
  `core/pm_engine/escalation_chain.py` deferred 分支

## 附带处置指引（事件级，非规则）

孤儿告警可按重复件人工消解；底层 spec 修复走 arbiter 裁决选项 A——已验证的
修复载荷保全于 `.history/fixed-scenarios-1793703779.json`（14 场景 0 错），
arbiter 台账明示「人类落地选项 A 直接取用，勿删」。三缺口治理已合并立项：
`fix-escalation-chain-watchdog-yield-gaps`（2026-11-03，full 模式，链痕单源查询/
deferred 留痕与看护重派/frozen 预检与空壳不计配额/归因取证）。
