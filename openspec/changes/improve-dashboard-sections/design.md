## Context

Dashboard（`core/dashboard/`）目前结构：`registry.py` 负责项目发现（显式 `projects` + 默认扫描 `~` 一级子目录，以 `STATE.md` 判定 Fenixd 项目）；`server.py` 提供 `/api/overview|specs|specs/<spec>|alerts|admin-activities|config` 等 REST 接口，并驱动 SSE 推送；`data.py` 是 TUI/Web 共享聚合层；前端 `static/app.js` 是原生 JS 单页（概览/项目/详情/配置/运维记录五视图）。

本次改动目标：概览页可控项目生命周期（启停 daemon、软删除）；运维记录按项目分页签 + 处置记录保留换行；项目表格支持排序、新增耗时列、fix-* 树状嵌套；spec 详情页四个长区块页签化。全部为 Dashboard 服务端 + 前端改动，不涉及 daemon 主进程（`fenixd.py`/`pm_engine`）行为。

现状要点：
- 每个项目 daemon 跑在唯一 tmux session（`fenix_session.session_name(root)` → `fenixd-<目录名>-<哈希6位>`），`is_running()` 只检测不启停。
- daemon 启动命令见 `skills/fenix-setup/SKILL.md`：`tmux new-session -d -s <session> "cd <root> && python3 .fenix/fenixd.py 2>&1 | tee .fenix/logs/stdout.log"`。
- `Registry.remove_project` 仅移除显式注册项；自动发现的项目无法从监控移除（下次扫描必重现），这是「删除项目」必须引入忽略列表的根因。
- 处置记录换行丢失：数据层把 list 字段 join 为 `；`（`agent_runner.py` 归一化），前端 `.activity-summary` 有 `pre-wrap` 但 `.activity-action/.activity-reco/.activity-fallback` 没有。
- `spec_summary` 已含 `latest_run`/`latest_run_status`，但无耗时聚合；`get_runs` 每条已有 `duration_seconds`。

## Goals / Non-Goals

**Goals:**
- 概览页可启停任意项目 daemon、软删除项目（不再自动发现，可恢复）。
- 运维记录跨项目视图按项目分页签；处置记录多行内容正确换行展示。
- 项目表格表头可排序、含「耗时」列（运行时长之和）、fix-* 树状挂载父规格。
- spec 详情页四个长区块（时间轴/场景/Bug/截图）独立页签，顶部常驻验证结论/进度/任务清单。

**Non-Goals:**
- 不做硬删除（不删项目文件）。
- 不改 daemon 主进程调度/生命周期逻辑。
- 不做服务端分页/虚拟滚动（当前数据量下前端排序足够）。
- 运维记录单项目路由（`activities/<project>`）行为保持不变，仅新增跨项目视图的页签分组。

## Decisions

### D1. daemon 启停复用 tmux session 管理

- `start_daemon(root)`：`session_name = fenix_session.session_name(root)`；命令与 `fenix-setup` 一致：`tmux new-session -d -s <session> "cd <root> && python3 .fenix/fenixd.py 2>&1 | tee .fenix/logs/stdout.log"`。启动前校验项目存在 `.fenix`（框架软链接）与 `STATE.md`，缺失返回可读错误。启动后等待 `is_running()` 命中再返回成功。
- `stop_daemon(root)`：先 `tmux send-keys -t <session> C-c` 触发 daemon 的 SIGINT 优雅关闭（`fenixd.py` 已注册 `shutdown` handler），轮询 `is_running()` 至多约 5s；仍未退出再 `tmux kill-session -t <session>` 强制终止。
- **备选**：直接 `tmux kill-session`（更快但跳过硬终止清理，run 产物/STATE 可能留下半写状态）；选择「优雅优先、强制兜底」兼顾数据一致性。
- 风险 → 缓解：`start` 竞态（同项目双击）→ 幂等：已运行则返回 `{ok:true, already:true}` 不重复拉起。

### D2. 软删除 = 忽略列表（ignored），而非移除显式项

- `dashboard.yaml` 新增顶层 `ignored: [<绝对路径>]`。
- `Registry.discover()` 在合并显式 + 扫描后，按规范化路径过滤 `ignored` 中路径，使被忽略项目（无论显式注册还是自动发现）都不再出现在监控列表。
- 软删除动作（`DELETE /api/projects/<name>`）：`stop_daemon` + 把该项目路径追加进 `ignored`。项目文件、`projects` 显式项、数据全部保留；恢复 = 手工从 `dashboard.yaml` 删除对应 `ignored` 条目（UI 不提供恢复按钮，避免误操作面）。
- **备选**：像 `remove_project` 那样从 `projects` 删除显式项。但自动发现项目不在 `projects` 里，删除后必被重新扫描发现——这正是用户「不要再被自动发现」所禁止的。忽略列表是唯一满足该语义的方案。
- 复用 `remove_project` 语义：被软删除项目的 `projects` 显式项一并移除，避免 config 冗余；但 ignore 优先，即便再次显式注册也被忽略。

### D3. 新增三个管理 API（`server.py`）

- `POST /api/projects/<name>/start`、`POST /api/projects/<name>/stop`、`DELETE /api/projects/<name>`。
- 路由按项目名解析到 `Registry.discover()` 的路径（`project_by_name`）；项目不存在/`exists=False` → 400。
- 返回 `{ok, error?, session?}`；成功后在 `sse_hub` 广播 `{type:"refresh"}` 触发概览自动刷新（daemon 状态变化不产生数据源文件变更，走心跳/refresh 通道）。
- `_handle_api_post`/`_handle_api_delete` 现有分发结构扩展即可，无新依赖。

### D4. 运维记录项目页签（纯前端状态）

- 跨项目视图 `data.projects` 已按项目分组返回活动。前端把 `renderActivities` 的平铺 section 改为 tab 栏：`全部` + 各项目名；点击切换显示对应分组，tab 状态存于前端模块级变量（不污染 hash 路由，保持 URL 语义）。
- `全部` 页签仍按 `data.projects` 顺序分段展示（保留现有结构作为聚合视图）。
- 单项目模式（`activities/<project>`）不变，仅渲染该项目卡片。

### D5. 处置记录换行保留

- 数据层：`agent_runner._read_disposition` 将 `actions_taken`/`summary` 的 list join 分隔符从 `；` 改为 `\n`（每动作/每段独立一行，语义更贴近"多条动作"）。
- 展示层：`.activity-action`、`.activity-reco`、`.activity-fallback` 增加 `white-space: pre-wrap; word-break: break-word`（`.activity-summary` 已有）。
- 旧数据（已存单行/`；` 分隔）不强制拆分——避免把叙述句子中的分号误拆；新写入记录即正确换行。

### D6. 表格排序 + 耗时列 + fix 树（前端为主）

- 排序：模块级 `specSort={key,dir}`；表头 `<th>` 可点击，遍历切换 `asc/desc/none`；排序键：状态（按生命周期序）、名称、优先级、创建时间、任务进度、验证、耗时、错误。表头加可点击样式与方向箭头。
- 耗时列：`data.spec_summary` 新增 `total_duration` = 该 spec 全部 run 的 `duration_seconds` 求和；前端 `fmtDuration` 渲染。排序键即 `total_duration`。
- fix 树：前端按「去前导 `fix-`（递归）到基名」分组；基名 spec 为根行，`fix-*`/`fix-fix-*` 为子行缩进渲染（缩进 + 连接线 + 🔧 标记）。排序以根节点整体排序（子行跟随父），树结构不因排序拆散。孤立 fix（父不存在）归入「无父级 fix」组。
- **备选**：后端排序/分组。选择前端做——列表已全量返回，前端状态驱动排序/分组交互更顺滑，后端仅补 `total_duration` 一个字段。

### D7. spec 详情页页签（前端状态）

- `renderSpec`：验证结论、验证进度、任务清单三个短区块保持平铺常驻顶部；下方新增 tab 栏：`运行时间轴`/`场景结果`/`Bug 列表`/`失败截图`，默认激活「运行时间轴」。
- tab 状态为模块级变量 `specTab`；切换时仅重渲染 tab 内容区。
- 时间轴挂载：`mountTimeline` 在 `renderView` 尾部调用；切到「运行时间轴」tab 后需在 DOM 就位时触发一次 `mountTimeline`（复用 `__tlRoot` 增量更新机制，不重建 root）。

## Risks / Trade-offs

- [启停命令在非交互环境执行 tmux] → 沿用现有 `is_running` 同样的 subprocess 调用方式（`capture_output` + 超时），异常一律返回错误对象不 500。
- [软删除后用户想恢复，UI 无入口] → 明确文档化：编辑 `~/.config/fenixd/dashboard.yaml` 删除 `ignored` 条目即可；概览卡片删除确认文案提示此路径。
- [list join 分隔符从 `；` 改 `\n` 影响存量解析] → 仅影响新写入记录；展示层 `pre-wrap` 对旧数据无副作用。
- [页签切换导致 React 时间轴二次挂载抖动] → 复用 `__tlRoot` 增量渲染，避免重建。
- [排序键对缺失值（created/耗时为空）的处理] → 缺失值恒排末尾（与现状 created 排序一致）。

## Migration Plan

- 无破坏性变更。`ignored` 为新配置键，缺省为空列表，老配置自动兼容。
- 部署即生效：Dashboard 服务重启（或 SSE refresh）后新 API 与前端可用；后端数据层改动无需迁移存量数据。

## Open Questions

- 无（需求经确认：软删除保留文件、耗时=运行时长之和、详情页顶部常驻+下方页签）。
