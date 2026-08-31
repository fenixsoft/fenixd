# 验证报告：add-deliverable-extractor-semantics

- 运行时间：2026-08-30T17:11:09Z（报告裁决增强：2026-08-31）
- 结论：**验证通过（verified）——零产品 Bug**；3 个失败场景均实测定性为测试场景缺陷（test-defect）
- 覆盖面：12 场景 → 9 通过 / 3 失败（全部 test-defect）/ 0 警告 / 0 阻塞

## 一、语义覆盖结论（Requirement 层）

| 语义点 | 覆盖场景 | 结果 |
|---|---|---|
| 引用语境不阻断（references 不入缺件清单） | extractor-refs-context-not-blocking-v1 | ✅ 通过（无守卫产物、放行 implemented、主行可点击） |
| 交付语境仍阻断 + 清单仅含交付物 | extractor-missing-list-deliverables-only-v1 | ✅ 通过（`.info-msg` 精确全文匹配，引用路径未混入） |
| `.fenix/` 前缀归一化复检命中放行 | extractor-fenix-normalize-recheck-v1 | ✅ 语义本身通过（子行计数=1、清单精确全文不含 `.fenix/core/deliverables.py`）；状态徽标断言因场景行序缺陷落空（见二.1） |
| `.fenix/` 前缀复检落空按声明原样报缺 | extractor-fenix-prefix-missing-reported-v1 | ✅ 通过（含前缀原样入清单、第 2 次重派） |
| 引用缺失仅审计软校验（零 UI 产物、不消耗重试） | extractor-reference-missing-soft-pass-v1 | ✅ 通过 |
| 3 次封顶升级 + blocked 徽标 + 人工指引 | extractor-blocked-escalation-regression-v1 | ✅ 通过 |
| 在线清除守卫错误（子行即时移除） | extractor-clear-guard-error-online-v1 | ✅ 通过 |
| v1 详情页守卫横幅 | extractor-detail-error-banner-v1 | ✅ 通过 |
| 超长清单 + 特殊字符路径不溢出 | extractor-long-missing-list-special-chars-v1 | ✅ 通过（no_overflow 实测无横向/纵向溢出） |
| 空项目向后兼容 | extractor-empty-project-state-v1 | ✅ 通过 |
| v2 详情 Dialog 守卫全文 + 清除按钮 | extractor-v2-detail-error-fulltext | ⚠️ 场景缺陷（见二.2）；实测链路完整 |
| v2 引用语境空错误呈现 | extractor-v2-refs-not-blocking-detail | ⚠️ 场景缺陷（见二.2） |

## 二、失败场景裁决（含实测复现证据）

三个失败场景的失败断言/步骤均经 Playwright 直连 8787 实测复现定性，无一属于产品缺陷。

### 1. extractor-fenix-normalize-recheck-v1 — test-defect（行序假设错误）

- 失败断言：`text_contains tbody tr >> nth=1 >> .status-pill` 期望「已实现」、`nth=0` 期望「就绪」，双双落空。
- 根因：v1 列表默认按 **created 倒序**渲染（`core/dashboard/static/app.js` cmp 函数无 `specSort.key` 时走 `bc.localeCompare(ac)`）。mock 中 `fenix-normalize-pass-spec`(10:30) 晚于 `deliver-gate-sandbox`(10:00)，实测渲染 row0=🧪 已实现、row1=📌 就绪——与断言索引恰好相反。
- 关键佐证：**归一化复检语义本身已被通过断言证实**——`.spec-info-row` 计数=1、`.info-msg` 精确全文仅含 `core/dashboard/static/v2/pages/config.json`、不含 `.fenix/core/deliverables.py`（归一化命中不计缺件）。
- 截图：`screenshots/extractor-fenix-normalize-recheck-v1_assert_fail.png`
- 修复建议：断言改按 `data-spec` 定位行（`.spec-row:has([data-spec='fenix-normalize-pass-spec']) .status-pill`）而非 nth 索引。

### 2. extractor-v2-detail-error-fulltext / extractor-v2-refs-not-blocking-detail — test-defect（系统性：2 场景同根因）

- 失败步骤：`click tbody tr >> nth=0 >> button:has-text('详情')` 5s 超时（步骤 6），后续断言未执行。
- 根因：v2 操作列是 AMIS **`dropdown-button`**（`core/dashboard/static/v2/pages/project.json` 末列），「详情」在其下拉菜单内，且菜单项以 `a`/`span` 而非 `button` 渲染——`button:has-text('详情')` 永不可见。实测复现：行渲染正常（tbody tr=1、徽标就绪）但该选择器计数=0。
- 产品无缺陷的实测证据：按正确链路（点「操作」→ 点 `li a:has-text('详情')`）Dialog 正常打开，错误区完整呈现「错误:」标题、守卫全文 `交付物守卫：缺件 [core/dashboard/static/v2/pages/config-gate.json] — 不合并不推进，重派实现补齐（第 2 次）` 与「清除错误」按钮（1 个）。
- 修复建议：步骤拆两步——先 `click tbody tr >> nth=0 >> button:has-text('操作')`，再 `click li a:has-text('详情')`；后续断言无需改动。

## 三、聚合与映射

- 同类失败聚合：v2 两场景同根因 → 报 1 个系统性场景缺陷；v1 行序缺陷独立 1 个。合计 **2 个 test-defect，0 个 product-bug**。
- 分类-状态映射：3 个场景 classification=test-defect → 均已映射 `status=failed`（符合 design D3，不悬置为 warning）。
- 逐断言归因：3 个场景 `assertion_triage` 已补齐（2+1+1 条，全部非 product-bug，故不构成产品 Bug 放行问题）。
- no_console_error：全部场景 `filtered_network` 为空、无外部 API 豁免触发；未出现密钥/签名类错误。

## 四、总结

提取器结构化两类语义（deliverables/references）、`.fenix` 前缀归一化正式化、引用软校验、缺件阻断与 3 次封顶升级、在线清除，以及 v1/v2 双界面呈现一致性均验证通过。3 个失败场景皆为测试场景与前端实现细节（默认排序 / dropdown-button 结构）不对齐所致，不涉及被测产品代码缺陷；建议实现器按上述修复建议修订场景后复跑即可全绿。

## 本轮场景集变更

场景集与持久化集一致，无变更。

