# 验证报告：add-run-record-readability

> ⚠️ 本报告由框架于 2026-09-22T12:27:05Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-09-22T12:27:05.033074+00:00

## 结论：✅ 通过（verified）

**状态：verified — 17/17 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 17/17 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 17 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 9.17M |
| 本链增量 Token（输出） | 0.11M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| cli-fixture-run-record-streams | 夹具供给：幂等创建夹具项目 /root/run-readability-showcase（.fenix/STATE.md 含 4 个 done spec），在 .fenix/runs/ 写入 3 份确定性事件流 jsonl（noise 降噪验证流 / group 工具聚合流 / think 全程无正文+360 条分页流），随后轮询被测实例 /api/projects 确认自动发现（registry 发现 TTL 10s，core/dashboard/http_server.py:50）。cli 非零退出码即夹具/发现环境阻塞信号，后续场景均 depends_on 本场景。 | pass | 0/7 | - |
| cli-frontend-run-stream-unit-tests | spec Testing 段落锚定的前端 node:test 单测全量回归（runStreamNoise/toolGrouping/thinkingScope/sessionEvents 四套，零依赖直载 .ts 模式）：exit 0 且无失败用例——覆盖 spec『既有会话事件测试不回归』验收项（session_ended 三种 reason 中文系统行行为不变）与新增分类/聚合/thinking 纯逻辑单测。命令输出形态已实测：尾部摘要行『ℹ fail 0』。 | pass | 0/2 | - |
| api-run-tail-default-window | 后端 run tail 读取既有语义回归：不带分页参数 GET /api/runs/impl-c-read-think-fix1（360 条事件流），返回尾部 300 条窗口（events[0].seq==60、events[299].seq==359），total_events==360 不受窗口影响，末行 result 判 status==done。出处 core/dashboard/routes/base.py:308（^/api/runs/(.+)$）+ core/dashboard/data/runs.py:469（get_run_events）。 | pass | 0/5 | - |
| api-run-window-mid-offset | 向前分页窗口中段切片：tail=100&offset_from_end=150 → 窗口 [360-250, 360-150)，events[0].seq==110、events[99].seq==209，total_events 仍 360、status 仍 done（status 判定不受窗口影响，spec 4.1）。出处 core/dashboard/routes/run_routes.py:85（offset_from_end 透传）+ runs.py:507（切片）。 | pass | 0/5 | - |
| api-run-window-clamp-head-negative | 窗口越界钳制与负值容错（三连请求命名捕获）：offset_from_end=300&tail=100 越出流首→按流首截断（seq 0..59，events[60] 缺失）；offset_from_end=99999 越界至空窗但 status 仍 done；offset_from_end=-5 负值按 0 钳制=既有尾部语义（events[0].seq==350）。出处 runs.py:474（负值钳制/越界截断注释）。 | pass | 0/10 | - |
| api-run-missing-shape | 异常路径：查询不存在的 run_id（impl-c-read-ghost）→ exists==false、status==missing、total_events==0、events 空数组，不 5xx。出处 runs.py:481（missing 分支）。 | pass | 0/5 | - |
| api-noise-run-raw-passthrough | 读侧不裁剪契约：noise 流（短流，<300 条）默认窗口返回全量且原始事件逐字透传——响应体含 compact_metadata/provider_marker/tool_progress 原始载荷字段（静默是纯渲染侧行为，Non-Goals 不做后端过滤），events[0].type==provider_marker。 | pass | 0/8 | - |
| web-noise-semantic-system-rows | 心跳降噪+信息类语义化总场景：打开夹具项目 spec c-read-noise 详情页（/projects/run-readability-showcase/c-read-noise，出处 core/dashboard/static/config/routes.ts:23）展开运行记录——[tool_progress]/[status]/[init] 等裸行与心跳行全部消失；模型路由/瞬断/压缩/提交语义条逐字可见；非错误 stderr 静默、错误 stderr（ECONNREFUSED/Traceback）保留；未入名单事件走 fail-open 占位条；短流计数即全量（显示尾部 N / 共 N 条）且『加载更早事件』置灰。navigate 出处 routes.ts:23。 | pass | 0/33 | - |
| web-noise-task-backfill-and-fallback | 任务生命周期回填：task_started/task_notification（tool_use_id 匹配 call_T1）不渲染独立行、回填到 Task 工具卡片（description/summary 按 spec 2.1 要求在卡片呈现）；无匹配卡片的孤儿通知兜底为『任务通知：…』系统条不静默丢失。spec 详情页路径出处 routes.ts:23。 | pass | 0/8 | - |
| web-noise-runrecord-modal-compat | 消费方行为兼容（四个入口共享渲染管线）：时间轴『查看运行记录』旁全屏按钮打开 RunRecordModal（core/dashboard/static/src/pages/projects/components/RunRecordModal.tsx:14，标题『运行记录 · <runId>』），弹窗内 ClaudeOutputPane 同样呈现降噪后的流（计数头部/语义条在位），证明全屏弹窗入口与内嵌入口渲染一致。详情页路径出处 routes.ts:23。 | pass | 0/7 | - |
| web-group-same-class-aggregation | 同类连续聚合（开关默认关闭）：Read×2+Grep×1 聚『查阅 3 个文件/模式』；Bash×5 聚『执行 5 条命令』（收起态预览优先语义摘要『跑全量回归对齐基线』而非命令原文）；Edit/Write×5 聚『编辑 5 个文件』（收起态 3 个去重路径）；异类相邻各自成组不合并；短流（noise 的单个 Bash）不聚合（阈值 2）。spec 详情页路径出处 routes.ts:23。 | pass | 0/11 | - |
| web-group-card-summary-and-elapsed | 卡片摘要与耗时标注（展开『执行 5 条命令』组）：组内每条一行展示各自摘要/成败/耗时——B4 心跳观测 max(300,510)=510s 渲染『8m30s』；B5 错误结果（command not found）在卡片下以错误样式呈现；无心跳的 B3 卡片不渲染耗时标注（title=工具耗时的 span 计数为 0）。spec 详情页路径出处 routes.ts:23。 | pass | 0/10 | - |
| web-group-edit-dedup-and-threshold | 编辑组路径去重与展开回归：『编辑 5 个文件』收起态预览仅 3 个去重路径（首现顺序 alpha/beta/gamma，命中路径的 button 计数=1）；展开后全部 5 次调用可见（alpha 命中 button 计数=3：组头+E1+E2），收起/展开内容对账。spec 详情页路径出处 routes.ts:23。 | pass | 0/6 | - |
| web-group-thinking-toggle-split | 思考显示开关（默认关闭→打开）：关闭时 Bash×5 被 thinking 隔断仍聚合一组（静默等效不可见分隔符）；点开头部『显示思考过程』Switch（aria-checked 翻转 true）后 thinking 折叠头『已思考 13 秒 · <预览>』出现并真实断组为『执行 2 条命令』+『执行 3 条命令』。spec 详情页路径出处 routes.ts:23。 | pass | 0/8 | - |
| web-think-duration-preview-fallback | 全程无正文兜底+时长/预览回退：think 流（deepseek 形态，所有 assistant 事件仅 thinking 块）在开关默认关闭时仍强制渲染 thinking（兜底规则）；带相邻时间戳的块显示『已思考 13 秒 · <首行预览>』『已思考 5 秒』；流末无下一事件的块回退『已思考数秒』且不出现 NaN；超长首行预览在折叠头内截断（『已思考 12 秒』流按 12s 另锚）。等等——本场景时长以夹具实测 13s/5s 为准。spec 详情页路径出处 routes.ts:23。 | pass | 0/8 | - |
| web-think-load-older-pagination | 向前分页与总量计数：默认尾部窗口计数『显示尾部 300 / 共 360 条事件』；点击『加载更早事件』后前置拼接到流首（计数变『显示尾部 360 / 共 360 条事件』、头部 deepseek-v3 模型路由条出现、尾部既有内容不丢失、按钮到达流首置灰）。spec 详情页路径出处 routes.ts:23。 | pass | 0/7 | - |
| web-empty-spec-no-run-node | 空状态：无任何 run 产物的 spec（c-read-empty，implementer_run null）详情页时间轴不渲染『查看运行记录』折叠与全屏入口，页面不报错。spec 详情页路径出处 routes.ts:23。 | pass | 0/4 | - |

## 本轮场景集变更

场景集与持久化集一致，无变更。

