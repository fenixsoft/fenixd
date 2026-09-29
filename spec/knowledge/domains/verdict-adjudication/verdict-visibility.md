<!-- knowledge: capability=verdict-visibility rev=1 sources=spec/archive/2026-09-11-fix-verify-verdict-visibility -->

# 裁决可见性（Dashboard 呈现）

被裁决分类过滤的失败场景在 Dashboard SPEC 详情页的可见性：消除「有失败+有失败截图+无产品 Bug」的矛盾呈现。

## 现行规则

- Dashboard SPEC 详情页「Bug 列表」页签展示被分类过滤（classification ∈ test-defect/flaky/env，即非 product-bug）的失败/错误场景摘要，摘要含：场景 id、分类标签、裁决理由/证据摘要（evidence 或 status_corrected 标注）、关联截图缩略图（有则显示，复用 `/screenshots/` 路由，点击可放大）。
- report.json 全部场景通过或不存在失败场景时，Bug 列表页签显示「无遗留 Bug」空态，不渲染摘要区块。
- 后端 `spec_detail` 响应含 `filtered_failures` 字段：从 report.json scenarios 提取 status ∈ (fail, failed, error) 且 classification 为非 product-bug 分类的场景，每项含 scenario_id、classification、evidence 摘要、screenshots（basename 归一化）、status_corrected。
- 旧格式 report.json（无 classification 字段）不产生 filtered_failures 条目（该类场景按既有规则收录进 bugs；与 parse_bugs 收录规则互补，向后兼容）。

## 溯源

- [2026-09-11 fix-verify-verdict-visibility](spec/archive/2026-09-11-fix-verify-verdict-visibility/) — 新增被裁决过滤失败场景的 Bug 列表摘要展示、后端 filtered_failures 结构与旧格式数据兼容边界
