# 时间轴立项原话展示（request.md）

<!-- knowledge: capability=timeline-origin-request rev=1
     sources=spec/archive/2026-10-31-add-timeline-origin-request -->

SPEC 立项原话的可追溯链路：用户 /fenix-new 立项时的原始一句话需求原文照录进 spec 目录 `request.md`，随 SPEC 全生命周期（含归档）留存，并在运行时间轴首个状态转移节点下完整展示。

## 规则

### 写侧（立项持久化）

- fenix-new 立项流程创建 change 脚手架时，把用户输入的原始一句话需求**原文照录**写入 `spec/changes/<name>/request.md`（UTF-8 纯文本）：不做工程化改写、不美化、不补上下文。
- request.md 是立项时刻的历史快照，落盘后不再更新：`/fenix-new --modify` 更新既有 SPEC 的 artifacts 时保持 request.md 原文不变；需求演变走 proposal.md / tasks.md 的正常更新通道。
- request.md 与 proposal.md 分工固定：request.md = 立项原话快照（永不更新），proposal.md = 需求 Agent 加工后的需求文档（随需求变更更新）。
- request.md 随既有 spec 目录提交流程入库（`git add spec/changes/<name>/` 自然覆盖，无新增提交逻辑），归档时随目录整体迁移，零额外迁移逻辑。
- 写侧唯一入口是 `skills/fenix-new/SKILL.md` 的写 request.md 步骤；绕过 skill 的创建路径无 request.md，属允许形态，展示退化为缺失、无副作用。

### 读侧（时间轴附着）

- `get_spec_timeline`（`core/dashboard/data/timeline.py`）在 spec 目录存在非空 request.md 时，读取其全文（经 `resolve_spec_dir` 解析，活跃与归档通吃）作为 `origin_request` 字段附到排序与折叠后的**第一个 state 节点**。
- 附着点唯一：仅首个 state 节点携带 origin_request，其余 state 节点不携带；run/verify/admin 等其它 kind 节点任何情况下不携带（时间轴无 state 节点时禁止退化挂到其它 kind）。
- 首个 state 节点不限转移类型：无 drafted→reviewing 转移的 SPEC（fast-track / 直接晋升，首个转移为 drafted→ready）与折叠链节点（chain，如 drafted→ready→implementing 折叠）同样附着，展示规则一致——折叠链上呈现为链上首个转移（drafted→…）的原话。
- fail-open 静默降级（对齐 lane_summary 模式）：request.md 缺失、读取异常或内容空白时，时间轴节点省略 origin_request 字段、详情接口零报错、前端不渲染任何占位。
- 时间轴排序折叠后不含任何 state 节点时不附着（state 节点唯一来源是 .fenix/logs 日志窗口，轮转有界留存，超窗/归档清理后可为空）；request.md 本体仍随 spec 目录入库与归档迁移，原话始终可从 spec 目录直接追溯，展示层降级不丢数据。
- request.md 读取独立于日志窗口锚定（created 不参与），不影响既有时间轴日志读取逻辑。

### 前端渲染

- state 节点携带非空 origin_request 时，在该节点内容区 from→to 状态转移行下方渲染原话引用块：多行原文以 pre-wrap 保留换行完整显示，样式为既有盒式卡片内的次级文本形态（引用边框/底色），与回退 reason 行视觉分层。
- 字段缺失或为空字符串时不渲染任何引用块结构（无占位）。
- 存储层不截断原文；超长原文（用户粘贴大段文本等）由展示层兜底：容器 max-height + 溢出滚动。原话通常一句话，不做折叠交互。

## 溯源

- 2026-10-31 add-timeline-origin-request（spec/archive/2026-10-31-add-timeline-origin-request） — 新建本页：立项原话持久化（fenix-new 写 request.md、原文照录与 --modify 不更新纪律）+ 时间轴首个 state 节点 origin_request 附着（fail-open 静默降级、归档路径解析）+ 前端原话引用块渲染。
