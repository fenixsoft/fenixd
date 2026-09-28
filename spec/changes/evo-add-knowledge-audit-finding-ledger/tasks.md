## Deliverables

```yaml
- path: core/knowledge_audit.py
  kind: modify
- path: core/config.py
  kind: modify
- path: .fenix/config.template.yaml
  kind: modify
- path: core/knowledge_backfill.py
  kind: reference
- path: tests/test_knowledge_audit.py
  kind: modify
```

## 1. 台账读写与指纹

- [x] 1.1 core/knowledge_audit.py：新增 _load_findings_ledger/_save_findings_ledger（原子写，对齐 _read_state/_write_state 模式），台账文件 .fenix/knowledge_audit_findings.json；指纹 = sha256(kind + 两页 rel + 归一化规则行 + digits)，复用既有归一化计算（约 :368-369/:382）
- [x] 1.2 core/knowledge_audit.py：按设计实现条目 schema（kind/pages/rules/page_hashes/verdicts/status/first_seen/updated_at，status 五态）

## 2. 复核循环接入

- [x] 2.1 core/knowledge_audit.py：run_audit 转写循环（约 :640-698）spawn 前查台账，命中 no-conflict 豁免且两页 sha256 未变则跳过派发并计入 exempt；任一页内容哈希变化则解冻回 suspected 正常派发；run_audit 增 config 形参（缺省回落 {}）并由 knowledge_daily_check 挂载点（约 :129）透传；_render_report 计数行与完成日志同步增 exempt 档（两处现硬编码四档）
- [x] 2.2 core/knowledge_audit.py：每个判定产出后回写台账（no-conflict 记页面哈希并豁免，重写提交记 fixed），替换现状只写每日覆盖报告的单路落盘
- [x] 2.3 core/knowledge_audit.py：同批快照滞后重复（规则行来自扫描开始快照、涉及页本批已纠偏）标记 superseded-in-batch 跳过（「本批已纠偏」含机械自修段提交涉及的页）
- [x] 2.4 core/knowledge_audit.py：台账中同一指纹连续两轮进入复核且均未产出确定性判定（仍 suspected，如转写失败回滚）时置 escalated（豁免解冻重派不计入升级轮次），复用 core/knowledge_backfill.py 的 append_todo_line 登记 todo.md 并停止自动复核，人工消费后清除

## 3. 同模块缺陷修复

- [x] 3.1 core/knowledge_audit.py：ADR 断链检查（约 :311）由精确名改为按 ADR-\d{3} 前缀匹配 slug 文件名，消除 ADR-015/019/034 三条永久误报
- [x] 3.2 core/knowledge_audit.py：每日检查点回写 state 前重读盘上状态合并（约 :122 与 :141-142/:155-156），修复 last_scale 被陈旧副本覆盖丢失，恢复规模趋势后缀

## 4. 配置键与模板

- [x] 4.1 core/config.py：get_knowledge_lane_config 增 no_conflict_exempt（默认 true）与 escalate_after_rounds（默认 2）两键及缺省处理
- [x] 4.2 .fenix/config.template.yaml：knowledge 节登记两新键并附注释

## 5. 测试

- [x] 5.1 tests/test_knowledge_audit.py：台账读写原子性与指纹稳定性用例
- [x] 5.2 tests/test_knowledge_audit.py：内容未变豁免跳派、内容变更解冻重派、第二轮疑似升级 todo 登记且不再派发三组用例（复用 run_audit 既有 spawn/commit 注入缝）
- [x] 5.3 tests/test_knowledge_audit.py：ADR slug 文件名前缀匹配用例（以 ADR-015/019/034 实况为夹具）与 last_scale 跨检查点持久用例
