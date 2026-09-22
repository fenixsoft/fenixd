# 验证报告：add-run-record-readability

> ⚠️ 本报告由框架于 2026-09-22T11:55:26Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-09-22T11:49:52.242874+00:00

## 结论：❌ 未通过（Bug Found）

**状态：bug-found — 14/17 场景通过，3 失败，0 错误（2 个真实产品 Bug）**

17 场景 14 过 3 败，败因聚合为 2 个产品 Bug：① Task 卡片任务回填字段（description/summary）转换层已写入但渲染层无消费点；② thinking 强制渲染兜底在转换层生效但被 MessageItem 的原始 showThinking 隐藏逻辑击穿（跨 2 场景系统性）。web-think-load-older-pagination 的 no_click_interception 失败单列为场景设计矛盾（对已置灰按钮 click，test-defect），不改场景分类。静态情报 web-noise-semantic-system-rows assertions[6]『提交 @ fenix/read-noise』经核实为误报：文本非恰 2 汉字（含非汉字后缀），antd autoInsertSpace 不触发，且该断言本轮实测通过，无需修复场景。

| 指标 | 数量 |
| --- | --- |
| 通过 | 14 |
| 失败 | 3 |
| 错误 | 0 |
| 产品 Bug | 2 |
| 本链增量 Token（输入） | 8.47M |
| 本链增量 Token（输出） | 0.10M |


## 真实产品 Bug

### BUG-01（severity=major）· element_visible

- 关联场景：web-noise-task-backfill-and-fallback
- 描述：Task 子代理卡片的任务生命周期回填字段不渲染：task_started description『Run dispatch tests』与 task_notification summary『12 tests passed』在卡片上不可见（两条断言 3s 超时）
- 根因：runEvents.ts:421-428 已把 description/summary 回填到匹配消息（msg.taskDescription/taskSummary），但渲染层全仓无消费点：仅 MessageItem.tsx:88 读取 taskStatus 画状态点，taskDescription/taskSummary 从未输出到 DOM（单测只测转换层故未拦截）
- 证据（场景 web-noise-task-backfill-and-fallback 结构化证据，引用）：
  - failed_assertions: [{"type": "element_visible", "selector": "text=\"Run dispatch tests\"", "expected": "可见（started description 回填到卡片）", "actual": "Locator.wait_for: Timeout 3000ms exceeded — 元素未出现"}, {"type": "element_visible", "selector": "text=\"12 tests passed\"", "expected": "可见（notification summary 回填到卡片）", "actual": "Locator.wait_for: Timeout 3000ms exceeded — 元素未出现"}]
  - screenshots: ["/root/fenixd/.fenix/verify-progress/add-run-record-readability/screenshots/web-noise-task-backfill-and-fallback_assert_fail.png"]
  - first_failed_step: 断言5: 展开运行记录后 Task 卡片内未呈现 task_started description『Run dispatch tests』，3s 等待超时（卡片本体已渲染）

### BUG-02（severity=major）· element_visible

- 关联场景：web-think-duration-preview-fallback、web-think-load-older-pagination
- 描述：全程无正文（thinking-only）流的『强制渲染 thinking』兜底失效（系统性，2 场景）：开关关闭时整流 thinking 被静默，『已思考 5 秒/13 秒/数秒』折叠头全部不出现；NaN 断言通过恰因气泡根本未渲染
- 根因：兜底只做了一半：runEvents.ts:235 effectiveShowThinking 在转换层生成了 thinking 消息，但 ClaudeOutputPane.tsx:274 把原始开关 thinkingVisible（默认 false）直传 ClaudeMessageList→MessageItem.tsx:47『isThinking && !showThinking → return null』在渲染层无条件隐藏，兜底产物被下游击穿（对照 group 流开开关可渲染，web-group-thinking-toggle-split 通过）
- 证据（场景 web-think-duration-preview-fallback 结构化证据，引用）：
  - failed_assertions: [{"type": "element_visible", "selector": "button:has-text(\"已思考 5 秒 · 尾部收尾思考\")", "expected": "可见（无正文兜底：开关关闭仍渲染 thinking）", "actual": "Locator.wait_for: Timeout 3000ms exceeded — 元素未出现"}, {"type": "element_visible", "selector": "button:has-text(\"已思考数秒 · 真正的最后思考\")", "expected": "可见（无下一事件回退已思考数秒）", "actual": "Locator.wait_for: Timeout 3000ms exceeded — 元素未出现"}]
  - screenshots: ["/root/fenixd/.fenix/verify-progress/add-run-record-readability/screenshots/web-think-duration-preview-fallback_assert_fail.png"]
  - first_failed_step: 断言3: think 流（全程无正文）开关默认关闭时，spec 要求的强制渲染兜底未生效——尾部折叠头『已思考 5 秒 · 尾部收尾思考』未渲染，3s 超时


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
| web-noise-task-backfill-and-fallback | 任务生命周期回填：task_started/task_notification（tool_use_id 匹配 call_T1）不渲染独立行、回填到 Task 工具卡片（description/summary 按 spec 2.1 要求在卡片呈现）；无匹配卡片的孤儿通知兜底为『任务通知：…』系统条不静默丢失。spec 详情页路径出处 routes.ts:23。 | failed（已修正） | 2/8 | product-bug |
| web-noise-runrecord-modal-compat | 消费方行为兼容（四个入口共享渲染管线）：时间轴『查看运行记录』旁全屏按钮打开 RunRecordModal（core/dashboard/static/src/pages/projects/components/RunRecordModal.tsx:14，标题『运行记录 · <runId>』），弹窗内 ClaudeOutputPane 同样呈现降噪后的流（计数头部/语义条在位），证明全屏弹窗入口与内嵌入口渲染一致。详情页路径出处 routes.ts:23。 | pass | 0/7 | - |
| web-group-same-class-aggregation | 同类连续聚合（开关默认关闭）：Read×2+Grep×1 聚『查阅 3 个文件/模式』；Bash×5 聚『执行 5 条命令』（收起态预览优先语义摘要『跑全量回归对齐基线』而非命令原文）；Edit/Write×5 聚『编辑 5 个文件』（收起态 3 个去重路径）；异类相邻各自成组不合并；短流（noise 的单个 Bash）不聚合（阈值 2）。spec 详情页路径出处 routes.ts:23。 | pass | 0/11 | - |
| web-group-card-summary-and-elapsed | 卡片摘要与耗时标注（展开『执行 5 条命令』组）：组内每条一行展示各自摘要/成败/耗时——B4 心跳观测 max(300,510)=510s 渲染『8m30s』；B5 错误结果（command not found）在卡片下以错误样式呈现；无心跳的 B3 卡片不渲染耗时标注（title=工具耗时的 span 计数为 0）。spec 详情页路径出处 routes.ts:23。 | pass | 0/10 | - |
| web-group-edit-dedup-and-threshold | 编辑组路径去重与展开回归：『编辑 5 个文件』收起态预览仅 3 个去重路径（首现顺序 alpha/beta/gamma，命中路径的 button 计数=1）；展开后全部 5 次调用可见（alpha 命中 button 计数=3：组头+E1+E2），收起/展开内容对账。spec 详情页路径出处 routes.ts:23。 | pass | 0/6 | - |
| web-group-thinking-toggle-split | 思考显示开关（默认关闭→打开）：关闭时 Bash×5 被 thinking 隔断仍聚合一组（静默等效不可见分隔符）；点开头部『显示思考过程』Switch（aria-checked 翻转 true）后 thinking 折叠头『已思考 13 秒 · <预览>』出现并真实断组为『执行 2 条命令』+『执行 3 条命令』。spec 详情页路径出处 routes.ts:23。 | pass | 0/8 | - |
| web-think-duration-preview-fallback | 全程无正文兜底+时长/预览回退：think 流（deepseek 形态，所有 assistant 事件仅 thinking 块）在开关默认关闭时仍强制渲染 thinking（兜底规则）；带相邻时间戳的块显示『已思考 13 秒 · <首行预览>』『已思考 5 秒』；流末无下一事件的块回退『已思考数秒』且不出现 NaN；超长首行预览在折叠头内截断（『已思考 12 秒』流按 12s 另锚）。等等——本场景时长以夹具实测 13s/5s 为准。spec 详情页路径出处 routes.ts:23。 | failed（已修正） | 2/8 | product-bug |
| web-think-load-older-pagination | 向前分页与总量计数：默认尾部窗口计数『显示尾部 300 / 共 360 条事件』；点击『加载更早事件』后前置拼接到流首（计数变『显示尾部 360 / 共 360 条事件』、头部 deepseek-v3 模型路由条出现、尾部既有内容不丢失、按钮到达流首置灰）。spec 详情页路径出处 routes.ts:23。 | failed（已修正） | 3/7 | product-bug |
| web-empty-spec-no-run-node | 空状态：无任何 run 产物的 spec（c-read-empty，implementer_run null）详情页时间轴不渲染『查看运行记录』折叠与全屏入口，页面不报错。spec 详情页路径出处 routes.ts:23。 | pass | 0/4 | - |


## 断言级豁免清单

以下失败断言被归类为非产品缺陷（不记产品 Bug），逐条列出供人工复核豁免是否掩盖真实缺陷（场景级一句话归因不足以复核）。

| 场景 | 断言 | 归类 | 豁免理由 | 证据 |
| --- | --- | --- | --- | --- |
| web-think-load-older-pagination | no_click_interception button:has-text("加载更早事件")（到达流首后置灰） | test-defect | 测试用例自身缺陷（非产品缺陷） | 场景设计矛盾：上一断言刚确认按钮 disabled（到达流首置灰，符合 spec），拦截检查再对该 disabled 按钮执行 click 必然超时（error: element is not enabled），非产品遮挡 |

## 本轮场景集变更

场景集与持久化集一致，无变更。

