# 验证报告 - improve-failover-model-mapping-ui

**生成时间：** 2026-08-28 08:58:33 UTC（基于本次运行）  
**验证状态：** ❌ 发现产品缺陷（bug-found）

---

## 验证摘要

| 指标 | 数值 |
|------|------|
| 总场景数 | 6 |
| 通过 | 0 |
| 失败 | 6 |
| 警告 | 0 |
| 阻塞（环境） | 0 |
| 控制台错误 | 0（全部场景 `no_console_error` 通过） |

所有 6 个场景本身均落在「配置页 / 链编辑器（Agent Models Tab）」范围内，全部 `no_console_error`、`no_click_interception` 通过，说明页面可加载、无 JS 报错、点击无遮挡。失败集中在**数据回显**与**保存反馈**两个功能性断言上。

---

## Bug 汇总

### Bug 1 — 链式 Provider 字段回显错误（major，系统性）

**影响场景（3 个）：**
- `chain-editor-load-display`
- `chain-editor-add-delete-move`
- `chain-editor-role-model-fallback`

**断言类型：** `text_match`（第 3 层）  
**失败证据：**

| 场景 | 选择器 | 期望 | 实际 |
|------|--------|------|------|
| chain-editor-load-display | `.chain-row[data-agent='implementer'][data-idx='1'] .assign-provider` | `bigmodel` | `""`（空） |
| chain-editor-add-delete-move | `.chain-row[data-agent='implementer'][data-idx='0'] .assign-provider` | `bigmodel` | `inferaiapi` |
| chain-editor-role-model-fallback | `.chain-row[data-agent='implementer'][data-idx='0'] .assign-provider` | `inferaiapi` | `""`（空） |

**根因推断：** 链编辑器中 Provider 字段的渲染/数据绑定存在缺陷——部分行的 Provider 值未被正确回显（显示为空或错绑到其它行的值）。注意同一数据在第 0 行 `.assign-model` 能正确显示 `custom-model`/`m1`，说明问题专属于 Provider 列的取值路径，而非整行缺失。

**聚合说明：** 3 个场景均指向同一根因（Provider 列回显逻辑），按聚合规则标记为「系统性问题」，合并为 1 个 Bug。

---

### Bug 2 — 保存后 Toast 提示不出现（critical，系统性）

**影响场景（3 个）：**
- `chain-editor-save-string-degenerate`
- `chain-editor-save-no-overwrite`
- `chain-editor-save-validation-error`

**断言类型：** `element_visible`（第 1 层）  
**失败证据：**

| 场景 | 选择器 | 期望 | 错误信息 |
|------|--------|------|----------|
| chain-editor-save-string-degenerate | `.toast-ok` | 保存成功提示可见 | `Timeout 3000ms exceeded` 等待 `.toast-ok` 可见 |
| chain-editor-save-no-overwrite | `.toast-ok` | 保存成功可见 | `Timeout 3000ms exceeded` 等待 `.toast-ok` 可见 |
| chain-editor-save-validation-error | `.toast-error` | 错误提示 Toast 可见 | `Timeout 3000ms exceeded` 等待 `.toast-error` 可见 |

**补充说明：** `chain-editor-save-validation-error` 同时失败了一个 `text_contains` 断言（期望页面包含文本「引用了不存在的 provider」），该断言同样未通过——与 `.toast-error` 不出现相互印证：后端 400 校验失败的错误信息未传递到 UI。

**根因推断：** 保存操作后，成功/失败反馈的 Toast 组件未渲染或未被触发（成功与失败两条路径均失效，说明不是单纯的错误展示问题，而是保存回调的反馈通路整体未打通）。这直接导致无法确认保存行为是否真实生效，属于阻断用户确认的关键功能缺失。

**聚合说明：** 成功/失败两条 Toast 路径在 3 个场景中一致失败，合并为 1 个 critical Bug，标注影响范围为全部保存交互。

---

## 判定依据（对照规则）

- **第 1-2 层断言**：`element_visible`（`.toast-*`）失败直接记为 Bug；`no_click_interception`、`no_console_error` 全部通过，无环境问题。
- **第 3 层断言**：`text_match` Provider 列失败，SPEC 未声明该内容为动态值，按「大概率为 Bug」处理。
- **no_auth_error / 网络特判**：本报告无云端密钥/签名错误，且 `no_console_error` 的 `filtered_network` 为空、无 `net::ERR_`，不涉及网络环境因素豁免。
- **断言时序特判**：`chain-editor-save-*` 失败发生在点击事件之后查询 `.toast-*` 全局提示元素（非弹窗内随关闭移除的 DOM），不符合「断言时序问题」模式，故确认为产品 Bug。
- **聚合**：两类失败各自在 ≥3 个场景出现相同 root cause，按规则各合并为 1 个 Bug 并标注系统性影响范围。

---

## 结论

**验证未通过。** 共发现 2 个系统性产品缺陷：

1. **major** — 链编辑器 Provider 列回显错误（3 场景）：部分 Provider 值为空或错绑，影响配置正确显示。
2. **critical** — 保存反馈 Toast 完全缺失（3 场景）：成功/失败提示均不出现，用户无法确认保存结果，且后端校验错误也未上抛到 UI。

**建议优先修复 Bug 2**（保存反馈通路），因其阻断了所有保存类交互的可用性确认；随后修复 Bug 1 的 Provider 回显绑定。修复后需重新运行全部 6 个场景验证。
