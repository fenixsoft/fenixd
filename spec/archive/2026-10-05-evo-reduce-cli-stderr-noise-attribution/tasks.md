## Deliverables

```yaml
- path: core/agent_runner/provider_circuit.py
  kind: modify
- path: core/self_review.py
  kind: modify
- path: core/knowledge_backfill.py
  kind: modify
- path: tests/test_self_review_midflight.py
  kind: modify
- path: tests/test_knowledge_backfill.py
  kind: modify
```

## 1. 噪声常量收口

- [x] 1.1 core/agent_runner/provider_circuit.py：**新增**独立常量 CLI_STDERR_NOISE_TEXT_PATTERNS（派生自 UNRECOGNIZED_MODEL_TEXT_PATTERNS，按具体 pattern 枚举 [claude-code:*] 启动期诊断行，如 [claude-code:unrecognized_model]），供消费端统一判别；既有 UNRECOGNIZED_MODEL_TEXT_PATTERNS（:80）元组**原样保留**、继续作为 :420 分类判据唯一 pattern 源，不改写不重命名；:405-423 分类判据与 :443-479 瞬断判定不动

## 2. 消费端降噪

- [x] 2.1 core/self_review.py：_scan_run_midflight（:854-919）stderr 分支的 first_stderr 选取（:902-903）跳过噪声行；stderr_count 保留全量计数；stderr 全为噪声行时 first_stderr 置空
- [x] 2.2 core/knowledge_backfill.py：失败归因文本构造（:426-430）先按噪声常量逐行过滤 stderr 再取尾部；过滤后为空时回退 stdout 尾部

## 3. 测试

- [x] 3.1 tests/test_self_review_midflight.py：扩展现有 stderr 采集用例——fixture 用 unrecognized_model 噪声行 + 真实诊断行，断言 first_stderr 取首条非噪声行、计数含噪声行、全噪声时置空
- [x] 3.2 tests/test_knowledge_backfill.py：断言归因文本不含噪声行；stderr 全噪声且 stdout 含「API Error: Request rejected (429)」时归因回退 stdout 尾部