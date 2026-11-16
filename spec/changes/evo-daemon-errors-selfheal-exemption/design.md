# Design: daemon-errors-selfheal-exemption

## 背景锚点

- 判据与豁免面：core/admin_monitor.py:5366 _detect_daemon_errors；阈值常量 :169-171（THRESHOLD=2/WINDOW=10/MAX_GAP=5）；既有压制分支（阈值判据 :5413-5414、最近间隔判据 :5416-5417、重启冷却窗 :5426-5436）与孪生合并聚合 :5473-5477；critical 模板 :5847/:5889；升级 append :5445。
- 自愈链：spec/knowledge/domains/worktree-vc/wip-defer-merge-retry.md 载「拦截即落等待标志，周期复查、自动 merge-only 合回，超限降级人工」；消费者 core/pm_engine/dispatch/queue.py:4269/:4009，预算常量 queue.py:60-61（90 分钟/6 次超限走人工）；本例闭环 c836b596ba9e（04:18:12Z）。
- ERROR 源头：core/worktree_manager/mergeback.py:752-777（escalate 出口 logger.error :777，前缀文案 :759 全仓无其他消费者——重试侧降 INFO 无下游解析破坏）；escalate 缺省策略出自 add-pipeline-throughput-governance D2（mergeback.py:360-375 docstring）。
- 注册表先例：core/alert_lifecycle.py:98 SELF_HEAL_SIGNAL_TYPES。

## 方案

1. 注册表放 admin_monitor.py 模块级常量（单源），条目={component 匹配，message 前缀，consumer 说明}；在升级 append 前（:5445 一带，逐指纹循环内 last_err[fp] 持有 component+message 原文供前缀匹配）加签名匹配 continue；不接任何人工复位通道（防毒对齐 state_machine.py:676-677 精神）。豁免跳过覆盖两个升级维度（窗口内复现与跨日同刻复发），跨日维度的可见度由消费端预算超限降级人工告警（queue.py:60-61）与命中审计计数兜底。
2. 源头聚合：mergeback.py 重试侧读重试计数上下文（queue.py:4009/:4269 传入或 _merge_retry_first_at 在场即非首阻），retry>0 的重复拦截改 logger.info 聚合行（含 retry 序号与间隔），首条保持 ERROR。
3. 灰区对冲：若自愈消费者失效成真故障——豁免命中计数留痕+注册表条目注明消费者与超限降级人工语义；超限后的新形态 ERROR（换签名/持续超窗）不受豁免影响仍会升级。

## 风险

- 签名前缀匹配过宽误伤真实故障——前缀含 policy=escalate 字面与组件名，匹配面收窄。
- promotion lint 族消费者（恢复节拍）停摆时同类 ERROR 长期静默——审计计数+既有每日龄期盘点（core/self_review.py:254 _unhandled_escalation_aging）兜底可见度。