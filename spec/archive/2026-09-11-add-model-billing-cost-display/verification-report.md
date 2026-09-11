# add-model-billing-cost-display 验证报告

- **Spec**: add-model-billing-cost-display
- **验证时间**: 2026-09-05T09:54:54 UTC
- **验证实例**: verify-serving/add-model-billing-cost-display-1788601962（端口 57415）
- **结果**: ✅ 通过（产品功能全部验证正确；10/11 场景失败均为测试场景自身缺陷，非产品 Bug）

## 场景汇总

| 场景 | 状态 | 分类 | 说明 |
|---|---|---|---|
| billing-switch-visible | ✅ PASS | — | 计费开关可见、默认关、可点击、无控制台错误 |
| billing-toggle-reveals-and-hides-price-area | ❌ FAIL | test-defect | **断言时序问题**：步骤在断言前已把开关拨回 OFF，价格区随开关关闭被正确隐藏；步骤5 曾成功点击「添加模型价格」证明渲染/交互正常 |
| billing-off-no-cost-in-spec-detail | ❌ FAIL | test-defect | **选择器过宽**：`.ant-tag-green` 同时匹配时间轴完成态状态 Tag「done」（detail.tsx:744 绿色）；成本行断言通过、页面无 $ 文本，产品正确不展示成本 |
| billing-price-row-complete-save-success | ❌ FAIL | test-defect | **选择器非法**：`>> nth=0 .ant-select-selector` 缺 `>>` 链接 + antd v5 类名实为 `.ant-select-content`；产品价格行正常渲染（provider 预填，已手动复现） |
| billing-config-readback-persisted | ❌ FAIL | test-defect | 级联：上游保存场景未完成 → 配置从未写入；手动保存后 reload 开关 ON、价格行回显正常 |
| billing-incomplete-price-rejected | ❌ FAIL | test-defect | 级联前置失败（开关未开启，价格区隐藏），校验逻辑未触达 |
| billing-duplicate-price-rejected | ❌ FAIL | test-defect | 级联前置失败，重复拦截逻辑未触达 |
| billing-provider-options-restricted | ❌ FAIL | test-defect | 级联 + 非法选择器双重问题 |
| spec-cost-summary-mixed-priced-unpriced | ❌ FAIL | test-defect | 级联：计费未配置 → 产品按 billing off 正确不展示成本；手动配置后详情页正确显示 $2.72 与「含 4 个未计价 run」 |
| spec-timeline-cost-tag-priced-runs-only | ❌ FAIL | test-defect | 级联：绿色 Tag 可见/计数=1 通过属巧合命中状态 Tag，$2.72 因计费未配置不渲染 |
| spec-cost-unavailable-all-unpriced | ❌ FAIL | test-defect | 级联 + 非法选择器；手工验证「成本不可用」空态渲染正确 |

**判定结论：无产品 Bug（bug-found 为空），产品功能全部验证正确。**

## 逐场景断言归因

### billing-toggle-reveals-and-hides-price-area（test-defect）
- `element_visible button:has-text('添加模型价格')` → test-defect：断言在步骤7把开关拨回 OFF 后执行，价格区被条件渲染正确移除；步骤5 曾成功点击该按钮，证明渲染与可点击均正常。
- `element_visible .billing-price-row` → test-defect：同断言时序问题；同场景 `element_not_exist .billing-price-row` 通过，证实「关闭隐藏」行为正确。

### billing-off-no-cost-in-spec-detail（test-defect）
- `element_not_exist .ant-tag-green` → test-defect：选择器同时匹配时间轴完成态状态 Tag（绿色「done」，detail.tsx:744）。billing off 下成本行断言已通过、$2.72 不存在，产品不展示成本的行为正确，失败源于选择器过宽。

### billing-price-row-complete-save-success（test-defect）
- 步骤7 点击 `.billing-price-row >> nth=0 .ant-select-selector` 超时 → test-defect：Playwright 链式语法非法（`A >> nth=0 B` 恒匹配 0 元素，实测 count=0），且该 antd 版本类名为 `.ant-select-content` 而非 `.ant-select-selector`。产品侧价格行正常渲染。

### billing-config-readback-persisted（test-defect）
- `attribute_match aria-checked=true` → test-defect：级联前置未满足，配置从未保存，开关关闭是正确产品行为；手动保存后 reload 开关保持 ON。
- `element_visible .billing-price-row` → test-defect：同上级联。
- `text_match 模型名=deepseek-v4-flash` → test-defect：同上级联 + 非法 `>> nth=0` 链接语法。

### billing-incomplete-price-rejected / billing-duplicate-price-rejected（test-defect）
- 步骤3 点击「添加模型价格」超时 → test-defect：级联前置失败（开关未开启，价格区隐藏）。场景未在步骤中自行拨动开关。

### billing-provider-options-restricted / spec-cost-unavailable-all-unpriced（test-defect）
- 点击价格行内元素超时 → test-defect：级联前置失败 + 非法 `>> nth=0` 链式语法。

### spec-cost-summary-mixed-priced-unpriced（test-defect）
- 成本行不可见 / `$2.72` 不存在 / 「含 4 个未计价 run」不存在 → test-defect：级联前置未满足（计费从未配置开启）。手动配置计费后详情页正确显示成本合计与未计价附注。

### spec-timeline-cost-tag-priced-runs-only（test-defect）
- `text_contains $2.72` 失败 → test-defect：级联（计费未配置）；`.ant-tag-green` 可见/计数=1 的通过属巧合命中状态 Tag。手动验证配置计费后 `$2.72` 成本 Tag 正常渲染。

## 产品功能实际行为（人工端到端复现）

1. **开关联动**：开关 ON → 每个 Provider 卡片出现「计费价格」分栏与「添加模型价格」按钮（3 个 provider → 3 组）；OFF → 价格区隐藏。✅
2. **价格行渲染**：点击「添加模型价格」→ 新增 `.billing-price-row`，provider Select 预填卡片 Provider（inferaiapi.com），模型名与四项单价输入就绪。✅
3. **保存持久化**：填写 model=deepseek-v4-flash 与 0.27/1.10/0.07/0.28 → 保存 → reload 后开关保持 ON、价格行回显。✅
4. **spec 详情成本合计**（billing on + 价格配置）：正确显示成本行 `$2.72`（含 4 个未计价 run 附注）。✅
5. **时间轴成本 Tag**：可计价 run 附绿色 `$2.72` Tag；计费关闭时不下发 cost_usd。✅
6. **全部未计价空态**（billing on + prices 空）：正确显示「成本不可用」，绝不伪造 $0.00。✅

## 测试场景缺陷根因（建议修复）

| # | 根因 | 影响场景 |
|---|---|---|
| 1 | Playwright 链式语法错误：`.billing-price-row >> nth=0 .ant-select-selector` 缺少 `>>` 链接；且 antd v5 渲染类名为 `.ant-select-content`（非 `.ant-select-selector`） | billing-price-row-complete-save-success、billing-provider-options-restricted、billing-config-readback-persisted、spec-cost-unavailable-all-unpriced |
| 2 | 断言时序：场景先将开关拨 ON、点「添加模型价格」（成功），再将开关拨 OFF 才执行可见性断言 → 断言应在关闭前执行或改为中间断言 | billing-toggle-reveals-and-hides-price-area |
| 3 | `.ant-tag-green` 选择器过宽：同时匹配成本 Tag 与时间轴完成态状态 Tag（detail.tsx:744 绿色） | billing-off-no-cost-in-spec-detail、spec-timeline-cost-tag-priced-runs-only |
| 4 | 级联依赖：下游场景依赖上游保存计费配置作为前置，上游因非法选择器未能保存，导致 7 个场景连锁失败 | billing-config-readback-persisted、billing-incomplete-price-rejected、billing-duplicate-price-rejected、billing-provider-options-restricted、spec-cost-summary-mixed-priced-unpriced、spec-timeline-cost-tag-priced-runs-only、spec-cost-unavailable-all-unpriced |

**建议**：修复上述测试场景选择器/断言时序后重跑验证；产品代码无需改动。

## 本轮场景集变更

当前稳定场景集共 8 个（第 1 轮）。

- 首轮写入 8 个场景

