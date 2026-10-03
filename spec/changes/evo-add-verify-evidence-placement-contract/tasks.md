## Deliverables

```yaml
- path: core/verify_contract.py
  kind: modify
- path: core/verify_contract_template.yaml
  kind: modify
- path: core/agent_runner/prompt_builder.py
  kind: modify
- path: core/worktree_manager/stray_wip.py
  kind: modify
- path: core/admin_monitor.py
  kind: modify
- path: tests/test_verify_evidence_placement.py
  kind: new
```

## 1. 证据落位契约

- [ ] 1.1 core/verify_contract.py：VerifyContract（:230-240）增可选 evidence_dir 字段（缺省 .fenix/verify-evidence/<spec>/），加载/校验/回退同既有字段形态；报告合成处仅引用相对路径，core/verify_report.py:961 单文件入库 pathspec 不改。
- [ ] 1.2 core/verify_contract_template.yaml：模板补 evidence_dir 注释化声明与示例。
- [ ] 1.3 core/agent_runner/prompt_builder.py：在落盘契约段（:910-943 quality-gates 同族位置）补「验证证据统一落 .fenix/verify-evidence/<spec>/（或契约 evidence_dir）」指引；若验证链提示词另有构建点，在同型位置补齐。

## 2. untracked 散件盘点信号

- [ ] 2.1 core/worktree_manager/stray_wip.py：_sweep_locked（:148-165）增 entry 级 untracked 口径（git status --porcelain），豁免 .fenix/ negation 放行项与已 ignore 路径；超阈值且跨宽限周期滞留发一次性新信号（SIGNAL_TYPE 常量 :35 旁新增），指纹记账/复位复用既有形态（:217-251），全程零触碰。
- [ ] 2.2 core/admin_monitor.py：新信号三处登记——severity 映射（:324）、recommended_action 文案（:404，复制 maintree_stray_wip_stale「只告警不处置」模板）、已知信号类型清单（:469-472）。

## 3. 测试

- [ ] 3.1 tests/test_verify_evidence_placement.py（新建）：evidence_dir 缺省/覆盖/非法回退；模板解析含新字段；untracked 信号 entry 级判定（混合目录 tracked 条目不报）、.fenix/ 放行项与 ignored 路径豁免、同指纹一次性、指纹消失复位、admin_monitor 三处登记断言。
- [ ] 3.2 运行既有 tests/test_maintree_stray_wip_sweep.py 与 verify_contract 相关用例确认零回退。