<!-- knowledge: capability=spec-table-improvements rev=1 sources=spec/archive/2026-09-02-improve-dashboard-sections -->

# SPEC 列表体验改进

SPEC 表格的表头排序、耗时列与 fix-* 规格树状挂载。

## 现行规则

- 表头点击排序：各列表头可点击，点击同一表头在升序/降序/默认（取消排序）间轮换，表头显示当前排序方向箭头；排序状态在页面刷新/SSE 重绘后保持；缺失排序键值的行恒排末尾；用户未选择任何排序时才生效「创建时间倒序」默认排序。
- 列语义排序：状态按生命周期顺序（drafted→ready→implementing→bug-found→implemented→testing→verified→done→pushed）、名称按字典序、优先级按数值、创建时间按时间、任务进度按完成百分比、验证按已测/总数、耗时按数值、错误按有无。
- 耗时列：表格提供「耗时」列，展示该 SPEC 消耗的总时间；服务端聚合字段 `total_duration` 等于该 SPEC 全部运行记录（`get_runs` 按 spec 过滤后的所有 run，含 implementer/verifier/planner/tester 等）的 `duration_seconds` 求和，无任何运行记录时为 0；前端以人类可读时长格式渲染（不足 1 分钟显示秒、不足 1 小时显示分秒、1 小时以上显示时分秒），0 显示「—」；该列参与表头排序（按数值）。
- fix-* 树状挂载：fix-* 规格以树状结构显示在对应父规格之下，父规格通过递归去除名称前导 `fix-` 得到（如 `fix-fix-add-parallelism` → `add-parallelism`）；子规格行缩进渲染并带「🔧」修复标记，父规格行正常显示；多层 fix 嵌套（fix-fix-* 挂到 fix-* 下）同样成立。
- 树与排序：表格排序以根规格为粒度整体排序，子规格行跟随其父规格位置不拆散；父规格不存在的孤立 fix 归入「无父级」分组，不作为普通顶层行与真实规格混淆。

## 溯源

- [2026-09-02 improve-dashboard-sections](spec/archive/2026-09-02-improve-dashboard-sections/) — 新增表头点击排序（列语义 + 三态轮换 + 缺失值排末尾）、「耗时」列（total_duration 全 run 聚合）与 fix-* 树状挂载（递归去前缀、整体排序、孤立 fix 无父级分组）
