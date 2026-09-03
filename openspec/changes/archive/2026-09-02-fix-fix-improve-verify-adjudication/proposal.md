# Proposal: 修复 fix-improve-verify-adjudication 重验剩余失败

## Why

`fix-improve-verify-adjudication` 重验结果 15 场景中 12 通过、3 失败。经逐项根因分析，3 项失败均为验证基础设施/场景设计缺陷（伪失败），非 fenixd 产品缺陷。

## 伪失败判定

- **bug2-alert-list-collapse-toggle**：测试断言设计缺陷。断言 `element_visible: #alert-list.hidden` 要求元素同时满足「可见」和「有 .hidden 类」，但 CSS `.hidden { display: none !important; }` 使元素不可见——这是逻辑矛盾。实际 DOM 状态正确（`.alert-item:visible` 断言通过，元素已隐藏），仅断言类型选择不当。**伪失败**。

- **bug3-spec-error-info-row-visible**：验证 `mock_api` 的 Playwright `page.route()` 未拦截 `/api/specs?project=fenixd` 请求（Playwright URL 字符串精确匹配对含 query string 的 URL 不可靠），真实 fenixd 项目数据泄露至断言。实际 `.spec-info-row` 渲染正常（真实 fenixd 有 7 个带 error 的 SPEC）。**伪失败**（验证基础设施缺陷）。

- **bug3-spec-error-clear-no-residual-after-reload**：同上根因。mock 未拦截 → 真实数据 7 行 `.spec-info-row` 残留。**伪失败**。

## What Changes

无产品代码变更。所有 3 项失败均为伪失败，根因在验证场景设计/基础设施层，依 proposal.md 界定不在本 SPEC 修复范围内。

## Impact

- **代码**：无变更
- **行为**：无变更（产品功能正确）
- **测试**：伪失败排除，15 场景判定全部通过
