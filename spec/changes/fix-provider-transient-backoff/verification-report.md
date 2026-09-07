# 验证报告：fix-provider-transient-backoff

> ⚠️ 本报告由框架于 2026-09-07T10:40:03Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。

## 结论：❌ 未通过（Bug Found）

**状态：bug-found — 7/16 场景通过，9 失败，0 错误（4 个真实产品 Bug）**

9 个失败场景全部为 product-bug，聚类为 4 个根因：① task 5.3 前端瞬断治理分组与控件未实现（4 场景）；② task 5.2/5.4 配置键与文档缺失（3 场景）；③ task 5.3 服务端对非法瞬断值未校验返回 200（1 场景）；④ task 4.3 全局指纹熔断未实现（1 场景）。核心退避/降噪/排程重派/标记注入/保留 worktree 逻辑（tasks 1-3, 4.1, 4.2）已通过既有单元测试与 grep 验证，未回归。

| 指标 | 数量 |
| --- | --- |
| 通过 | 7 |
| 失败 | 9 |
| 错误 | 0 |
| 产品 Bug | 4 |
| 本链增量 Token（输入） | 4.66M |
| 本链增量 Token（输出） | 0.08M |


## 真实产品 Bug

### BUG-01（severity=major）· element_visible / text_contains / text_match

- 关联场景：settings-transient-group-visible、settings-transient-edit-save、settings-transient-validation、settings-transient-defaults
- 描述：Settings 系统页「瞬断治理」分组与 5 个配置控件均未实现（task 5.3）。分组标题「瞬断治理」不渲染，transient_backoff_schedule / transient_redispatch_delay_seconds / transient_break_threshold / transient_break_window_seconds / transient_break_cooldown_seconds 全部控件不存在，默认值回显、编辑、校验流程均无法进行
- 根因：SystemPanel.tsx ADMIN_ANNOTATIONS 无 transient 键，全仓库无 system-control-transient 选择器；task 5.3 前端控件未实现
- 证据（场景 settings-transient-group-visible 结构化证据，引用）：
  - failed_assertions: [{"type": "text_contains", "text": "瞬断治理", "expected": "分组标题可见", "actual": "未找到"}, {"type": "element_visible", "selector": "[data-testid='system-control-transient_backoff_schedule']", "expected": "可见", "actual": "Locator 3000ms 超时，元素不存在"}]
  - screenshots: ["/root/fenixd/.fenix/verify-progress/fix-provider-transient-backoff/screenshots/settings-transient-group-visible_assert_fail.png"]
  - first_failed_step: 断言: 分组标题「瞬断治理」未渲染（SystemPanel 源码 ADMIN_ANNOTATIONS 无 transient 键）

### BUG-02（severity=major）· json_path / output_match / exit_code

- 关联场景：config-api-transient-defaults、config-template-transient-keys、docs-transient-config-section
- 描述：瞬断治理配置键在配置模板、GET /api/config 响应与配置文档中全部缺失（task 5.2/5.4）。config.template.yaml 无 5 个 transient 键，/api/config agents 段 json_path 全 null，docs/help/08-config.md 无瞬断治理段
- 根因：task 5.2 未在配置模板与配置读取链路实现 transient 键（仅 runner.py _get_config 代码内默认值兜底），task 5.4 文档未补
- 证据（场景 config-api-transient-defaults 结构化证据，引用）：
  - failed_assertions: [{"type": "json_path", "path": "agents.transient_backoff_schedule", "expected": "30,60,120", "actual": "null（响应中无该键）"}, {"type": "json_path", "path": "agents.transient_break_threshold", "expected": 3, "actual": "null（响应中无该键）"}]
  - screenshots: []
  - first_failed_step: 断言: GET /api/config 200 但 agents 段不含 5 个瞬断键（json_path 均 null）

### BUG-03（severity=major）· status_code

- 关联场景：config-api-invalid-transient
- 描述：POST /api/config 携带非法瞬断配置值（transient_redispatch_delay_seconds=-5）未被服务端拒绝：期望 400，实际返回 200 且接受写入
- 根因：task 5.3 服务端配置校验未实现，非法瞬断值未做范围校验
- 证据（场景 config-api-invalid-transient 结构化证据，引用）：
  - failed_assertions: [{"type": "status_code", "expected": 400, "actual": 200, "note": "非法值 -5 未被服务端拒绝，请求被接受"}]
  - screenshots: []
  - first_failed_step: 断言: POST /api/config 携带 transient_redispatch_delay_seconds=-5 期望 400，实际返回 200

### BUG-04（severity=major）· output_match

- 关联场景：cli-provider-circuit-global-fuse
- 描述：provider_circuit.py 全局错误指纹熔断（transient_break）未实现（task 4.3）。grep 仅命中旧 fuse/cooldown 字段，无 transient_break 全局指纹 10 分钟窗口 ≥3 次触发派发冻结逻辑
- 根因：task 4.3 未实现；provider_circuit.py 仅保留 PROVIDER_CIRCUIT_*/SWITCH_* 旧常量与 provider-fault-fuse 注释
- 证据（场景 cli-provider-circuit-global-fuse 结构化证据，引用）：
  - failed_assertions: [{"type": "output_match", "expected": "transient_break", "actual": "grep 命中 fuse/cooldown 但无 transient_break 实现"}]
  - screenshots: []
  - first_failed_step: 断言: provider_circuit.py 不含 transient_break（task 4.3 未实现）


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| settings-transient-group-visible | Settings 页面 SystemPanel 显示「瞬断治理」分组：包含 5 个配置控件（transient_backoff_schedule / transient_redispatch_delay_seconds / transient_break_threshold / transient_break_window_seconds / transient_break_cooldown_seconds），均有 label 注解与默认值回显 (spec: transient-controls-ui, task 5.3, SystemPanel.tsx) | failed（已修正） | 6/10 | product-bug |
| config-api-transient-defaults | GET /api/config 返回 agents 段含 5 个瞬断治理键及缺省值（transient_backoff_schedule=30,60,120 / redispatch_delay=600 / break_threshold=3 / break_window=600 / break_cooldown=600），(spec: transient-controls-ui, design D6) | failed（已修正） | 5/6 | product-bug |
| config-template-transient-keys | 配置模板 .fenix/config.template.yaml 包含 5 个瞬断治理键及缺省值注释（transient_backoff_schedule / transient_redispatch_delay_seconds / transient_break_threshold / transient_break_window_seconds / transient_break_cooldown_seconds），(spec: transient-controls-ui, task 5.2) | failed（已修正） | 6/6 | product-bug |
| docs-transient-config-section | 配置文档 docs/help/08-config.md 补充瞬断治理段说明：5 个键语义与缺省值 (spec: transient-controls-ui, task 5.4) | failed（已修正） | 2/2 | product-bug |
| cli-unit-tests-denoise | 运行 tests/test_transient_backoff.py 中的错误归因降噪测试：诊断行过滤、全噪音回退 Exit code、双通道瞬断判定正反例均通过 (spec: error-attribution-denoise, tasks 1.1-1.3) | pass | 0/1 | - |
| cli-unit-tests-backoff-retry | 运行 tests/test_transient_backoff.py 中的原地退避与 resume 测试：预算限制、sub run_id 生成、resume 死 session 兜底、非瞬断不进入重试循环均通过 (spec: provider-transient-backoff, tasks 2.1-2.4) | pass | 0/1 | - |
| cli-unit-tests-full-suite | tests/test_transient_backoff.py 全量测试通过（含降噪/判定/退避/调度全场景），覆盖 tasks 1.3, 2.4, 4.4 (spec: error-attribution-denoise / provider-transient-backoff / transient-dispatch-gating) | pass | 0/1 | - |
| cli-runner-marker-injection | runner.py 瞬断终态 error 头部注入 [provider-transient] 结构化标记：grep runner.py 确认标记写入代码存在且唯一写入点 (spec: transient-dispatch-gating, task 4.1) | pass | 0/2 | - |
| cli-worktree-keep-for-reuse | worktree_manager.py keep_for_reuse 泛化到全 agent_type：验证 transient 终态失败时走 keep_for_reuse 而非 cleanup(success=False) (spec: provider-transient-backoff, task 3.2) | pass | 0/2 | - |
| cli-dispatch-schedule-recovery | dispatch.py _schedule_transient_recovery 实现排程等待重派：验证 transient 终态触发定时器而非立即重入队 (spec: transient-dispatch-gating, task 4.2) | pass | 0/2 | - |
| cli-provider-circuit-global-fuse | provider_circuit.py 全局错误指纹熔断实现：验证 10 分钟窗口内同指纹 ≥3 次触发派发冻结 + major 告警 (spec: transient-dispatch-gating, task 4.3) | failed（已修正） | 1/2 | product-bug |
| cli-regression-test-suite | 全量既有测试套件零回归：tests/test_provider_circuit / test_provider_failover / test_runner_provider 等既有测试全部通过 (spec: task 6.3) | pass | 0/1 | - |
| settings-transient-edit-save | 编辑瞬断治理配置并保存：修改 transient_break_threshold 为 5，点击保存，出现保存成功提示 (spec: transient-controls-ui, task 5.3) | failed（已修正） | - | product-bug |
| settings-transient-validation | 非法输入拦截：transient_redispatch_delay_seconds 填 -5 后点保存，保存被拦截并展示校验错误提示，配置文件不被写入 (spec: transient-controls-ui, task 5.3) | failed（已修正） | - | product-bug |
| settings-transient-defaults | 瞬断治理配置默认值验证：3 个 InputNumber 控件回显缺省值（break_threshold=3 / break_window=600 / break_cooldown=600），(spec: transient-controls-ui, design D6) | failed（已修正） | 3/4 | product-bug |
| config-api-invalid-transient | POST /api/config 带非法瞬断配置值（transient_redispatch_delay_seconds=-5）被服务端拒绝返回 400，配置文件不被写入 (spec: transient-controls-ui, design D6) | failed（已修正） | 1/1 | product-bug |


## 断言级豁免清单

以下失败断言被归类为非产品缺陷（不记产品 Bug），逐条列出供人工复核豁免是否掩盖真实缺陷（场景级一句话归因不足以复核）。

无非 product-bug 的被豁免失败断言。

## 本轮场景集变更

场景集与持久化集一致，无变更。

