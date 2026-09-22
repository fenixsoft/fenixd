## Context

时间轴由后端 `core/dashboard/data/timeline.py` 合成节点（state/admin/verify/run 四类），前端 `detail.tsx` 渲染。run 节点 agent 标签走 `agentLabel()`：先查 `AGENT_LABEL`（agent_type 键表，detail.tsx:275 附近），未命中再走 `RUN_ID_PREFIX_LABEL` 前缀兜底（detail.tsx:292，长前缀在前、首个命中即止）。`impl-ocr-` 已在 run_files.py `RUN_ID_AGENT_PREFIXES` 登记为独立 agent_type `impl-ocr`（add-impl-ocr-parallel-lane 任务 3.5），但两张前端表都没有对应条目 → 落 `impl-` 兜底显示「开发 Agent」。车道 run 转录 start 事件自带 message（`ocr 车道启动: <branch> <from8>..<to8>`，maintenance_runs.py `_write_impl_ocr_run_events`），时间轴 run 节点目前不透出。质量门禁数据在 detail payload（`detail.quality_gates.items`，含 gate id `code-review`），时间轴是独立 payload。

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

timeline.py 合成状态节点时，判定「最新状态转移节点且 to == testing」→ 复用 quality_gates.py 的 ocr 门合成函数取当前状态，附 `ocr_gate: {status, detail}` 字段；前端在 `status === 'running'` 时渲染注记「ocr 审查车道进行中，完成自动推进」（detail 一并透出更佳）。**同源硬约束**：时间轴 MUST 调 quality_gates.py 既有合成函数（import 复用），MUST NOT 复制第二套三态判定——这是与门禁 Card 不漂移的唯一保障。非 running 状态不渲染注记（前端零渲染），历史节点天然无注记。

### D4 渲染判断收敛进 qualityGates.ts 纯函数

注记显示条件（gate status 是否 running）与标签选择逻辑抽到 `qualityGates.ts` 既有纯函数模块（node:test 可加载，零 import 约束），`detail.tsx` 只做 JSX 套用——沿用 add-quality-gates-visibility 的既有分层（qualityGates.test.mjs 直接断言）。

### D5 非目标

不展示心跳实时进度（依赖 fix-ocr-lane-orphaned-state-misfire 心跳事件，另案）；不加车道节点终止按钮（维护型 run 非派发 run，取消语义未定义）；不改时间轴其他节点类型。

## Risks

- **payload 时差**：时间轴与 detail 门禁数据来自不同端点，轮询 tick 间可能短暂不一致（如车道刚完成但注记还在）。影响仅为注记多显示一个轮询周期（秒级），可接受；同源保证语义一致，仅时刻可能滞后。
- **历史节点误挂注记**：时间轴里有多个「→ testing」节点（打回重入等）。缓解：D3 限定「最新」状态转移节点，仅一个节点可携带。
- **前缀表顺序回归**：`impl-ocr-` 插入位置错误会被 `impl-` 先命中、标签退回「开发 Agent」。缓解：spec 场景 + node 测试断言标签选择。
