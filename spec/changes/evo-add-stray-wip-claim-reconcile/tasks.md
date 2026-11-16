## Deliverables

```yaml
- path: core/admin_monitor.py
  kind: modify
- path: core/worktree_manager/stray_wip.py
  kind: modify
- path: core/admin_store.py
  kind: modify
- path: tests/test_stray_wip_claim_reconcile.py
  kind: new
- path: tests/test_maintree_stray_wip_sweep.py
  kind: modify
```

## 1. 升级条目挂指纹清单（core/admin_monitor.py）

- [ ] 1.1 core/admin_monitor.py：maintree_stray_wip_stale 升级条目生成处（escalate 分支）把指纹文件集路径列表写入条目结构化字段，与 stray_wip 指纹归一结果同源

## 2. 认领探测与自动核销（core/worktree_manager/stray_wip.py + core/admin_store.py）

- [ ] 2.1 core/worktree_manager/stray_wip.py：周期盘点挂认领探测——对每个未核销升级条目取指纹文件集，判定「main 基线后新提交覆盖全部文件且工作区该集合 clean」，命中核销、未命中/部分入库/仍脏保守保留
- [ ] 2.2 core/admin_store.py：核销写回 handled=True/handled_by="auto-resolve-claim"，resolve_note 含认领 commit SHA 与「人工已以提交认领主树直改形态，请确认是否仍需建立 worktree 车道」；照 auto_resolve_by_type_fingerprint 白名单形态只挂 maintree_stray_wip_stale 族
- [ ] 2.3 core/admin_store.py：存量无结构化字段条目按 evidence 文本回提取文件集参与探测，回提取失败保守跳过

## 3. 测试（新建 tests/test_stray_wip_claim_reconcile.py）

- [ ] 3.1 tests/test_stray_wip_claim_reconcile.py：认领核销场景——指纹 5 文件被基线后单提交全覆盖+工作区 clean，断言核销写回、resolve_note 含 commit SHA 与转向话术
- [ ] 3.2 tests/test_stray_wip_claim_reconcile.py：保守反例——部分入库/工作区仍脏/回提取失败三形态，断言逐位保留零核销；升级节奏字段不变
- [ ] 3.3 tests/test_maintree_stray_wip_sweep.py：既有 sweep 零回归——处置侧零触碰+升级节奏、指纹归一、registry 复位行为不变断言（认领探测为纯消费端增量）