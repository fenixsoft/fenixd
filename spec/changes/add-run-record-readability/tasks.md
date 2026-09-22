## Deliverables

```yaml
- path: core/dashboard/static/src/components/claude-msg/runEvents.ts
  kind: modify
- path: core/dashboard/static/src/components/claude-msg/toolGrouping.ts
  kind: modify
- path: core/dashboard/static/src/components/claude-msg/ToolCard.tsx
  kind: modify
- path: core/dashboard/static/src/components/claude-msg/Reasoning.tsx
  kind: modify
- path: core/dashboard/static/src/components/claude-msg/ClaudeOutputPane.tsx
  kind: modify
- path: core/dashboard/static/src/components/claude-msg/types.ts
  kind: modify
- path: core/dashboard/static/src/services/dashboard.ts
  kind: modify
- path: core/dashboard/static/tests/runStreamNoise.test.mjs
  kind: new
- path: core/dashboard/static/tests/toolGrouping.test.mjs
  kind: new
- path: core/dashboard/static/tests/thinkingScope.test.mjs
  kind: new
- path: core/dashboard/data/runs.py
  kind: modify
- path: core/dashboard/routes/run_routes.py
  kind: modify
- path: tests/test_dashboard_api.py
  kind: modify
- path: core/dashboard/static/dist/index.html
  kind: reference
```

## 1. 事件分类与降噪（runEvents.ts）

- [ ] 1.1 实现事件分类表（design D1）：静默名单（tool_progress/background_tasks_changed/commands_changed/run_metrics/init/hook_started/hook_response/superseded/turn_extension）、非名单结构化事件 fail-open 渲染「系统事件（<type>）」占位条、stderr 错误词表常量（error/Error/Traceback/failed/FATAL/refused）
- [ ] 1.2 实现语义化系统条：provider_marker（模型路由 model @ provider 第 i/共 n 棒，字段缺失降级「模型路由」）、transient_retry（reason+backoff+retry 序号+error 摘要 80 字，错误样式）、compact_boundary（trigger+pre→post tokens）、vcs_state_changed commit（短哈希+分支，其他 kind 静默）；全部不含 `[label]` 裸行
- [ ] 1.3 实现 task_started/task_notification 凭 tool_use_id 回填工具条目（taskDescription/taskStatus/taskSummary 字段），无匹配卡片时兜底为系统条；既有 session_ended/error/interrupted/cancelled 分支保持不变
- [ ] 1.4 实现 tool_progress 按 parent_tool_use_id 收集 max(elapsed_time_seconds) 映射，写入对应工具条目新字段（toolElapsedSeconds）
- [ ] 1.5 新增 tests/runStreamNoise.test.mjs（零依赖 node:test 直载 .ts，沿用 sessionEvents.test.mjs 模式）：分类表逐行锚定——静默名单不产出行、fail-open 占位条、stderr 词表两分支、四类语义条文案与降级、回填与兜底、session_ended 既有用例不回归

## 2. 工具同类聚合与卡片语义化（toolGrouping.ts / ToolCard.tsx）

- [ ] 2.1 toolGrouping.ts 增加工具→类映射（查阅=Read/Grep/Glob、命令=Bash、编辑=Edit/Write、其他沿用同名连续），同类连续成组（阈值 2 不变），组标题「查阅 N 个文件/模式」「执行 N 条命令」「编辑 N 个文件」，编辑组收起态按首现顺序去重展示路径
- [ ] 2.2 扩展 rendersNothing 语义：一切被静默/隐藏的消息（含开关关闭时的 thinking）不打断同类连续分组
- [ ] 2.3 ToolCard.tsx 摘要优先取输入 description（缺失回落 command/file_path 既有 summarize 兜底，单行截断），卡片右侧渲染 toolElapsedSeconds 为 XmYs 格式（无值不渲染），分组内条目行展示各自成败与耗时
- [ ] 2.4 新增 tests/toolGrouping.test.mjs：同类聚合（间隔 thinking 不断组）、异类断组、路径去重、阈值 2 不聚合、description 优先摘要、耗时标注有/无两分支

## 3. thinking 时长/预览与显示开关（Reasoning.tsx / ClaudeOutputPane.tsx）

- [ ] 3.1 实现时长估算：thinking 所在 assistant 事件与流中下一个 assistant 事件 timestamp 差（秒四舍五入；缺失/负值回退「已思考数秒」）+ 首个非空行截断约 40 字符预览，折叠头文案「已思考 N 秒 · <预览>」，流式「思考中…」不变
- [ ] 3.2 ClaudeOutputPane 头部新增「显示思考过程」开关（默认关闭，组件内 state），showThinking prop 保留；runEventsToChatMessages 内实现无正文兜底：全流无非空 text 块时忽略 showThinking=false 强制渲染 thinking
- [ ] 3.3 新增 tests/thinkingScope.test.mjs：时长估算（相邻时间戳/末尾无下一事件/负值回退）、预览截断、默认关闭不渲染且不断组、无正文兜底强制渲染、开关打开恢复

## 4. 向前分页（后端 runs.py / 路由 / 前端）

- [ ] 4.1 get_run_events 增加 offset_from_end 参数（默认 0）：events 按 len-tail-offset 到 len-offset 窗口切片（边界钳制），offset_from_end=0 行为与现状逐字段一致（status/total_events/error 语义不变）
- [ ] 4.2 run_routes.py run tail 端点透传 offset_from_end query 参数（缺省不改变既有响应）
- [ ] 4.3 dashboard.ts getRunTail 扩展可选 offsetFromEnd 参数与返回类型（total_events 已有，补充类型声明）
- [ ] 4.4 ClaudeOutputPane 头部实现计数「显示 N / 共 M 条事件」与「加载更早事件」按钮：点击以 offset_from_end=当前已加载条数重拉并前置拼接（SSE 增量只追加尾部互不冲突），已加载≥total_events 时按钮禁用，加载中展示加载态且不丢已渲染内容
- [ ] 4.5 tests/test_dashboard_api.py 补窗口切片用例：offset=0 与现状等价、中段窗口、越界钳制、total_events 与 status 不受窗口影响

## 5. 全量验证与构建

- [ ] 5.1 前端单测全绿（cd core/dashboard/static && npm test）且 npm run build 成功（dist 为 gitignored 构建产物，构建成功即可，不入库）
- [ ] 5.2 后端相关 pytest 通过（tests/test_dashboard_api.py 全文件），确认既有 run tail 消费方（detail 时间轴/AdminRunModal/AdminInvokeModal/RunRecordModal 打开路径）无回归
- [ ] 5.3 合成样本流 + 主树归档样本冒烟：构造含全部事件类型（心跳/语义/回填/终态）的最小 jsonl 与从主树 .fenix/runs/archive 复制一份真实大 run 流到临时目录，经 get_run_events 各 offset 窗口取事件后走 runEventsToChatMessages+groupConsecutiveTools 断言渲染序列（心跳零出现、分组聚合、计数与 total_events 一致）
