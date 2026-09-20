# Tasks: fix-cr-robustness

## Deliverables

```yaml
- path: core/agent_runner/liveness.py
  kind: modify
```

## 1. 修复审查问题

- [ ] 1.1 float() 直接转换运行超时可能抛 TypeError — core/agent_runner/liveness.py:996
