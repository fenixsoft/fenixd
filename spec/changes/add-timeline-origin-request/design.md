# Design: add-timeline-origin-request

## Context

- 时间轴数据链路：`core/dashboard/data/timeline.py` 的 `get_spec_timeline(project_root, spec_name, created, entry)` 产出节点列表（state/run/verify/admin），经 `_collapse_timeline` 折叠连续前向转移后返回；调用方 `summary.spec_detail`（dashboard 详情接口）透传给前端 `SpecTimeline.tsx`。
- 现状缺口：用户 /fenix-new 的原始一句话需求无任何持久化（STATE.md entry 只有调度字段；proposal.md 是 Agent 加工文本）。`skills/fenix-new/SKILL.md` 在本仓库管理，是 SPEC 立项唯一常规入口。
- 存量事实：既有时间轴注记先例 `lane_summary`（缺失静默省字段、调用方零报错）与 ocr_gate（entry 透传合成），本设计沿用同模式。
- 归档语义：`resolve_spec_dir` 通吃活跃（`spec/changes/<name>`）与归档（`spec/archive/<date-name>`）目录；spec 目录入库（git 管理）、归档随目录迁移。

## Goals / Non-Goals

**Goals:**
- 立项原话一处持久化（request.md），随 SPEC 全生命周期（含归档）可追溯
- 时间轴首个状态转移节点下展示原话，fast-track/直晋 SPEC 同样可见
- 存量 SPEC 零迁移、零报错

**Non-Goals:**
- 不做 SPEC 列表页/拓扑大屏的原话展示（仅详情页时间轴）
- 不改 STATE.md schema、不新增 CLI/dashboard 手工立项入口的写侧支持
- 不做原话的多语言/格式加工（原文照录）

## Decisions

**D1 存储位置：spec 目录 `request.md` 文件，而非 STATE.md entry 字段。**
备选是 STATE.md entry 新增 `origin_request` 进 `SERIALIZED_FIELDS`。弃选理由：(a) STATE.md 为行式 kv 格式，多行原话需转义、单行纪律脆弱；(b) STATE.md 是高频全量回写的运行时文件（不入库），原话属于需求历史，入 spec 目录随 git 留存有审计价值；(c) entry 字段方案触点更深（state_machine 白名单 + 归档迁出语义）。request.md 随目录走，归档零成本；`resolve_spec_dir` 读侧通吃活跃/归档。

**D2 附着点：`get_spec_timeline` 内部读文件、附「排序+折叠后」首个 state 节点。**
在 timeline.py 内做（而非 summary.py 组装层），原话节点归属与时间轴节点语义同域；附折叠后的首个节点，折叠链（chain）与普通节点统一处理。fail-open：文件缺失/读失败/内容空白 → 省字段（对齐 lane_summary 模式）。前端 `TimelineItem` 类型补可选字段，数据流零其它变更。

**D3 前端渲染：state 节点内容区状态行下方引用块，完整渲染不截断。**
多行用 `white-space: pre-wrap` 保留换行；样式走既有盒式卡片内的次级文本形态（Typography + 引用边框/底色），与回退 reason 行视觉分层。原话通常一句话，不做折叠交互；超长（异常数据）由容器自然撑开可滚动，存储层不截断。

**D4 写侧唯一入口：`skills/fenix-new/SKILL.md`。**
在「创建 change 脚手架」步骤后增加「写 request.md」子步骤：内容=用户 ARGUMENTS 原文，明文纪律「原文照录、不做工程化改写、--modify 不更新」。既有提交步骤（`git add spec/changes/<name>/`）自然覆盖，SKILL 无需改提交段。绕过 skill 的创建路径无 request.md → 展示退化缺失，无害。

## Risks / Trade-offs

- [Agent 立项时改写/美化原话，request.md 失真] → SKILL 明文「原文照录」硬约束；文件入库留痕可 diff 审计
- [超长原话（用户粘贴大段文本）撑爆时间轴节点] → 前端容器 max-height + 溢出滚动；存储不截断，展示层兜底
- [request.md 与 proposal.md 语义相近被误删/误合并] → SKILL 写明两者分工（request.md=立项原话快照，永不更新；proposal.md=加工后的需求文档）；Deliverables 声明不含 request.md（它是运行时由 skill 步骤产出、非实现分支代码交付物……实现分支需含 SKILL.md 修改使其必然产出）
- [归档 SPEC 时间轴读侧回归] → request.md 读取独立于日志窗口锚定（created 不参与），不影响既有日志读取逻辑；既有时间轴测试全量回归

## Migration Plan

纯增量：新 SPEC 由新 SKILL 步骤产出 request.md；存量无文件走静默降级。无回滚需求（去掉前端渲染分支即回退展示，request.md 文件留存无害）。
