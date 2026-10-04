# 项目知识页签

<!-- knowledge: capability=knowledge-dashboard-tab rev=1
     sources=spec/archive/2026-10-05-add-knowledge-atlas -->

项目详情页中真相源的只读视图：浏览总目录与能力页、ADR 索引，按需加载零首屏开销。

## 规则

- 页签位置：项目页 Tabs 中「项目知识」位于「架构蓝图」之后、「会话接入」之前（URL `tab` 合法值含 `knowledge`）；按需加载门控——仅页签选中时发起 knowledge 数据请求，未选中零请求、面板不挂载。
- 后端只读 API（均 GET、无副作用、路由层零写路径）：`GET /api/knowledge/index?project=` 返回 index.md 文本 + 域清单 + 标题映射（面包屑中文名数据源），真相源未初始化（无 index.md）时返回 `initialized: false` 占位结构，项目不存在 404；`GET /api/knowledge/file?project=&path=` 返回白名单前缀（`domains/`、`adr/`）内单文件内容，含 `..`、绝对路径、反斜杠、越出真相源目录的路径恒 400（路径穿越拒绝先于存在性判断、不泄露存在性），白名单内文件缺失 404。
- 视图：①总目录 Markdown 渲染，域/能力链接可点击进入能力页渲染（规则散文与溯源段可见，溯源行可弹出归档文档）；②ADR 索引列表视图（编号、标题、状态标签，accepted 与 superseded 一目了然，superseded 条目带取代来源标识与跳转且保留在列）。
- 禁用与空态：`knowledge.enabled=false` 时页签仍在，内容区显示「知识真相源已禁用」占位而非报错；真相源未初始化时显示「尚未初始化」引导占位（归档首个 SPEC 后由蒸馏管线自动产出）。

## 溯源

- 2026-10-05 add-knowledge-atlas（spec/archive/2026-10-05-add-knowledge-atlas/） — 新增本能力页：页签插入位置与按需加载、只读 API 白名单与路径穿越拒绝、index/ADR 视图、禁用与未初始化占位；原契约另含关系图渲染位与 graph 下发端点
- 2026-09-29 graph 关系图区随 graphify 生图功能取消整体移除（无归档目录） — 探测、iframe 渲染位与 `/api/knowledge/graph` 下发端点一并删除，本页当前契约不含关系图
