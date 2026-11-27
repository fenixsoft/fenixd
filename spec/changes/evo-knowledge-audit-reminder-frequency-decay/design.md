## 设计

### 改动点

core/knowledge_audit.py（提醒生成链）：

- 生成入口处（_escalated_summary/_escalated_todo_line 链路，:381-:413；落库点 upsert_todo_line :2333）加节拍判断：knowledge_audit_state.json 增记 last_escalated_reminded_date 与 last_escalated_fingerprint_set；
- 降频条件：escalated 集合持续零消费超 stale_days（复用缺省 7 或同值常量）且距 last_escalated_reminded_date 不足 7 天时，跳过 todo 行改写（保持旧行不变）；满 7 天间隔才更新文案并刷新日期；
- 文案注记：降频态的聚合行尾追加「（已降频为每周一拍、欠账仍在）」；
- 恢复：consume_arbitration（:680）消费任一 escalated 指纹时清除降频态（重置节拍日期），下次体检即恢复每日节拍；全部消费走既有止拍语义。

### 状态存储

复用 .fenix/knowledge_audit_state.json（已有 last_audit_date 等字段），新增两个键，不新增文件。

### 兼容性

- todo 聚合行前缀（TODO_ESCALATED_AGG_PREFIX，:111）与原位替换语义不变；
- disputed 注记（:88-94、:421-440）与消费检查点（fenixd.py:1822-1824）零改动。

### 测试设计

tests/test_knowledge_audit_reminder_decay.py（新建）：未超龄每日一拍；超 7 天未消费降为每周一拍（7 天内不改写 todo 行）；消费后恢复每日节拍；降频文案注记存在；disputed 注记不受影响。