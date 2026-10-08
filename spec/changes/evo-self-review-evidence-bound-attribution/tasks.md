## Deliverables

```yaml
- path: agents/self-review.md
  kind: modify
```

## 1. 提示词纪律

- [ ] 1.1 agents/self-review.md：「调查评估」质量标准段（约 :22-24）追加归因证据边界纪律——凡结论涉及根因归因必须逐项对照当日可回收证据（明细档/告警/日志/commit）；证据只覆盖失败形态（如 items 空、fallback_full=true、total=0）时结论只写到形态层、根因写「未定、多假说并存」，MUST NOT 单因确定性叙事、MUST NOT 据此建议针对特定根因的修复方向；证据足以裁决时可给确定性归因并附证据引用；错误归因以新条目更正、不回改历史条目原文

## 2. 链路确认

- [ ] 2.1 确认 core/agent_runner/prompt_builder.py `_build_self_review_prompt` 能装载改后模板（模板缺失 fail-fast 机制不被触发、填充无残留占位符），不做代码改动