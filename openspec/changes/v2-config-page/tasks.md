# Tasks: v2-config-page

实现依据(实施 agent 必读,代码以计划为准):
- 实施计划 docs/superpowers/plans/2026-08-29-amis-dashboard-v2.md「Task 10」节(config.json 完整结构含链编辑器骨架、requestAdaptor 合并、测试代码)
- 行为权威:docs/superpowers/specs/2026-08-29-amis-dashboard-v2-behavior.md §6(配置结构/链规则/回退)、§0(豁免)

## 1. 测试先行

- [x] 1.1 写 tests/v2/config.spec.js(加载回显→修改并行度→保存→toast→重载回显);跑确认 FAIL

## 2. 页面实现

- [x] 2.1 实现 pages/config.json:config-loader service(写 __configSnapshot)+ config-form 5 页签(LLM combo/env KV combo、链 input-array sortable+validateChain、并行度 4 input-number、审批 radios、主题只读 tpl);requestAdaptor 调 buildConfigPayload;不挂任何 sse 监听
- [x] 2.2 config.spec.js PASS;链校验与编辑豁免抽查

## 3. 提交

- [x] 3.1 `git add core/dashboard/static/v2/pages/config.json tests/v2/ && git commit`(信息:`v2-config: 配置页(5 页签+链编辑器+三级回退+编辑豁免)`)## 验证修复（第 1 轮失败）

- [x] 阅读 `openspec/changes/v2-config-page/verification-report.md`，定位「真实产品 Bug」并修复
- [x] 修复后重跑验证确认通过（本地 VerifyEngine 重放 17/17 场景全通过，0 失败 0 警告）
