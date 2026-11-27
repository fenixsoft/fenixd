## Deliverables

```yaml
- path: core/knowledge.py
  kind: modify
- path: core/knowledge_audit.py
  kind: modify
- path: tests/test_knowledge_anchor_check.py
  kind: modify
- path: tests/test_knowledge_audit_pending_consumption.py
  kind: new
```

## 1. 锚点检查器目录引用放行

- [x] 1.1 core/knowledge.py（check_anchor_references 判定行 :889）：对目录级引用形态且 (proot/path) 为实存目录的 token 增加 is_dir() 放行，不再报「锚点悬空」；文件级判定与行号违例判定行为不变；与 validate_knowledge 的 sources 目录放行口径（:647）对齐。

## 2. 待人工发现登记与消费接线

- [x] 2.1 core/knowledge_audit.py：锚点悬空与行数硬顶两类待人工发现写入项目 .fenix/todo.md 独立前缀跟踪行（复用 upsert_todo_line），粒度逐页一行（前缀=固定段+页面 rel、行内逐发现列路径；新前缀 MUST NOT 与 TODO_ESCALATED_* 前缀构成前缀关系）；页内发现清零按空行纯清理摘行，发现集变化整组替换，不留陈旧欠账。
- [x] 2.2 core/knowledge_audit.py（报告渲染模板）：报告档位标签与实际通路对齐——「待人工/定向转写」措辞收敛（定向转写当前无实现通路），避免误导处置预期。

## 3. 测试

- [x] 3.1 tests/test_knowledge_anchor_check.py：新增目录引用放行用例——实存尾斜杠目录不报悬空、缺失目录仍报、文件级与行号违例判定不回归。
- [x] 3.2 tests/test_knowledge_audit_pending_consumption.py：覆盖 待人工发现逐页登记 todo 行/页内发现清零整行摘除/发现集变化整组替换/escalated 聚合行不被新前缀误清/报告档位标签断言；行数硬顶用例以临时夹具页驱动（当前知识树零破顶实例）。