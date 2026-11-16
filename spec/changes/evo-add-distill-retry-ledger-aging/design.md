# 设计：蒸馏重试台账欠账龄期升级与节流

## 现状代码（2026-11-16 实测；姊妹 SPEC evo-fix-distill-retry-ledger-auto-close 已合入主树）

- core/knowledge.py check_retry_ledger_age（:1639）：催办发射单点——AdminStore.append(kind=SIGNAL) 落 knowledge_distill_retry_stale 记录（:1727 起），severity 固定 "warning"（:1732）。description 已以「归档名（登记 YYYY-MM-DD）」形态携带归档名与登记日期（_retry_display_names），缺当前龄期；recommended_action（:1719-1722）仍指向已排除的 unrecognized_model 假说。
- core/knowledge.py RETRY_STALE_AFTER = timedelta(hours=24)（:1390 附近）：首警阈值；龄期按行归位日期节本地零点起算（_section_midnight，天粒度）。
- 节流现状：磁盘持久状态文件 .fenix/knowledge-distill-retry-state.json（RETRY_REMIND_STATE_RELPATH，:1403）承载「同日且 stale 集合指纹未变则跳过」（:1709-1711 判据），重启读盘恢复；原「进程内当日幂等标记」已退役。指纹 _stale_retry_fingerprint（:1620 附近）= sha256(排序「登记日期|行文本」拼接)，不含应发级别。状态写入持 flock + 原子回写、「未知键保留，前向兼容」（_save_retry_remind_state docstring）——新增键安全。
- 挂载：fenixd.py:1823-1825 主循环 300s 检查点调用 check_retry_ledger_age；dashboard --serve 不接入（既有口径不变）。
- admin_store.py 既有原语（本 SPEC 仅参考，不引入为第二条节流）：latest_signal（:1479，窗口=max(created,last_seen)、severity 参数同级别匹配）、append_if_absent（:941）、has_unhandled_fingerprint（:1652）、ESCALATION 常量（:43）。

## 设计要点

1. 龄期展示：发射时在 description/evidence 补当前龄期（由日期节零点起算，与 _retry_display_names 的登记日期同源，展示为小时/天）；归档名与登记时刻沿用既有展示形态。同轮把 recommended_action 改为 proposal 附节口径（约束重发蒸馏的链接范围，或人工整理归档知识页后勾销台账），移除对已排除 unrecognized_model 假说的指引。
2. 升级判定：欠账龄期超 72 小时（具名常量 RETRY_ESCALATE_AFTER = timedelta(hours=72)，紧邻 RETRY_STALE_AFTER 注明权衡）时 severity 提为 major，24~72h 维持 warning；升级在现行 kind=SIGNAL 通道内完成，不使用 kind=ESCALATION——后者进入 pending_escalations 人工升级队列并参与处置链闭环对账（unhandled_for 仅匹配 ESCALATION；close_escalations_by_chain 按 chain.signature 收口），面向 run 失败处置语义，台账催办入链会误耗 admin 配额。
3. 节流基线：维持现行状态文件持久去重（日粒度 + 指纹），不另设窗口。原草案「把进程内当日标记替换为 AdminStore 判窗（建议 6h 窗口）」的前提已被姊妹 SPEC 推翻——进程内标记已退役、持久化已落地；再引入 6h 窗口反而把「至多每日一条」放宽为「至多每 6 小时一条」，属倒退。
4. 升级穿透：应发级别纳入现行节流状态——状态文件新增 last_severity 键（前向兼容语义下安全），跳过判据「同日且指纹未变」扩为「同日且指纹未变且应发级别未升」（级别序 warning < major）；级别提升时穿透立即发射，发射成功（append 返回非 None）后随 _save_retry_remind_state 一并回写新级别，拒写不回写、下一周期重试穿透（与现行「被拒写下一周期重试」语义一致）。
5. 每日自省数据摘要无需改动：self_review.py 数据摘要第 3 段「admin 告警与处置记录（窗口内）」（:2599 起，_collect_admin_summary :2811）按窗口收集全部 kind=SIGNAL 记录（不分 severity），升级件自然进入固定视野。

## 风险与回退

- 穿透仅在级别提升边沿触发一次：同级后续发射回到现行日粒度节流，不会造成高频重发；条目处置后 stale 清空，新欠账经「跨日或指纹变化」放行从 warning 起步，无升级态残留泄漏（last_severity 回写「上次实际发射级别」，级别回落随下一次发射自然覆盖）。
- 升级阈值与节流解耦：72h 为具名常量并注释权衡，后续可配。
- 台账条目处置后信号自然消失，无需新增核销逻辑（与条件消失自动复位的现状一致）。
