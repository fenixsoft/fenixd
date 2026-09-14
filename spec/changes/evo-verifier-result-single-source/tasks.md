# 任务

## Deliverables

```yaml
- path: core/pm_engine/verification.py
  kind: modify
- path: core/pm_engine/engine.py
  kind: modify
- path: tests/test_verdict_contamination.py
  kind: new
- path: .fenix/STATE.md
  kind: reference
```

## 1. 统一裁决读取入口 _read_verdict(spec_name)

- [ ] 1.1 core/pm_engine/verification.py：verify-progress 优先 + 主树共享双校验回退 + unreadable 语义；legacy 与 planner 两路径全部改走入口，删除各自读取分支。

## 2. 主树共享文件写入 role/spec 戳隔离

- [ ] 2.1 core/pm_engine/engine.py：implementer 结果写 verify-progress/<spec>/impl-result.json（对齐既有实践）；主树共享写路径补 role=verifier 与 spec 戳；无 role 的主树共享文件读侧丢弃。

## 3. implementer 残留污染回归测试

- [ ] 3.1 tests/test_verdict_contamination.py：模拟主树共享文件被 implementer 残留 status=success 污染，断言 legacy/planner 两路径均不将其当裁决，unknown-status 走 re-dispatch；重放 add-web-ui 09-06 误判链 0 blocked。

## 4. 成本基线重验

- [ ] 4.1 .fenix/STATE.md：修复后重验 add-web-ui 基线成本，确认无新增空转（judge 重跑上限配合下）。运行时账本，gitignored，声明为 reference 仅审计留痕。
