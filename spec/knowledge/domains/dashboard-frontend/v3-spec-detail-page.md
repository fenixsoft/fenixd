<!-- knowledge: capability=v3-spec-detail-page rev=1 sources=spec/archive/2026-09-08-add-v3-spec-detail-page -->

# v3 SPEC 详情页

v3 的 SPEC 详情：常驻信息区 + 四页签（运行时间轴 / 场景结果 / Bug 列表 / 失败截图）。

## 现行规则

- 路由 `/projects/:name/:spec`；SPEC 列表行内 spec 名称可点击进入；详情页提供返回列表导航（回 `/projects/:name`）；头部展示 spec 名称、状态与元信息。
- 顶部常驻信息区不随页签切换消失：error 横幅（`spec.error` 非空时渲染红色横幅，为空不渲染）、验证结论（verdict）、验证进度、Token 用量（tokens_in/out 与成本可用性，成本不可用时展示「成本不可用（网关未回传）」）、任务清单（tasks.md 分组与勾选状态）。
- 「运行时间轴」页签按时间序展示生命周期事件（状态迁移节点含回退原因）与运行记录节点（agent 类型、状态）；运行节点可展开查看该次运行的 LLM 对话流（经 `/api/runs/<run_id>/watch` 系端点，按需加载，不随页面打开全量拉取）。
- 「场景结果」页签展示汇总行（通过/警告/失败/错误计数）与场景卡片（状态、scenario_id、描述），失败场景可展开断言（✓/✗ 与消息）与失败步骤明细；`report.json` 损坏或不可读时展示专门错误语义「report.json 损坏或不可读」，无场景数据时展示「暂无场景结果」空态——两种语义区分不混用。
- 「Bug 列表」页签展示 bug 卡片（severity/来源/描述/关联场景/断言类型/证据）及关联截图缩略图；「失败截图」页签展示全部失败截图缩略图，点击任意缩略图打开全屏 lightbox 预览（`/screenshots/<project>/<spec>/<file>`，可关闭）。
- 无数据的页签保持可见可点，点开展示对应空态文案（暂无 Bug / 暂无失败截图）。

## 溯源

- 2026-09-08 add-v3-spec-detail-page — 建立 /projects/:name/:spec 路由与常驻信息区（error 横幅 / verdict / 进度 / Token / 任务清单）、四页签内容契约（时间轴按需加载对话流、场景双空态语义、Bug 卡片与截图 lightbox）
