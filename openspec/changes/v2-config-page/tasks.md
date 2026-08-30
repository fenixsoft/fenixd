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

- [x] 3.1 `git add core/dashboard/static/v2/pages/config.json tests/v2/ && git commit`(信息:`v2-config: 配置页(5 页签+链编辑器+三级回退+编辑豁免)`)

## 验证修复（第 2 轮失败）

- [x] 阅读 `openspec/changes/v2-config-page/verification-report.md`，定位「真实产品 Bug」并修复
- [x] 修复后重跑验证确认通过

## 验证修复（第 3 轮失败 — Administrator 重置后修复指引，2026-08-29）

最新一轮验证（.fenix/verify-progress/v2-config-page/.fenix-run-result.json，2026-08-29T17:11Z）16 场景 3 通过/7 预警/6 失败。注意 `verification-report.md` 仍是第 1 轮陈旧合成内容（config.json 缺失时代），本轮以该 run-result 的 bug 清单为准，修复以下 4 项真实产品 Bug + 1 项测试隔离问题：

- [x] BUG-A(major)：Agent 模型分配页签链编辑器「新增」按钮以 hidden 渲染（dark-Combo-addBtn），点击超时 → 检查 combo/input-array 的 addable/sortable 配置与空数组隐藏逻辑（影响 config-incomplete-chain-blocked、config-chain-sortable-reorder）
- [x] BUG-B(major)：LLM Provider 页签 provider 卡片「删除」按钮缺失（AMIS 渲染为图标/下拉操作而非文本按钮）→ 修正选择器或补齐可点击的删除控件（影响 config-delete-provider-row）
- [x] BUG-C(major)：provider 卡片 ENV_KEY 输入框被 `<span>值</span>` 所在 dark-Form-col 子树拦截 pointer events → 修复 combo 嵌套栅格/列宽布局遮挡（影响 config-llm-env-kv-add-remove）
- [x] BUG-D(major)：并行度三级回退失效：清空后保存持久化为空字符串，重载回显 "" 而非回退快照值 5 → 检查 numOr(adapters.js:313-322) 与 buildConfigPayload 对空值的透传（影响 config-number-fallback-snapshot）
- [x] BUG-E(minor)：config-parallel-persist-reload 期望值 7 被先行场景保存的 8 污染 → 将用例改为自包含保存-重载闭环（测试隔离修正）

修复完成后重跑验证确认通过。
