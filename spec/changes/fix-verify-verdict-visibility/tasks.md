## Deliverables

```yaml
- path: core/dashboard/data.py
  kind: modify
- path: core/dashboard/static/src/pages/projects/detail.tsx
  kind: modify
- path: agents/verifier.md
  kind: modify
- path: tests/test_verdict_visibility.py
  kind: new
```

## 1. 后端 filtered_failures 结构

- [x] 1.1 data.py 新增 `parse_filtered_failures(project_root, spec_name)`：
  从 report.json scenarios 提取 status ∈ (fail, failed, error) 且
  classification ∈ 非 product-bug 分类的场景，每项返回
  {scenario_id, classification, evidence_summary, screenshots(basename 归一化),
  status_corrected}；evidence_summary 取 evidence.first_failed_step，
  缺省回退 failed_assertions 首项 actual，再缺省空串；status="fail"/"failed"
  与 "error" 的非 product-bug 分类均收录（与 parse_bugs 的收录面互补，二者互斥不双计）
- [x] 1.2 `spec_detail` 响应新增 `"filtered_failures"` 键调用上述函数；
  旧格式 report.json（无 classification 字段）不产生条目

## 2. 前端 Bug 列表摘要渲染

- [x] 2.1 detail.tsx Bug 列表页签：bugs 为空且 filtered_failures 非空时，
  在「无遗留 Bug」空态下方渲染被过滤失败场景摘要列表（场景 id、分类标签
  「测试缺陷/环境问题/偶发」、evidence_summary 文本、截图缩略图复用
  /screenshots/ 路由点击放大）；bugs 非空时摘要折叠为次级区块
- [x] 2.2 filtered_failures 为空时渲染行为与现状完全一致（「无遗留 Bug」，
  无新区块）

## 3. verifier 出题选择器实测规则

- [x] 3.1 agents/verifier.md 在场景执行步骤附近新增出题约束段（MUST 级）：
  断言用 CSS 选择器必须先经 playwright 在被测应用实测 DOM 确认命中，
  不得凭训练知识引用框架类名；附 antd v6 反例（Collapse 内容类实测为
  .ant-collapse-body/.ant-collapse-panel，.ant-collapse-content 已不存在）

## 4. 测试与验证

- [x] 4.1 新建 tests/test_verdict_visibility.py：覆盖 filtered_failures 提取
  （test-defect 失败收录、product-bug 不收录、旧格式无 classification 不收录、
  evidence 多级回退、截图 basename 归一化）、spec_detail 响应含新键、
  agents/verifier.md 含实测规则文本（MUST 措辞与反例）；测试隔离用户级配置
  （对齐 isolated_user_config fixture 惯例）
- [x] 4.2 全量测试通过（pytest tests/ -x），无回归
