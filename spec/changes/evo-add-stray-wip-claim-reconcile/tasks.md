## Deliverables

```yaml
- path: core/worktree_manager/stray_wip.py
  kind: modify
- path: core/admin_store.py
  kind: modify
- path: tests/test_stray_wip_claim_reconcile.py
  kind: new
- path: tests/test_maintree_stray_wip_sweep.py
  kind: modify
```

## 1. 升级条目挂指纹清单（core/worktree_manager/stray_wip.py）

- [x] 1.1 core/worktree_manager/stray_wip.py：maintree_stray_wip_stale 告警落库记录构造处把指纹文件集路径列表写入记录结构化字段（与 evidence「文件清单(N):」段同源），核销探测只消费结构化字段或回提取结果

## 2. 认领探测与自动核销（core/worktree_manager/stray_wip.py + core/admin_store.py）

- [x] 2.1 core/worktree_manager/stray_wip.py：周期盘点挂认领探测——插桩 MUST 在盘点轮空集早退之前（evo-whitelist-tracked-patrol 1.1 先例：tracked 零改动直接返回 clean，早退不得吞掉本判定）；对每个未核销（kind=SIGNAL）升级条目取指纹文件集，在 project_root 内 `git -C` 判定「基线后存在覆盖全部文件的提交（≥1，数不限）且工作区该集合 clean」，命中核销、未命中/部分入库/仍脏保守保留
- [x] 2.2 core/admin_store.py：核销写回 handled=True/handled_by="auto-resolve-claim"，resolve_note 含认领覆盖提交 SHA（多波覆盖时取最近覆盖提交）与「人工已以提交认领主树直改形态，请确认是否仍需建立 worktree 车道」；照 auto_resolve_by_type_fingerprint 白名单形态只挂 maintree_stray_wip_stale 族
- [x] 2.3 core/admin_store.py：存量无结构化字段条目按 evidence「文件清单(N):」段回提取文件集参与探测（复用既有段级解析单源口径，禁新写路径正则双处解析），回提取失败保守跳过；只面向 kind=SIGNAL 记录
- [ ] 2.4 core/worktree_manager/stray_wip.py：复发计数台账检索（`_prior_stray_rounds`）跳过 handled_by="auto-resolve-claim" 的记录——自动核销非人工处置轮，不得计入「已 N 度处置」复发口径

## 3. 测试（新建 tests/test_stray_wip_claim_reconcile.py）

- [ ] 3.1 tests/test_stray_wip_claim_reconcile.py：认领核销场景——指纹 N 文件被基线后提交全覆盖（含单波与多波两形态）+工作区 clean（含 tracked 空集轮探测仍执行的插桩断言），断言核销写回、resolve_note 含覆盖提交 SHA 与转向话术
- [ ] 3.2 tests/test_stray_wip_claim_reconcile.py：保守反例——部分入库/工作区仍脏/回提取失败三形态，断言逐位保留零核销；升级节奏字段不变
- [ ] 3.3 tests/test_maintree_stray_wip_sweep.py：既有 sweep 零回归——处置侧零触碰+升级节奏、指纹归一、registry 复位行为不变断言（认领探测为纯消费端增量）
- [ ] 3.4 tests/test_stray_wip_claim_reconcile.py：复发计数不计自动核销——handled_by="auto-resolve-claim" 记录不使同文件后续告警误带「已 N 度处置」复发口径