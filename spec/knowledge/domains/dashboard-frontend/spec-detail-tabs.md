<!-- knowledge: capability=spec-detail-tabs rev=1 sources=spec/archive/2026-09-02-improve-dashboard-sections -->

# SPEC 详情页签

SPEC 详情页长区块的页签化组织与顶部常驻区块布局。

## 现行规则

- 详情页的四个长区块——运行时间轴、场景级测试结果、Bug 列表、失败截图——各自以独立页签展示；页签栏包含「运行时间轴」「场景结果」「Bug 列表」「失败截图」四项，默认激活「运行时间轴」。
- 点击页签仅显示对应区块内容；页签选择为纯前端状态（不改变 URL hash），在页面内刷新/SSE 重绘后保持。
- 无数据的页签显示空状态占位（如「暂无 Bug」）而非隐藏页签项，便于用户知晓该页签无内容。
- 页面顶部常驻展示验证结论（verdict）、验证进度（verify progress）、任务清单（tasks）三个区块——位于标题与状态信息之后、页签栏之前，不被页签栏收纳；三个区块保持既有渲染内容与交互（任务清单进度条、验证进度条、结论摘要等）。

## 溯源

- 2026-09-02 improve-dashboard-sections（spec/archive/2026-09-02-improve-dashboard-sections） — 详情页四长区块页签化（默认时间轴、纯前端选中态刷新保持、空数据页签占位）与顶部三区块常驻契约
