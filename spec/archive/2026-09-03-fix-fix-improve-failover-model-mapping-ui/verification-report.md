# 验证报告：fix-fix-improve-failover-model-mapping-ui

> 验证引擎执行时间：2026-08-28T16:10:52Z
> 验证结论：**未通过（bug-found）**

## 概览

| 指标 | 数值 |
|------|------|
| 场景总数 | 16 |
| 通过 | 7 |
| 失败 | 9 |
| 警告 | 0 |
| 错误（环境/异常） | 0 |
| 真实产品 Bug | 1（critical，系统性，影响 7 个场景） |
| 伪失败（测试剧本缺陷） | 2 个场景 |

## 判定方法

- 第 1/2 层断言（元素可见、可点击、数量）：直接记录。
- 第 3 层断言（文字/属性/计数）：大概率为 Bug，结合产品代码溯源判定。
- `no_console_error`：所有场景 `errors` 为空且含 `filtered_network` 字段，全部通过，无密钥/签名/网络层错误，**排除环境类误判**。
- 聚合：同根因的多个失败场景合并为一个系统性 Bug 报告，标注影响范围。

---

## 真实产品 Bug（1 项）

### BUG-01 · critical · 编辑器「加载」路径未归一化字符串/混合形态 provider

**影响场景（7 个）：**

| 场景 | 失败表现 |
|------|----------|
| `chain-role-model-fallback-echo` | 第1行 `.assign-provider` 回显为空，期望 `inferaiapi.com`（Bug 2 回显验证直接失败） |
| `chain-load-str-form` | `.chain-row` 可见断言 timeout（实际 0 行），`element_count` expected 1 / actual 0 |
| `chain-load-str-list` | 两行 `.assign-provider` 均回显为空（期望 `a`/`b`） |
| `chain-load-echo-mixed` | 第2行（字符串 `"b"`）`.assign-provider` 回显为空，期望 `b` |
| `chain-reorder-down` | 两行 `.assign-provider` 均回显为空（期望 `b`/`a`） |
| `chain-save-no-model-blocks` | 本应拦截保存并弹「无可用模型」错误横幅，实际因无链行导致校验跳过、未拦截（下游级联） |
| `chain-list-operations-save-order` | 操作后 provider 仍为空、保存成功横幅未出现（下游级联） |

**根因：** `core/dashboard/static/app.js` 的 `renderAgentAssignment`（约 1993–2032 行）仅按对象数组 `[{provider, model}]` 处理 `provider`：

- 第 1995 行 `const rows = (assigned && Array.isArray(assigned.provider)) ? assigned.provider : []` —— 当配置为单字符串 `"a"` 时，`Array.isArray` 为 false，直接返回空数组，**整行不渲染**。
- 第 2011 行 `const pname = r.provider || ''` —— 当 `provider` 是字符串数组 `["a","b"]` 或混合 `[{...}, "b"]` 时，数组元素是字符串，`r.provider` 取对象属性得到 `undefined`，`<select>` 不选中、回显为空。

后端 API 与 mock 均直接透传原始配置，**缺少在渲染前将 `"a"` / `["a","b"]` / `[{...},"b"]` 统一转换为 `[{provider, model}]` 的归一化预处理**。

**反证：** 对象数组形态 `chain-existing-array-not-overwritten`（配置 `[{a,m1},{b,m2}]`）中 m1/m2 均正确回显，证明对象数组渲染路径正常，缺陷仅限非对象形态。

**附加风险（静默数据丢失）：** 单字符串形态配置加载后因渲染为 0 行，用户即便只修改其它字段并保存，`collectConfigData`（app.js:2297-2311）也收不到任何链行，从而将该角色的 provider 分配从写入数据中整体剔除。这是比回显错误更严重的隐藏缺陷。

**修复建议：** 在 `renderAgentAssignment` 入口增加 `provider` 形态归一化，将 `string`、`string[]`、`{provider,model}[]` 三种形态统一转换为 `{provider, model}[]`：

```js
const raw = (assigned && assigned.provider) || [];
const rows = (Array.isArray(raw) ? raw : [raw])
  .map((r) => (typeof r === 'string' ? { provider: r, model: '' } : { provider: r.provider || '', model: r.model || '' }))
  .filter((r) => r.provider !== '');
```

---

## 伪失败（测试剧本缺陷，不计为产品 Bug）

| 场景 | 仅失败断言 | 说明 |
|------|-----------|------|
| `chain-move-buttons-disabled` | `element_count` expected 1 / actual 2 | 场景描述为「两行链 [a, b]」，实际 2 行；4 个上移/下移 `disabled` 属性断言**全部通过**，证明确为 2 行且禁用态正确。 |
| `chain-existing-array-not-overwritten` | `element_count` expected 1 / actual 2 | 场景描述为「对象数组 `[{a,m1},{b,m2}]`」，实际 2 行；m1/m2 均正确回显、保存成功。 |

两处 `element_count` 的 `expected=1` 为测试剧本笔误（应为 2），其功能性断言均通过，**非产品缺陷**。

---

## 通过场景（7 个）

- `deep-link-agent-models-tab-active` — 深链激活 Agent 模型页签修复验证通过
- `chain-empty-state-add-clickable` — 空状态添加按钮可达且新增行
- `chain-added-row-placeholder` — 新增行占位提示含角色级缺省
- `chain-add-row-save-success` — 新增行收集并保存成功（Bug 1 修复）
- `chain-single-row-disabled-move` — 单行上/下移均禁用
- `chain-delete-row-empty` — 删除后恢复 disabled 空状态
- `chain-single-row-degrade-save` — 单行无 model 保存成功（字符串退化场景）

---

## 结论

本次为对 `fix-improve-failover-model-mapping-ui` 缺陷修复的复验。复验发现修复**不完整**：已修复 Bug 1（保存链路）、Bug 3/4（禁用态与下移）的通过场景证实了部分修复有效；但 **Bug 2（Provider 回显）及旧形态/混合形态向后兼容在「加载」路径上仍失败**，并暴露一处静默数据丢失风险。需补充 `provider` 形态归一化（`renderAgentAssignment` 入口）后重新验证。
