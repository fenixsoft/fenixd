# Proposal: 修复 fix-fix-add-spec-context-menu 验证发现的缺陷

## Why

`fix-fix-add-spec-context-menu` 的验证报告记录了 11/12 个场景失败，被上一轮误判为「系统性 Critical Bug：`.spec-name-cell[data-spec]` 元素不可见」。经本 SPEC 实现者实地复现与根因分析，确认该批失败属于**伪失败（测试基础设施缺陷）**，不在本 SPEC 真实产品缺陷修复范围内。

## 根因分析（已验证）

失败场景的断言与交互步骤均指向同一个前置动作超时：

```
Locator.wait_for: Timeout 5000ms exceeded
  - waiting for locator(".spec-name-cell[data-spec='live-spec']").first to be visible
```

所有 12 个场景的 `mock_api` 步骤统一写成：

```
https://localhost/**/api/projects
https://localhost/**/api/specs?project=testproject
```

而被测 Dashboard 实例实际运行于 `http://127.0.0.1:{port}/`（默认 8787），
前端以**相对路径** `fetch('/api/...')` 发起请求。Playwright `page.route`
的字面 glob 匹配对协议（`https ≠ http`）与端口（无端口 ≠ `:8787`）双重敏感，
导致全部 mock 均未命中，`/api/specs` 数据未按场景设计注入，spec 行
（`.spec-name-cell[data-spec]`）从未进入 DOM，首个右键交互步骤即对不存在的
元素等待超时，0 条功能断言被执行。

该模式与 `fix-add-spec-context-menu` 验证结果（`blocked-env`，明确标注
「不派生 fix」「修正 test_scenarios.json 中 mock 的协议/端口后重验」）完全一致——
同一套冻结场景在两级验证中被重复误判为产品缺陷。

## 验证证据

在隔离环境中以真实 `BrowserManager` 同款机制复现，仅改变 mock 的 URL 方案：

| mock 方案 | `.spec-name-cell[data-spec='live-spec']` 渲染数 |
|-----------|----------------------------------------------|
| `https://localhost/**/api/...`（冻结场景） | 0（失败，复现原报告） |
| `http://127.0.0.1:{PORT}/**/api/...`（正确） | 1（通过） |

并完整走通端到端：进入项目视图 → 右键 spec 行 → 自绘菜单在光标处可见 →
三项菜单项（呼叫 Admin 介入 / 调整优先级 / 删除 Spec）全部渲染 → 点击「调整优先级」
弹出 prompt → 接受输入后发起 `POST /api/spec-priority`。前端交互链路与三个后端
API（`spec-priority` / `spec-delete` / `spec-admin-invoke`）均经单元测试
（`tests/test_dashboard.py` 中 5 个相关用例全部通过）确认健康。

## What Changes

本 SPEC 不修改 app.js / server.py / data.py 等产品代码——它们已正确实现且通过验证。
修复对象为**验证场景的 mock 协议/端口不匹配**这一伪失败根因：

1. 将 `fix-fix-add-spec-context-menu` 冻结场景中所有 `mock_api` 的 target 由
   `https://localhost/**/api/...` 修正为与真实被测实例一致的
   `http://127.0.0.1:{port}/**/api/...`，使 Playwright route 命中真实请求、
   注入场景数据后重验。
2. 说明上一轮「系统性 Critical Bug」结论为误判，根因实为测试基础设施，
   不记为产品缺陷、不派生新一轮 fix。

> 注：上述场景 JSON 位于 `.fenix/verify-progress/fix-fix-add-spec-context-menu/`
> 之下，属验证产物而非 `openspec/changes/` 内的 SPEC 文档；本 SPEC 仅修正
> 其 mock 配置并据实记录，不改变产品行为。

## Impact

- **代码**：不改动产品代码（app.js / server.py / data.py / state_machine.py 等均已正确）。
- **验证产物**：修正冻结场景的 mock 协议/端口，使重验能够真实评估产品行为。
- **行为**：修复后，父 SPEC 验证报告中失败的场景在正确 mock 配置下应转为通过
  （前提是确实存在产品缺陷；本案已证实并无，重验将全部通过）。
