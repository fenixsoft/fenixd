# 审查质量分面（项目页）

<!-- knowledge: capability=code-review-quality-tab rev=1
     sources=spec/archive/2026-09-24-add-code-review-agent-and-quality-tab -->

项目页「质量」分面：问题台账的可复选表格、手动触发审查入口、真实进度条与取消、批量生成修复 SPEC 入口。

## 规则

- 问题表格含「严重度 / 问题 / 状态」三列，支持按严重度与状态过滤、排序；「问题」列三行堆叠展示（第一行标题、第二行 `文件:行`、第三行 `[category] description`），内容行最多两行省略，超出经悬浮浮层看全文（Popover + Markdown 渲染，形制对齐开发分面「名称」列）。
- 表格支持行复选（`rowSelection`）并实时显示已选条数。
- 逐条「忽略」操作将条目置 `ignored`（`POST /api/code-review/items/status`），成功后从默认列表移除——`ignored` 是「用户显式标记」的状态，唯一入口在本分面。
- `in_spec` 条目提供逐条「清除归属」操作：重置回 `open` 并清空 `spec_name`（撤回误选的唯一途径）。
- 默认列表仅含 `open` 条目（`resolved` / `ignored` 默认隐藏，可经状态过滤查看）。
- 数据经 `GET /api/code-review/items` 拉取，随 SSE（`/api/stream`）与心跳兜底刷新，不只页面首次加载拉取一次；仅当「质量」分面被选中时才拉取数据与订阅，未选中不发质量数据请求（保持按需加载语义）。
- 手动触发按钮两枚：「全仓库审查」以 `scope=full`、「当期提交审查」以 `scope=window` 调 `POST /api/code-review/run`；两枚同视觉样式（同 `outlined`，不分主次）。
- 已有审查运行中时再次点击被后端 409 拒绝，前端明确提示「已有审查在进行中」，不启动第二个 run、不静默失败。
- 手动触发走「写文件信号 → daemon 消费」链路；项目文件信号无消费方（daemon 未运行或未受 supervisor 托管，`hosting_state == "unmanaged"`）时后端拒绝写信号并返回明确错误，前端原样提示（无人消费的信号会永久滞留，并可能在 daemon 下次启动时被消费成用户未请求的审查）。
- 触发成功进入运行中态：轮询 `GET /api/code-review/progress`（或经 SSE）获取 `{running, total, done, current}`，渲染真实百分比（`done/total`）与当前审查文件；取消按钮调 `POST /api/run-cancel`（携带 review_id 映射的 run_id）并给受理反馈；运行结束收起进度区并刷新问题表格；无运行中审查时不渲染进度条与取消按钮。
- 底部「生成修复 SPEC」按钮仅在选中项数 > 0 时可用，点击调 `POST /api/code-review/generate-spec`（body 携带选中 `item_ids`），成功提示 SPEC 名，选中条目流转 `in_spec` 后不再出现在 open 列表。

## 溯源

- 2026-09-24 add-code-review-agent-and-quality-tab（spec/archive/2026-09-24-add-code-review-agent-and-quality-tab） — 新建质量分面：问题表格与忽略/清除归属操作、双触发按钮（409 单飞拒绝与 unmanaged 托管拒绝透传）、真实进度条与取消、生成修复 SPEC 入口。
