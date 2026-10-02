<!-- knowledge: capability=spec-list-filter-stickiness rev=1 sources=spec/archive/2026-09-26-add-spec-list-filter-stickiness -->

# 列表过滤条件保持

项目页 SPEC 开发列表的过滤状态与页签选中态持久化到 URL 查询参数，三条恢复路径视图一致。

## 现行规则

- 持久化范围：搜索关键词、状态多选、类型、归档切换 4 个过滤条件与页签选中态，同步写入 URL 查询参数；写入采用 replace 语义，不为过滤操作新增浏览器历史条目。
- 参数白名单与承载：`tab`（页签）、`q`（搜索关键词）、`status`（状态多选，合法状态枚举逗号分隔）、`type`（类型过滤）、`archived`（归档切换）。
- 合法值域：`tab ∈ {dev, quality, regression, session}`；`status ⊆ {drafted, ready, reviewing, implementing, implemented, testing, verified, bug-found, blocked, done, pushed}`；`type ∈ {active, completed}`；`archived = 1`。
- 缺省不写参：各参数处于缺省值时（`tab=dev`、`q` 为空、`status` 为空、`type` 为空即全部、`archived` 未归档）不写入该参数——默认视图下 URL 保持无参干净形态。
- 搜索防抖：关键词按既有 300ms 防抖节拍写入 URL，不逐字符同步；输入框回显与列表过滤的既有行为不变。
- 恢复路径：页面挂载时从 URL 恢复 5 项状态，使「从 SPEC 详情返回」「浏览器刷新」「带参 URL 直接打开」三条路径的视图恢复一致。
- 恢复细节：恢复搜索关键词时同时回填输入框（`q`）与生效过滤值，不出现「先展示全量列表、防抖到期后才过滤」的中间态；恢复页签复用分面 active 门控语义——仅被选中的分面发起自身数据拉取，未选中分面保持零请求；恢复到「会话」分面不隐式启动会话进程（未启动仍显示「开始会话」空态）；无参数（或参数缺省）打开时行为与引入本能力前完全一致。
- 非法参数 fail-safe：解析采用白名单校验，非法值静默忽略并回退缺省值——非法 `tab`/`type` 整体忽略回默认；`status` 中非法枚举逐个丢弃（全部非法视为无参）；`archived` 仅 `1` 视为已归档；不崩溃、不产生 console error、不将非法值传入过滤逻辑。
- 解析即消毒：页面稳定后 URL 中的脏参数被清洗（清洗后的合法形态写回或移除）。

## 溯源

- 2026-09-26 add-spec-list-filter-stickiness（spec/archive/2026-09-26-add-spec-list-filter-stickiness） — 建立过滤与页签状态的 URL 持久化：replace 写入、缺省不写参、三路径恢复一致与非法参数 fail-safe 消毒
