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

- [ ] 1.1 core/agent_runner/provider_circuit.py：把 UNRECOGNIZED_MODEL_TEXT_PATTERNS（:80）收口导出为可复用的 CLI stderr 诊断噪声 pattern 常量（按具体 pattern 枚举 [claude-code:*] 启动期诊断行）；:405-423 分类判据与 :443-479 瞬断判定不动

## 2. 消费端降噪

- [ ] 2.1 core/self_review.py：_scan_run_midflight（:854-919）stderr 分支的 first_stderr 选取（:902-903）跳过噪声行；stderr_count 保留全量计数；stderr 全为噪声行时 first_stderr 置空
- [ ] 2.2 core/knowledge_backfill.py：失败归因文本构造（:426-430）先按噪声常量逐行过滤 stderr 再取尾部；过滤后为空时回退 stdout 尾部

## 3. 测试

- [ ] 3.1 tests/test_self_review_midflight.py：扩展现有 stderr 采集用例——fixture 用 unrecognized_model 噪声行 + 真实诊断行，断言 first_stderr 取首条非噪声行、计数含噪声行、全噪声时置空
- [ ] 3.2 tests/test_knowledge_backfill.py：断言归因文本不含噪声行；stderr 全噪声且 stdout 含「API Error: Request rejected (429)」时归因回退 stdout 尾部