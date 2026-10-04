## Deliverables

```yaml
- path: core/self_review.py
  kind: modify
- path: core/agent_runner/prompt_builder.py
  kind: modify
- path: tests/test_self_review_todo_fallback.py
  kind: new
```

## 1. 未收集态文案区分

- [ ] 1.1 core/self_review.py：组装自省 detail 时，read_todo=false 分支为 todo_entries 赋显式未收集陈述（归因 read_todo 关闭），使其不再落入 prompt_builder 的「（近3日窗口内无既有条目）」兜底；核对 maintenance_runs.py 的 None→空串归一不吞掉该显式字符串
- [ ] 1.2 core/agent_runner/prompt_builder.py：{todo_entries} 的 or-fallback 语义收窄为意外空值兜底或改用与未收集态可分辨的文案；{todo_md_content} 的兜底保持现状

## 2. 测试

- [ ] 2.1 tests/test_self_review_todo_fallback.py：覆盖 read_todo=false 输出未收集陈述、read_todo=true 且空窗口输出「近3日窗口内无既有条目」、read_todo=true 且有条目输出带 ID 清单三个场景，并断言前两者文案可分辨