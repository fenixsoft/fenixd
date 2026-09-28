# add-knowledge-audit-finding-ledger

## Why

add-knowledge-atlas-maintenance 落地的知识审计车道对疑点无记忆：初筛 _scan_semantic（core/knowledge_audit.py:372-436）是每次全量重扫的纯函数；no-conflict 判定只写进每日被整体覆盖的 .fenix/knowledge_audit_report.md；状态文件只有日期戳。真实运行中同批 10 对疑点连续两天逐字重出（两轮 20 个复核 run，9 个/天是白跑的无矛盾复核，仅产出 492dd241、9ae0c7a8 两笔纠偏）；待人工队列被 3 条永久性 ADR 断链误报长期占位且无消费闭环；同一疑点跨日由「无矛盾」翻转为「确认」（疑点 8）也无累计感知。复跑实测：纠偏后今日重扫仍产出完全相同的 10 对疑点，第三轮浪费已注定。

## What Changes

1. audit 车道新增疑点台账 .fenix/knowledge_audit_findings.json（指纹为键、原子写）：记录每个语义疑点的 kind、页对、规则行、页面内容哈希、判定历史与状态。
2. no-conflict 判定按内容豁免：两页全文 sha256 均未变时次日初筛跳过派发复核（计 exempt）；任一页内容变更自动解冻回 suspected 重新派发——保住「复核结论会翻转」情形的再审价值。
3. 待人工疑点挂起等消费：不再自动重派；同批内因扫描快照滞后产生的重复疑点标 superseded-in-batch 跳过。
4. 同一疑点连续两轮复核均无确定性判定即升级：状态置 escalated，写入 .fenix/todo.md（复用 append_todo_line）并停止自动复核，人工仲裁消费后清除；豁免解冻重派不计入升级轮次。
5. 同模块捆绑修复两项实现缺陷：ADR 断链检查改按 ADR-\d{3} 前缀匹配 slug 文件名（消除 ADR-015/019/034 三条永久误报）；每日检查点回写 state 改为先重读合并（救活 last_scale 与规模趋势基线）。

## Non-Goals

- 不改初筛算法本身，不调整扫描频率与车道调度。
- 不回填历史 run 的判定（台账自落地日起热启动）。
- 人工升级走既有 todo.md 登记通道，不扩展 admin_alerts 作用域。
- 不做台账条目清理与容量治理。

## Impact

- Specs: specs/knowledge-audit/spec.md（ADDED：疑点台账持久化、内容豁免、挂起与升级、ADR 前缀匹配、state 合并回写）
- Code: core/knowledge_audit.py（台账读写、复核循环接入、ADR 前缀匹配、state 合并写回）、core/config.py（get_knowledge_lane_config 增豁免开关与升级阈值键）
- Config: .fenix/config.template.yaml knowledge 节登记新键
- Tests: tests/test_knowledge_audit.py 增台账读写、豁免/解冻/升级、ADR 前缀、state 合并用例