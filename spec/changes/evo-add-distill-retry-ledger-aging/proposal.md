# 提案：蒸馏重试台账欠账龄期升级与节流

## 背景

归档 SPEC 的知识蒸馏失败会登记重试台账（knowledge-distill-pending.json 与 todo 勾选项），并由 knowledge_distill_retry_stale 信号提醒欠账。2026-10-30 dsh-plugins 项目归档 spec 2026-10-30-add-dsh-dashboard-bridge 的知识页产出因三轮链接校验违规被放弃（fenixd.log 三轮 run 均报链接越出知识真相源目录，模型拒识假说已排除），台账条目登记后 13 天无人处置，期间该信号发射 26 次全部零消费。其中 17 次落在 daemon 重启后约 5 分钟——彼时发射幂等靠进程内当日标记、重启即清零重发；该缺口已由姊妹 SPEC evo-fix-distill-retry-ledger-auto-close 关闭（幂等去重已迁为磁盘持久状态文件 .fenix/knowledge-distill-retry-state.json，同日不重发、重启读盘恢复），本 SPEC 不再处理此问题。信号自带的排查指引（recommended_action）至今仍指向已排除的模型拒识假说（core/knowledge.py check_retry_ledger_age 发射点实测），误导人工处置。

## 目标

1. 龄期展示：信号正文携带台账条目登记时刻、当前龄期与对应归档 spec 名，人工一眼看到欠账挂了多久。
2. 超期升级：欠账超 72 小时未处置时信号升级为 severity=major（在现行 kind=SIGNAL 通道内升级；不使用 kind=ESCALATION——后者进入 pending_escalations 人工升级队列并参与处置链闭环对账，面向 run 失败处置语义，台账催办入链会误耗 admin 配额），使欠账进入更高优先级视野；每日自省数据摘要的 admin 告警段按窗口收集全部 kind=SIGNAL 记录（core/self_review.py _collect_admin_summary），升级件自然进入固定视野，无需额外注入代码。
3. 升级穿透与节流基线：节流的持久化与跨重启语义已由姊妹 SPEC evo-fix-distill-retry-ledger-auto-close 落地（日粒度 + stale 集合指纹，重启不重发），本 SPEC 不另设节流机制、不放宽现行「至多每日一条」节奏；在其上把应发级别纳入节流状态，使欠账龄期跨过 72 小时门槛的首次升级发射不被「同日且指纹未变」判据吞掉、立即发出。

## 非目标

- 不自动处置台账条目（处置仍是人工动作）。
- 不修改知识页链接校验规则：三轮违规是模型产出未收敛，重试预算机制本身有效（同日姊妹 spec 第 3 轮即改合规）。
- 不改动蒸馏批次调度与观测聚合（fix-distill-observation-gaps 在途件管辖）。
- 不改动现行持久节流基线机制（evo-fix-distill-retry-ledger-auto-close 落地的 .fenix/knowledge-distill-retry-state.json 日粒度 + 指纹去重口径），仅叠加升级级别穿透；不引入 AdminStore latest_signal 判窗等第二条节流（会把「至多每日一条」放宽为窗口级高频重发，属倒退）。

## 附：在途个例的人工处置提示

dsh-plugins todo.md 第 381 行欠账的根因已可从日志裁决：知识页链接指向 spec/archive/ 目录越出真相源。人工处置时按「重发蒸馏时约束链接范围，或人工整理归档知识页后勾销台账」动手，勿按告警指引排查 unrecognized_model。
