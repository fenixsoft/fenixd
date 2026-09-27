## Context

时间轴由后端 `core/dashboard/data/timeline.py` 合成节点（state/admin/verify/run 四类），前端 `detail.tsx` 渲染。run 节点 agent 标签走 `agentLabel()`：先查 `AGENT_LABEL`（agent_type 键表，detail.tsx:275 附近），未命中再走 `RUN_ID_PREFIX_LABEL` 前缀兜底（detail.tsx:292，长前缀在前、首个命中即止）。`impl-ocr-` 已在 run_files.py `RUN_ID_AGENT_PREFIXES` 登记为独立 agent_type `impl-ocr`（add-impl-ocr-parallel-lane 任务 3.5），但两张前端表都没有对应条目 → 落 `impl-` 兜底显示「开发 Agent」。车道 run 转录 start 事件自带 message（`ocr 车道启动: <branch> <from8>..<to8>`，maintenance_runs.py `_write_impl_ocr_run_events`），时间轴 run 节点目前不透出。质量门禁数据在 detail payload（`detail.quality_gates.items`，含 gate id `code-review`）；时间轴与门禁同在 `/api/specs/<spec>` 聚合响应（summary.py `spec_detail` 同请求分别合成 `timeline` 与 `quality_gates` 字段），并非不同端点。

> ⚠️ 评审实测修正（前提缺口）：ocr 门的 `running` 态当前**不可达**——车道仅在 `run_impl_ocr` 收尾一次性 tmp+replace 落盘 `code-review.json`（status 白名单 `completed|unavailable`，maintenance_runs.py；全仓无 `status=="running"` 落盘写点），而 `_code_review_status`（quality_gates.py）只读磁盘产物、无在飞检测，尽管其 docstring 与 quality-gates-progress 契约（「车道在飞或产物 `status == "running"` 为 running」）均声称在飞→running。车道在飞窗口 Card 实际显示 pending（或上一轮同指纹产物），「ocr 并行审查进行中」从未真正出现过。本 SPEC 注记同源依赖该合成，MUST 先补全在飞检测（D6），否则注记永不渲染。

## Goals

- 用户看时间轴即可分辨：车道节点是谁（代码审查 Agent）、在做什么（审哪个分支哪段区间）、spec 为何停在 testing（停等注记）。
- 与质量门禁 Card 同源，两处口径永不漂移。
- 纯展示层，零探针/状态机/派发链路改动。

## Decisions

### D1 标签双路补条目（agent_type 键 + 前缀兜底）

`AGENT_LABEL` 增 `'impl-ocr': '代码审查 Agent'`；`RUN_ID_PREFIX_LABEL` 在 `['impl-', …]` **之前**插入 `['impl-ocr-', '代码审查 Agent']`（表已约定长前缀在前、首个命中即止，注释同步）。双路都补：agent_type 缺失的存量/异常数据仍有前缀兜底，不依赖单一通路。

### D2 车道摘要由后端 timeline.py 透出，不走前端转录读取

timeline.py 合成 run 节点时，对 `agent_type == 'impl-ocr'` 的节点读其转录 start 事件的 message 放入节点字段（如 `lane_summary`）；前端内容行直接渲染。前端不另发转录请求（时间轴已有聚合读路径，复用 run 元数据读取口，不新增端点）；message 缺失静默省字段。采用后端透出而非前端 join 的原因：转录文件定位/解析是后端职责，前端 join 会引入第二个读路径与缓存口径。

### D3 停等注记：后端在最新 testing 状态节点附 ocr 门状态，前端按状态渲染

timeline.py 合成状态节点时，判定「最新状态转移节点且 to == testing」→ 复用 quality_gates.py 的 ocr 门合成函数取当前状态，附 `ocr_gate: {status, detail}` 字段；前端在 `status === 'running'` 时渲染注记「ocr 审查车道进行中，完成自动推进」（detail 一并透出更佳）。**同源硬约束**：时间轴 MUST 调 quality_gates.py 既有合成函数（import 复用），MUST NOT 复制第二套三态判定——这是与门禁 Card 不漂移的唯一保障。非 running 状态不渲染注记（前端零渲染），历史节点天然无注记。复用入口固化为公开 `parse_quality_gates`（取 `items` 中 `id=="code-review"` 项），MUST NOT import 私有 `_code_review_status`；`get_spec_timeline` 增可选 `entry` 参由 `spec_detail` 调用点透传，`parse_quality_gates` 与 Card 同参调用——`_verify_progress_candidates` 的 worktree 候选仅 `spec_status=="implementing"` 时追加、指纹 expected 取 `entry.branch`，同参才能保证与 Card 在一切状态下逐字同源。

### D4 渲染判断收敛进 qualityGates.ts 纯函数

注记显示条件（gate status 是否 running）与注记文案抽到 `qualityGates.ts` 既有纯函数模块（node:test 可加载，零 import 约束），`detail.tsx` 只做 JSX 套用——沿用 add-quality-gates-visibility 的既有分层（qualityGates.test.mjs 直接断言）。agent 标签表（AGENT_LABEL / RUN_ID_PREFIX_LABEL）留在 detail.tsx 原地补条目（见 tasks 2.2），不做跨模块搬移。

### D5 非目标

不展示心跳实时进度（依赖 fix-ocr-lane-orphaned-state-misfire 心跳事件，另案）；不加车道节点终止按钮（维护型 run 非派发 run，取消语义未定义）；不改时间轴其他节点类型。

### D6 ocr 门在飞检测补全（注记可达性的前置）

车道在飞判据（读侧，复用既有数据）：`parse_quality_gates` 作用域内的 `runs`（get_runs 产物）中存在 run_id 前缀 `impl-ocr-` 且无终态事件的 run（车道 jsonl 启动写 `start`、收尾写 `result`/`error`，无终态即 in-flight，与既有 run 状态 no-terminal→running 判定同约定）→ `("running", "ocr 并行审查进行中")`；在飞判据优先于磁盘产物状态（重审轮 head 前移后上一轮产物指纹陈旧，本就不可采信）。契约源是 quality-gates-progress 既有条文「车道在飞或产物 `status == "running"` 为 running」，本任务为实现补全而非新需求；门禁 Card 与列表页 progress_phase 的 `testing ∧ ocr running` 窗口随之恢复契约本义。实现上 MUST 将 `runs` 参透传进 `_code_review_status`（parse_quality_gates 已持有，避免二次扫描）。

## Risks

## Risks

- **同请求双算（原「payload 时差」评审修正）**：时间轴与门禁同在 `/api/specs/<spec>` 聚合响应（summary.py `spec_detail`），无跨轮询时刻差；真实残留是同请求内 `parse_quality_gates` 被调两次（Card 一次 + 时间轴一次）的重复计算（指纹 git subprocess ×2），量级可接受；如需消除可经门面复用同请求结果，非本 SPEC 必须。
- **ocr 门在飞语义激活的波及面**：D6 落地后 Card 的 ocr 门与列表页 progress_phase 的 `testing ∧ ocr running` 橙条窗口从「恒不触发」恢复为 add-quality-gates-visibility 已声明的契约本义，属修复而非回归；验证场景须覆盖在飞→running 与 completed 后翻转回落。
- **历史节点误挂注记**：时间轴里有多个「→ testing」节点（打回重入等）。缓解：D3 限定「最新」状态转移节点，仅一个节点可携带。
- **前缀表顺序回归**：`impl-ocr-` 插入位置错误会被 `impl-` 先命中、标签退回「开发 Agent」。缓解：spec 场景 + node 测试断言标签选择。
