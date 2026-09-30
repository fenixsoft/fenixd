# Design: add-code-fix-startup-stage-visibility

## Context

- 数据链路：前端每 2s 轮询 `GET /api/code-review/fix-progress` →
  `read_code_review_fix_progress` 转导 `core.code_fix.read_progress` →
  读 `.fenix/code-review/fix-progress.json`（批级）+
  `_synthesize_item_progress` 实时合成条级（源 = worktree 的
  `fix-out-<run_id>.jsonl`）。
- 取证定案（2026-09-24，第 3/4 批实测）：「修复中 → 首条处置」空档
  65s ~ 6min39s，全程在 claude 进程内部（编排侧仅 ~3 秒）；固定部分
  ~1 分钟（SessionStart hook + init + 首次 RTT），方差部分为网关首响应
  长尾。编排侧等待期间不知道 agent 内部细节，**但 run 转录文件
  `.fenix/runs/<run_id>.jsonl` 由进程实时追加**，末行事件类型足以判阶段。
- 前端现状：`CodeFixProgressCard.tsx` 对 `item_done=null` 整段不渲染
  （用户 2026-09-23 决定，防误导性 0 计数）。

## Goals / Non-Goals

- Goals：准备期卡片有内容（粗粒度阶段 + 已等待时长），零写侧协议改动。
- Non-Goals：网关长尾治理（failover/限流另行立项）；阶段 100% 精确；
  code-review / ocr 等其他车道（本 SPEC 只做 code-fix 读侧，形态可后续复用）。

## Decisions

### D1 读侧合成，激活条件收窄

新增 `_synthesize_startup_stage(project_root, progress)`，仅在
`running=true 且 phase ∈ {fixing, retrying} 且 out 零有效行`时激活——
与 `_synthesize_item_progress` 的激活域互补（out 有行时本函数短路为
null）。接入点在 `read_progress` 内、`_synthesize_item_progress` 之后，
复用其已读出的 out 行集合，不重复 IO。合成字段生命周期对齐
item_done/current_item 先例（core/code_fix.py:95-97、170-174）：
`startup_stage` 进 `FIX_PROGRESS_DEFAULT`（缺省 null），合成函数无条件先
置 null 再计算，`write_progress` 剥离该键不落盘（防合成快照经合并写持久
化成陈旧状态污染进度文件）。

### D2 阶段映射表（末行事件类型 → 短语）

| 末行形态 | 阶段短语 |
|---|---|
| 转录文件不存在 | 等待 agent 进程启动 |
| `system` `init` / `hook_started` / `hook_response`（初始化事件） | 会话初始化中 |
| `system` 其余子类型（`task_started` / `task_progress` / `background_tasks_changed` 等 mid-run 遥测） | agent 启动处理中 |
| `assistant` thinking / text | 模型分析分组中 |
| `assistant` tool_use | 正在执行 <工具名> |
| 其他（user / stderr / 未知） | agent 启动处理中 |

（词表经实测校准 2026-09-24：`.fenix/runs/code-fix-1790225011.jsonl` 中
`system` 子类型不止初始化类，还含子代理/后台任务遥测——按 type 整类归
「会话初始化中」会在启动窗口误标，故拆分。`thinking_tokens` 遥测已被
runner 事件循环过滤、不落盘，无需处理。）

时长口径：`now - 转录文件 birth time`。转录文件为**懒创建**：`_run_claude`
事件循环收到首条流事件（实测首行为 `system/hook_started`）才经
`append_run_line` open("a") 建文件；spawn 前无 touch（`touch` 仅 planner
节流路径先例，code-fix 车道无）——故 birth = 首事件到达时刻、非 spawn
时刻；spawn→首事件窗口由「文件不存在」分支覆盖（「等待 agent 进程启动」、
无时长），waited_minutes 自首事件起算、轻度低估（接受）。stat 取不到
birth 时 `waited_minutes` 置 null（不省键，对齐 D4 形态）。

### D3 fail-open 容错（硬要求）

run 流事件形态多样（转录前缀盲区教训：至少 9 种前缀），末行解析按
「读得到就显示、读不到就 null」处理：文件缺失 / OSError / 末行非 JSON /
JSON 无 `type` 键 → `startup_stage=null`。任何分支不得抛异常中断
`read_progress` 主流程（读侧 MUST NOT 500 是既有硬口径）。

### D4 数据透传与前端渲染

- `read_progress` 把 `startup_stage` 写进返回 dict；数据层
  `read_code_review_fix_progress` 的转导只 pop `worktree`/`run_id`
  两个内部键，合成字段自然透出，数据层零改动。
- 字段形态：`null | {stage: str, waited_minutes: int|null}`。
- `CodeFixProgressCard.tsx`：`item_done=null && startup_stage` 非空 →
  在原「本批已处置」行位置渲染准备段（阶段短语 + 「已等待 N 分钟」）；
  `startup_stage` 为 null → 维持整段不渲染。`item_done` 有值时该段
  逻辑完全不进入（条级计数优先）。
- TS 类型 `CodeReviewFixProgress`（services/dashboard.ts）增补
  `startup_stage` 可空字段。

### D5 重试轮天然正确

重试轮编排已刷新 `progress.run_id`（既有 task 2.2 机制），本函数一律以
`progress.run_id` 定位转录文件，重试切换后自动指向当前轮，无需额外处理。

## Risks / Trade-offs

- [run 文件归档迁移] 批收尾后 `runs/` → `runs/archive/`，但本字段仅在
  out 零行（批进行中）激活，phase 届时已离开 fixing/retrying，无交集 →
  接受。
- [粗粒度不准确] 映射是启发式（如网关长尾期间末行停留在 init，文案
  停在「会话初始化中」但实际在等模型）→ 接受：用户验收口径即「不要求
  100% 推进，不能没有显示」；已等待时长持续增长本身即「活着」信号。
- [birth time 平台差异] 部分文件系统 stat 无 birth → 退化为无时长文案 →
  接受。

## Migration Plan

纯读侧新增 + 前端渲染，无数据迁移；daemon 重启后生效（daemon 旧码陷阱）。

## Open Questions

无。
