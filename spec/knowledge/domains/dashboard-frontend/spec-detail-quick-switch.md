<!-- knowledge: capability=spec-detail-quick-switch rev=1 sources=spec/archive/2026-09-09-add-v3-spec-quick-switch -->

# SPEC 详情快速切换

SPEC 详情页标题区名称旁的下拉切换器，在项目内多个 SPEC 之间快速跳转。

## 现行规则

- SPEC 详情页头部标题区的 SPEC 名称旁展示下拉箭头按钮，点击展开下拉面板；项目下除当前 SPEC 外不存在其他 SPEC、或下拉数据不可用时，不展示该箭头。
- 下拉面板以表格形式列出 SPEC，每行展示 SPEC 名称与状态标签；状态标签与 SPEC 列表页使用同一状态语义（statusMeta）。
- 面板不包含当前正在查看的 SPEC。
- 选中某个 SPEC 后收起面板并跳转至该 SPEC 详情页（`/projects/:name/:spec`），页面数据随路由参数变化自动加载。
- 数据复用既有 `GET /api/specs?project=` 接口；接口失败时静默降级（箭头不展示，或展开后显示加载失败提示），SPEC 详情页主体功能不受影响。

## 溯源

- [2026-09-09 add-v3-spec-quick-switch](spec/archive/2026-09-09-add-v3-spec-quick-switch/) — 新增详情页名称旁下拉快速切换（排除当前 SPEC、状态标签同源 statusMeta、失败静默降级）
