## Deliverables

```yaml
- path: core/verify_contract.py
  kind: modify
- path: core/agent_runner/prompt_builder.py
  kind: modify
- path: core/dashboard/server.py
  kind: modify
- path: core/dashboard/static/src/pages/settings/index.tsx
  kind: modify
- path: .fenix/verify.yaml
  kind: reference
- path: tests/test_verify_profile_config.py
  kind: new
```

## 1. schema 与注入

- [ ] 1.1 verify_contract.py：VerifyContract 支持 profile 条目列表解析（id/agents/text），schema 校验（id 唯一、agents 取值合法），无 profile 键向后兼容
- [ ] 1.2 prompt_builder：新增档案读取与注入 helper（agents 过滤、单标题段「项目验证档案（用户配置）」、无命中零注入），接入 planner-plan / planner-judge / verifier / fast-track 四个分支

## 2. 死知识清理与迁移

- [ ] 2.1 删除 planner-plan 的 AMIS 选择器大全段；planner-judge `.dark-Card` 示例与 interaction_contract_section `dark-Card--link` 示例改为 data-testid 风格通用示例
- [ ] 2.2 verifier Step 3 被管产品面板清单（Quick Links/Stock/Notes/Calculator/Email）替换为通用表述，保留「交互必须有可见结果否则 BLOCKING BUG」意图
- [ ] 2.3 云端 COS e2e、壳路由 href、seed 键格式三段迁移为 fenixd 自身 `.fenix/verify.yaml` profile 条目（按原适用 agent 标注）

## 3. Dashboard 验证页签

- [ ] 3.1 server.py：profile 条目 GET/PUT 端点（读/整写 verify.yaml，schema 校验失败返回明确错误）
- [ ] 3.2 settings/index.tsx 验证页签新增「项目验证档案」编辑区（条目列表：id 输入 / agents 多选 / text TextArea，增删改保存）
- [ ] 3.3 v3 dist 重建并提交（dist 为入库产物）

## 4. 测试

- [ ] 4.1 tests/test_verify_profile_config.py：覆盖 spec 全部 Scenario（向后兼容、按 agent 过滤注入、无档案零注入、死关键词断言、迁移条目存在性、端点读写）
- [ ] 4.2 既有 prompt/verify 契约测试回归全绿
