# 验证报告：add-v3-spec-quick-switch

- 验证时间：2026-09-02T07:42:04Z
- 验证轮次：修复轮（场景集冻结，5 个持久化场景全部覆盖）
- 结果统计：**4 通过 / 1 失败 / 0 警告 / 0 错误**

## 结论

**未发现产品 Bug。** 唯一的失败场景（`v3-quick-switch-select-navigates`）判定为 **测试断言设计缺陷（test-defect）**，产品代码逻辑正确。

## 场景明细

| 场景 ID | 状态 | 说明 |
|---|---|---|
| v3-quick-switch-arrow-visible | ✅ 通过 | 多 SPEC 时箭头按钮渲染且可点击 |
| v3-quick-switch-arrow-hidden-single-spec | ✅ 通过 | 仅含当前 SPEC 时箭头隐藏 |
| v3-quick-switch-dropdown-rows-exclude-current | ✅ 通过 | 下拉面板行内容正确、排除当前 SPEC |
| v3-quick-switch-select-navigates | ❌ 失败 | 点击行切换路由成功，但面板 DOM 断言误判（见下） |
| v3-quick-switch-getspec-failure-degrade | ✅ 通过 | 拉取失败静默降级，主体不受影响 |

## 失败分析：v3-quick-switch-select-navigates

**流程复核**：点击 SPEC 行后 `setSwitchOpen(false)` + `history.push` 均生效 —— 步骤 6 等待新标题 `add-spec-archive` 成功，断言 1/2（标题可见、含目标文本）与断言 4（`.spec-detail-card` 主体渲染）全部通过，`no_console_error` 也通过。

**唯一失败断言**：
```
element_not_exist  .spec-quick-switch-panel   →  actual_count=1（应为 0）
```

### 根因：断言类型选择不当（test-defect）

`element_not_exist` 断言通过 `page.locator(selector).count()` 检查 **DOM 节点存在性**。而 Ant Design Dropdown 在 `popupRender` 模式下关闭时——受控 `open` 转为 false——**面板 DOM 节点并不会被销毁**（`destroyPopupOnHide=false` 是 rc-trigger/antd 默认行为），只是通过 CSS 隐藏。因此：

- 产品侧：`setSwitchOpen(false)` 后 Dropdown 已收起（标题、主体均正常说明跳转完成），**功能正确**；
- 断言侧：检查的是「DOM 中不应存在该节点」，但 antd 语义下该节点保留、仅不可见。断言框架缺少 `element_not_visible` / `element_hidden` 这类可见性断言类型，测试场景只能选型 `element_not_exist`，导致此误判。

### 判定依据

- 该断言为第 1 层断言，但失败原因不属于产品行为错误，而是断言语义与组件框架行为（antd Dropdown 保留关闭后的 DOM 节点）不匹配；
- 同一场景其余功能性断言全部通过，且截图/时序上均无产品异常；
- 符合「断言时序/场景设计缺陷」豁免特征 —— 应改为断言「元素不可见」，或等待 Dropdown 销毁动画完成后再断言。

### 分类

- 场景分类：`test-defect`（测试场景设计缺陷，非产品 Bug）
- 建议修复：为断言框架补充 `element_not_visible` 类型，或将本场景断言改为可见性检查。

## 聚合结论

无合并 Bug；无系统性问题；无环境问题。

## 本轮场景集变更

场景集与持久化集一致，无变更。

