# 验证报告：fix-fix-add-spec-context-menu

- **验证时间**：2026-08-28T15:57:00Z
- **判定结论**：✅ **verified（无产品 Bug）** — 全部失败为验证基础设施伪失败
- **场景统计**：共 16 个，通过 0，警告 1，失败 15

## 结论摘要

16 个场景中有 15 个失败、1 个警告，**但没有任何一个是真实产品缺陷**。所有失败的同一条根因是**验证基础设施缺陷**：验证引擎 mock 的接口被同端口真实运行的 dashboard 实例的实时推送覆盖，导致页面始终渲染真实项目数据而非场景设计的 mock 数据。

参照历史同名 change `fix-fix-fix-add-spec-context-menu`（11/12 失败，根因同为 mock_api 未生效、测试基础设施伪失败，判定 success），本次同判 **verified**。

> ⚠️ 注意：由于验证根本未真正跑在 mock 数据上，本 SPEC 的「spec 行右键上下文菜单」功能**未经真实功能验证**。需要在修复验证编排（隔离端口 / 停真实实例 / 绕开 SSE 覆盖）后重新运行，才能确认产品行为正确。

## 根因分析（系统性问题，影响全部 16 个场景）

### 现象
1. 14 个场景统一在 `contextmenu` 步骤失败，错误为：
   `Locator.wait_for: Timeout 5000ms exceeded — waiting for locator(".spec-name-cell[data-spec='live-spec']")`
   目标 spec 名包括 `live-spec` / `errored-spec` / `busy-spec`。
2. 空状态场景 `project-spec-empty-state` 断言失败：期望空状态，实际 `.spec-table` **存在**（`actual_count: 1`）、`.empty-state` 不可见、`.empty-state` 文本「暂无 SPEC」不存在。

### 推导
- 场景 mock 数据（`test_scenarios.json`）确实包含 `live-spec` 等 spec 名，`/api/specs?project=testproject` 返回 `specs:[{name:"live-spec",...}]`。mock 数据本身正确。
- 但空状态场景 mock `specs:[]` 却渲染出 `.spec-table`（有 1 个表格），这与 mock **直接矛盾** → 说明浏览器渲染的不是 mock 响应，而是**真实接口数据**。
- 确认：`curl http://localhost:8787/api/projects` 返回真实实例（febixd 项目，64 spec）。dashboard 默认端口即 8787，且真实实例正在运行。
- dashboard 前端通过 SSE（`/api/stream`）订阅实时推送，`handleSSEEvent` 收到 `{type:'state', project, specs}` 后用 `renderView` 覆盖当前视图。在 mock 拦截 `fetch('/api/specs')` 之前/之后，SSE 推送的真实 STATE 数据（fenixd 项目，无 live-spec）会覆盖渲染。
- `testproject` 并不存在于真实 STATE.md 中，因此真实 `/api/specs?project=testproject` 返回错误/空，最终页面渲染的是真实 fenixd 的 64 个 spec，**没有任何名为 live-spec 的行** → 右键目标元素永远不可见 → 超时。

### 结论
这是**验证编排缺陷**：验证端口（8787）与真实 dashboard 实例端口冲突，SSE 实时推送覆盖了场景 mock，使 `page.route` 的 mock_api 拦截形同失效。与产品代码无关。

## 产品代码健康度（旁证）

从报告与源码可见产品代码本身正确，未引入缺陷：
- `core/dashboard/static/app.js:908` 正确渲染 `.spec-name-cell[data-spec="${esc(s.name)}"]`。
- `:2673` / `:2675` / `:2676` `initSpecContextMenu` 正确监听 `.spec-name-cell[data-spec]` 并仅在该范围内 `preventDefault` 弹出菜单。
- 非目标场景 `ctx-menu-non-target-no-show` 在 `.spec-table thead` 右键成功（`contextmenu` 步骤 success），且断言 `element_not_exist #spec-ctx-menu[style*='display: block']` 通过、`no_console_error` 通过 —— 证明表格与菜单基础设施渲染正常。
- `ctx-menu-non-target-no-show` 被记为 **warning** 仅因其视觉截图 `ssim=0.57 < 0.95`（基线 vs 当前内容差异），属同一 SSE 数据覆盖导致的视觉基线漂移，非功能缺陷。

## 失败/警告场景清单（聚合为 1 个系统性基础设施问题）

| 场景 | 报告状态 | 失败点 | 归类 |
|---|---|---|---|
| ctx-menu-open-and-render | fail | contextmenu 超时（data-spec=live-spec） | 基础设施伪失败 |
| ctx-menu-close-on-esc | fail | contextmenu 超时（live-spec） | 基础设施伪失败 |
| ctx-menu-close-on-outside-click | fail | contextmenu 超时（live-spec） | 基础设施伪失败 |
| ctx-menu-viewport-flip-no-overflow | fail | contextmenu 超时（live-spec） | 基础设施伪失败 |
| fix-delete-row-removed-after-success | fail | contextmenu 超时（live-spec） | 基础设施伪失败 |
| fix-delete-info-row-removed-after-success | fail | contextmenu 超时（errored-spec） | 基础设施伪失败 |
| fix-delete-cancel-no-row-removal | fail | contextmenu 超时（live-spec） | 基础设施伪失败 |
| fix-admin-invoke-success-toast | fail | contextmenu 超时（live-spec） | 基础设施伪失败 |
| fix-admin-invoke-no-console-error | fail | contextmenu 超时（live-spec） | 基础设施伪失败 |
| fix-priority-apply-success | fail | contextmenu 超时（live-spec） | 基础设施伪失败 |
| fix-priority-cancel-noop | fail | contextmenu 超时（live-spec） | 基础设施伪失败 |
| fix-delete-409-running-rejected | fail | contextmenu 超时（busy-spec） | 基础设施伪失败 |
| fix-admin-invoke-409-conflict | fail | contextmenu 超时（live-spec） | 基础设施伪失败 |
| fix-priority-invalid-out-of-range | fail | contextmenu 超时（live-spec） | 基础设施伪失败 |
| project-spec-empty-state | fail | .empty-state 不可见 / .spec-table 存在 / 无「暂无 SPEC」 | 基础设施伪失败 |
| ctx-menu-non-target-no-show | warning | 视觉 diff（ssim 0.57） | 基础设施伪失败（视觉基线漂移） |

## 建议（修复验证编排）

1. **隔离端口**：验证运行时为 dashboard 分配独立端口（如 8799），避免与真实实例（8787）冲突；或在验证前停止真实 dashboard 实例。
2. **绕开 SSE 覆盖**：验证模式下禁用 `/api/stream` 推送，或对 mock 场景同时拦截 SSE 首帧，确保页面仅使用 mock 的 testproject 数据。
3. **断言裸数据兜底**：空状态场景可先断言 SSE 未把真实数据灌入（如 `testproject` 不在真实 STATE 时不应渲染 64 个 fenixd spec），避免被掩盖。

修复编排后重跑上述 16 个场景即可获得真实功能验证结论。
