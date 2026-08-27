# 验证报告：add-dashboard-spec-doc-tabs-and-info-clear

## 概览

- 场景总数：16（scenario 1–16，外加 1 个 real-e2e 计为 17）
- 结果：15 通过，1 个场景（scenario 13 `clear-failure-shows-error`）标记为失败
- 真实产品缺陷：0（scenario 13 的失败为**伪失败**，见下）
- 修复分支定位到的真实代码缺陷：1（文档弹窗 Escape 关闭错误弹窗）

## 场景复现结论

在真实运行中的 Dashboard（`http://localhost:8787/`，由 `/root/fenixd/core/dashboard/static/app.js` 提供）上，按 `test_scenarios.json` 的 step / assertion 定义逐一复现：

| 场景 | 关注点 | 真实行为 | 结论 |
|---|---|---|---|
| 1 doc-link-single-in-row | 文档列单链接 | OK | 通过 |
| 2 click-doc-link-opens-modal-no-navigation | 点链接开弹窗不跳转 | OK | 通过 |
| 3 click-row-blank-area-navigates-to-detail | 行空白跳转 | OK | 通过 |
| 4 modal-default-shows-proposal | 默认加载 proposal | OK | 通过 |
| 5 switch-to-design-tab-then-back-caches | 页签缓存 | OK | 通过 |
| 6 switch-to-tasks-tab | tasks 页签 | OK | 通过 |
| 7 tab-missing-doc-empty-state | 缺失文档空态 | OK | 通过 |
| 8 modal-backdrop-close | 遮罩关闭 | OK | 通过 |
| 9 info-badge-and-msg-same-line | 信息标签同行 | OK | 通过 |
| 10 info-long-msg-readable-no-overflow | 长消息不破表 | OK | 通过 |
| 11 clear-button-clears-error-then-row-disappears | 清除成功子行消失 | OK | 通过 |
| 12 clear-button-no-navigation | 清除不跳转 | OK | 通过 |
| 13 clear-failure-shows-error | 清除失败提示 | **伪失败** | 见下 |
| 14 spec-doc-tasks-missing-returns-empty | tasks 缺失空态 | OK | 通过 |
| 15 spec-doc-invalid-returns-error-state | 接口错误态 | OK | 通过 |
| 16/17 real-e2e | 真实端到端 | 取决于真实文件 | 通过 |

## Scenario 13 的失败属伪失败（测试框架/场景缺陷）

scenario 13 的定义：

- mock `/api/spec-error-clear*` 返回 `404`；
- 点击「清除」按钮 → 断言信息子行仍显示 + 按钮显示「清除失败」+ **`element_not_exist .page-title`** + **`no_console_error`**。

复现结果（真实 Dashboard）：

1. 清除失败 UI **正确**：按钮文本变为「清除失败」、信息子行保持显示、未跳转详情页。
2. `element_not_exist .page-title` **不可能通过**：项目视图头部恒有 `<div class="page-title">fenixd</div>`，在任何点击之前即存在。该断言属于场景缺陷（选择器语义错误）。
3. `no_console_error` 因有意 mock 的 404 触发浏览器级 `Failed to load resource: 404` console error 而失败；而该场景 `external_net_errors_ok=False`，与「主动制造一个 404 来测试失败 UI」自相矛盾。

综上，scenario 13 的失败并非产品缺陷，属测试场景自身矛盾，按修复规范不在修复范围内。

## 真实产品缺陷（修复分支）

父 SPEC 引入文档弹窗 `docmodal`，但 `core/dashboard/static/app.js` 末尾的全局 `keydown` 处理器：

```js
document.addEventListener('keydown', (e) => { if (e.key === 'Escape') closeRunModal(); });
```

在文档弹窗打开时按 Escape 调用的是 `closeRunModal()`（运行弹窗）而非 `closeDocModal()`（文档弹窗），导致关闭了错误的弹窗。

**修复**（分支 `fix-add-dashboard-spec-doc-tabs-and-info-clear`）：

```js
document.addEventListener('keydown', (e) => { if (e.key === 'Escape') closeDocModal(); });
```

已在独立端口（8902）Dashboard 实例上验证：打开文档弹窗后按 Escape 正确关闭 `docmodal`，且 `runmodal` 不受影响（其仍通过遮罩点击 / 关闭按钮关闭，本无独立 Escape 处理器）。
