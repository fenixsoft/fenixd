# 验证报告：add-planner-efficiency

> 本报告由 Fenix Planner Agent 于 2026-09-05 生成，基于对验证报告的详细分析。

## 结论：❌ 未通过（Bug Found）

**状态：bug-found — 7/12 场景通过，5 失败，0 错误（1 个真实产品 Bug）**

验证发现 1 个产品缺陷：设置页「Planner 生成节流」开关的配置持久化**读回**链路缺失——写盘正常但 `GET /api/config` 读不回来。另有 3 个场景因同根因测试选择器缺陷（antd v5 双汉字按钮自动空格）在保存步骤即中断（非产品 Bug），1 个场景为详情页时间轴异步渲染时序 flaky。

| 指标 | 数量 |
| --- | --- |
| 通过 | 7 |
| 失败 | 5 |
| 错误 | 0 |
| 产品 Bug | 1 |
| 测试缺陷（同根因聚合） | 1 |
| flaky | 1 |

## 通过场景（7）

`pln-throttle-tab-default-off`、`pln-throttle-annotation-three-points`、`route-map-indexed-settings-entry-real`、`route-map-gen-cli-outputs-index`、`latency-events-channel-structured`、`pln-throttle-switch-reveals-limit-input`、`pln-throttle-switch-off-hides-input`

- 节流开关默认关、注解三点覆盖、开关开→上限输入框出现（默认值 1）、开关关→输入框从 DOM 移除等核心交互全部通过。
- 事件通道（/api/events）与 prompt 供给通道（/api/prompts）连通性验证通过。

## 真实产品 Bug

### BUG-01（severity=major）· text_contains

- **关联场景**：pln-throttle-config-readback-persisted
- **描述**：配置持久化读回缺陷：`write_config` 已把 `verify.planner_max_concurrent=2` 合并写盘（配置文件中真实存在），但 `GET /api/config` 返回的 verify 段始终不含 `planner_max_concurrent` 键——保存后无法读回已持久化的节流配置，前端回显与 spec「开关持久化」需求失效。
- **根因**：`core/dashboard/data.py` 中 `read_config()` 的 verify 段提取分支仅处理 `static_scope` 与 `deps_mode`（data.py:2914-2917），未将新增的 `planner_max_concurrent` 纳入读回白名单；写路径（`write_config` data.py:3127-3129）与读路径白名单不对称——写进去却读不出来。
- **证据**：
  - failed_assertions:
    - `text_contains` expected=`planner_max_concurrent` → actual=GET /api/config verify 段不含该键
    - `text_contains` expected=`"planner_max_concurrent": 2` → actual=GET /api/config verify 段不含该键值
  - screenshots: `screenshots/pln-throttle-config-readback-persisted_assert_fail.png`
  - first_failed_step: 断言阶段：GET /api/config 返回的 verify 段缺少 planner_max_concurrent 键
- **逐断言归因**：2 条失败断言均为 product-bug（同一根因，读回白名单遗漏）。

## 测试缺陷（非产品 Bug）

### TEST-DEFECT-01（severity=minor）· click（同根因聚合 3 场景）

- **关联场景**：pln-throttle-save-persists、pln-throttle-empty-limit-validated、pln-throttle-restore-off
- **描述**：设置页「保存」按钮选择器 `button.ant-btn-primary:has-text("保存")` 无法命中实际 DOM。antd v5 Button 对两汉字按钮自动插入空格（autoInsertSpace），实际渲染文本为「保 存」，`has-text("保存")` 子串匹配失败，导致 5s 定位超时、步骤中断。产品按钮真实存在于 `ParallelSettingsPanel.tsx:148-152` 且可点击，**非产品缺陷**。这 3 个场景因此在保存动作处中断，后续断言全部未执行。
- **根因**：antd v5 CJK 双汉字按钮自动插空格；修复应改用 `has-text("保 存")` 或为保存按钮增加 data-testid 定位。
- **证据**：first_failed_step 均为「点击保存按钮 Locator 5s 超时（element_not_found_or_not_actionable）」，三个场景失败模式一致。
- **逐断言归因**：各场景 1 条失败步骤（click 保存）均归类 test-defect，证据为 antd CJK 自动空格导致 has-text 不命中。

## flaky（非产品 Bug）

### FLAKY-01（severity=minor）· element_visible

- **关联场景**：latency-run-record-display-normal
- **描述**：spec 详情页 run 时间轴 `.ant-timeline` 可见性断言 3000ms 超时。产品渲染正确：同场景后续 `text_contains「查看运行记录」` 断言通过、`no_console_error` 无错误，证明时间轴最终正常渲染。失败根因是异步数据加载时序竞态——detail API 慢响应时，固定等待预算（1500ms+3000ms）未覆盖渲染窗口。
- **根因**：时间轴依赖 `detail.timeline` 异步就绪（detail.tsx:658-660），属间歇性时序问题。
- **证据**：screenshots `screenshots/latency-run-record-display-normal_assert_fail.png`。
- **逐断言归因**：1 条失败断言（element_visible .ant-timeline）归类 flaky，证据为同场景其他断言通过且产品可正确渲染。

## 场景结果

| 场景 | 状态 | 分类 | 失败断言 |
| --- | --- | --- | --- |
| pln-throttle-tab-default-off | pass | - | 0 |
| pln-throttle-annotation-three-points | pass | - | 0 |
| route-map-indexed-settings-entry-real | pass | - | 0 |
| route-map-gen-cli-outputs-index | pass | - | 0 |
| latency-events-channel-structured | pass | - | 0 |
| pln-throttle-switch-reveals-limit-input | pass | - | 0 |
| pln-throttle-switch-off-hides-input | pass | - | 0 |
| latency-run-record-display-normal | fail | flaky | 1 |
| pln-throttle-save-persists | fail | test-defect | 0（步骤失败） |
| pln-throttle-empty-limit-validated | fail | test-defect | 0（步骤失败） |
| pln-throttle-config-readback-persisted | fail | product-bug | 2 |
| pln-throttle-restore-off | fail | test-defect | 0（步骤失败） |

## 修复建议

1. **（必须）pln-throttle-config-readback-persisted**：在 `read_config()`（core/dashboard/data.py:2914-2917）verify 段提取分支补充 `planner_max_concurrent` 非负整数回读，与写路径白名单保持一致。
2. **（建议）保存按钮选择器**：为设置页保存按钮补充 `data-testid`，或改用 `has-text("保 存")` 匹配 antd 渲染文本，避免后续验证场景在保存步骤中断。
3. **（可选）flaky 加固**：详情页 timeline 断言改为显式轮询等待（如 `waitFor({ state: 'visible', timeout: 10000 })`）或断言「暂无运行时间轴」空态作为二选一结果。

## 本轮场景集变更

当前稳定场景集共 12 个（第 1 轮）。

- 首轮写入 12 个场景

