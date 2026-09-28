# knowledge-audit 能力增量（delta）

## ADDED Requirements

### Requirement: 疑点台账持久化

audit 车道 SHALL 将每个语义疑点的指纹、判定历史与状态持久化到 .fenix/knowledge_audit_findings.json（原子写），指纹为 kind 与两页相对路径及归一化规则行的哈希，不依赖 run 输出文本。

#### Scenario: 判定回写

- **WHEN** 复核 run 产出 no-conflict 或重写提交
- **THEN** 台账中该指纹的 verdicts 追加判定、日期与提交，status 相应更新
- **AND** 次日初筛对同指纹具备历史判定感知

### Requirement: no-conflict 按内容豁免

同指纹上一次判定为 no-conflict 且两页全文 sha256 均未变时，audit 车道 SHALL 跳过为其派发复核 run 并计入 exempt 统计；任一页内容哈希变化时 SHALL 自动解除豁免并正常派发。

#### Scenario: 内容未变不复发

- **WHEN** 次日初筛产出与台账 exempt 条目相同指纹的疑点且两页内容哈希未变
- **THEN** 不派发复核 run，体检计数出现 exempt
- **AND** 台账记录豁免发生时间

#### Scenario: 内容变更解冻

- **WHEN** 某页内容被修改使其哈希偏离台账记录
- **THEN** 该疑点回 suspected 并照常派发复核

### Requirement: 待人工挂起与第二轮升级

标记待人工的疑点 SHALL 停止自动重派复核；同批内规则行来自扫描开始时快照且涉及页在本批已被纠偏的疑点 SHALL 标记 superseded-in-batch 并跳过；同一指纹连续两轮进入复核且两轮均未产出确定性判定（状态仍 suspected，如转写失败回滚）时，SHALL 置 escalated、写入 .fenix/todo.md 并停止自动复核，直至人工消费后清除；豁免解冻触发的重派不计入升级轮次（每次内容变更重置），与「no-conflict 按内容豁免」的解冻重派要求不相冲突。

#### Scenario: 第二轮升级人工

- **WHEN** 同一指纹第二轮仍被判疑似
- **THEN** 不再派自动复核，todo.md 出现该疑点的升级登记
- **AND** 状态保持 escalated 直到人工处置

### Requirement: ADR 断链前缀匹配

检查知识页 ADR 引用断链时 SHALL 按 ADR-\d{3} 前缀匹配盘上 slug 形态文件名；存在对应 slug 文件的引用不得判为断链。

#### Scenario: slug 形态引用不再误报

- **WHEN** 页面引用 ADR-015 且盘上存在 ADR-015-<slug>.md 形态文件
- **THEN** 该引用不进待人工队列

### Requirement: 状态检查点合并回写

每日检查点写回 knowledge_audit_state.json 前 SHALL 重读盘上状态并合并；run_audit 内部的键写入不得被陈旧副本覆盖；连续两日体检后报告 SHALL 出现基于 last_scale 的规模趋势后缀。

#### Scenario: last_scale 不再丢失

- **WHEN** 体检写入 last_scale 后检查点回写 state
- **THEN** last_scale 键仍在且次日报告出现「上次 X 行」趋势后缀