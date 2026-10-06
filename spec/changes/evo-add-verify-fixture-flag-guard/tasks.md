## Deliverables

```yaml
- path: spec/knowledge/domains/test-engineering/fixture-project-governance.md
  kind: modify
- path: agents/planner-plan.md
  kind: modify
- path: core/verify_engine/scenario_static_check.py
  kind: modify
- path: tests/test_fixture_project_governance.py
  kind: modify
```

## 1. 规范固化（文档 + 出题提示词）

- [ ] 1.1 spec/knowledge/domains/test-engineering/fixture-project-governance.md：在「现行规则」节新增 MUST 条目——验证场景注册探针夹具（/tmp 扫描根外临时路径）一律 fixture=True；写明依据 ADR-163（收窄仅在缺省跨项目聚合分支、显式点名查询 ?project= 零改动、打标对场景断言零影响），并注明直写 admin_alerts.json 不经摄取抑制、聚合分支 fixture 标记是唯一降噪面。
- [ ] 1.2 agents/planner-plan.md：验证场景出题规范补一条——场景命令内自注册探针夹具 MUST fixture=True，给正反示例（反例即 add-alert-self-heal-marking 的 fixture=False 形态）。

## 2. 机械守卫（静态扫描，不动 Registry 语义）

- [ ] 2.1 core/verify_engine/scenario_static_check.py：按既有表驱动模式新增一条扫描模式——场景命令出现 add_project( 调用而实参未含 fixture=True 即产出 judge 情报（只情报不拦截，对齐既有 stale_literal_port 同型）；不改 Registry.add_project 缺省值，避免与 ADR-163 Decision「禁按路径/名字推导」冲突。

## 3. 测试

- [ ] 3.1 tests/test_fixture_project_governance.py：覆盖新扫描模式——显式 fixture=False 与缺省不传均命中情报、显式 fixture=True 不命中；领域文档新增 MUST 条目的存在性断言。