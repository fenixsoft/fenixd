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

- [x] 1.1 core/verify_contract.py：VerifyContract（:230-240）增可选 evidence_dir 字段（缺省 .fenix/verify-evidence/<spec>/），加载/校验/回退同既有字段形态；落点语义=消费项目主树（绝对路径 = 项目根/.fenix/verify-evidence/<spec>/，与 worktree 生命周期解耦）；报告合成处仅引用相对路径（以主树根为基准），core/verify_report.py:961 单文件入库 pathspec 不改。
- [x] 1.2 core/verify_contract_template.yaml：模板补 evidence_dir 注释化声明与示例。
- [x] 1.3 core/agent_runner/prompt_builder.py：在落盘契约段（:910-943 quality-gates 同族位置）补「验证证据统一落主树根 .fenix/verify-evidence/<spec>/（绝对路径；或契约 evidence_dir）」指引，写明禁止落 worktree 相对路径（worktree 销毁即失联）；若验证链提示词另有构建点，在同型位置补齐。

## 2. untracked 散件盘点信号

- [x] 2.1 core/worktree_manager/stray_wip.py：_sweep_locked（:148-165）增 entry 级 untracked 口径（git status --porcelain），豁免 .fenix/ negation 放行项与已 ignore 路径；插桩须覆盖 tracked 空集早退路径（:163-165，纯 untracked 场景不得提前返回 clean）；超阈值（admin.maintree_untracked_stray_threshold，缺省 5）且跨宽限周期（复用 admin.maintree_stray_wip_grace_minutes）滞留发一次性新信号 maintree_untracked_stray_stale（SIGNAL_TYPE 常量 :35 旁新增）；untracked 指纹=路径排序集+逐文件内容 sha256（不可复用 git diff HEAD 形态——untracked 不进 diff，会退化为纯路径集哈希），指纹记账/复位复用既有形态（:217-251）；tracked 口径现行行为逐字节不变，全程零触碰。
- [x] 2.2 core/admin_monitor.py：新信号 maintree_untracked_stray_stale 两处登记——severity 映射（:324 处，值 info）、recommended_action 文案（:404，复制 maintree_stray_wip_stale「只告警不处置」模板）；MUST NOT 收录 STORED_SIGNAL_TYPES（:469-472，摄取循环 admin_monitor.py:2189-2192 无 severity 过滤、收录即唤起人工，与 info 留痕语义相抵），可见性由 AdminStore 留痕与 Dashboard 承载。

## 3. 测试

- [x] 3.1 tests/test_verify_evidence_placement.py（新建）：evidence_dir 缺省/覆盖/非法回退；模板解析含新字段；untracked 信号 entry 级判定（混合目录 tracked 条目不报）、tracked 空集+纯 untracked 场景信号仍触发（:163-165 早退插桩回归点）、.fenix/ 放行项与 ignored 路径豁免、同指纹一次性（内容演化不重告）、指纹消失复位、阈值/宽限配置解析、admin_monitor 断言（severity=info 与文案两表登记在册、STORED_SIGNAL_TYPES 不含 maintree_untracked_stray_stale）。
- [x] 3.2 运行既有 tests/test_maintree_stray_wip_sweep.py 与 verify_contract 相关用例确认零回退。