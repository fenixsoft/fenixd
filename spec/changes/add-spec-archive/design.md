# add-spec-archive — 设计

## Context

- CLI 归档已存在：`.fenix/bin/fenix_archive.py <name>` 将 `openspec/changes/<name>/` 移到 `openspec/changes/archive/YYYY-MM-DD-<name>/`（不覆盖、返回 JSON），`/fenix-archive` skill 仅移目录、不写 STATE.md。当前项目 108 个 change 目录，archive 为空，历史 SPEC 混在活跃列表中。
- Dashboard spec 列表链路：`server.py::_api_specs` → `data.py::parse_state(STATE.md)` → `spec_summary()`；行内「更多」菜单在 `list.tsx::specMenuItems`（呼叫 Admin / 调整优先级 / 冻结-解冻 / 删除）；过滤区有「全部/仅需求/仅问题」Radio.Group；「删除 Spec」已有「确认弹窗 + POST + 刷新」交互模式可对齐。
- 删除（`soft_delete_spec`）语义 = STATE.md 移条目 + 目录移 `archive/<name>-<Unix秒>/`，条目从所有视图消失；归档语义不同：条目保留、仅目录移走，需可切换查看。
- 配置体系：`ConfigLoader` 用户级/项目级深合并 + 30s mtime 热更新；`runs.keep` 是「其他」面板既有键（`ConfigLoader.get(effective, "runs.keep", 默认值)` 模式）。
- daemon 主循环（fenixd.py ~L220）1s tick，已挂 admin invoke 拾取（2s）、配置热更新（30s）、恢复复查（60s）等独立计时任务。
- 状态机：`done → pushed`，pushed 为终态；终态 SPEC 不再被调度，但 `parse_state` 读出的条目仍会进入列表与扫描视野。

## Goals / Non-Goals

**Goals**
1. 界面一键归档终态 SPEC，效果与 CLI skill 完全一致（同目录、同命名、STATE.md 不动）。
2. 归档判定有唯一事实来源，CLI 与界面两条路径产出相同可见性。
3. 超阈值自动归档开箱即用（默认 50），可配置、可禁用、可热更新。
4. 归档后活跃列表即时瘦身，已归档 SPEC 可回查。

**Non-Goals**
- 不提供「取消归档 / 恢复」功能（用户可手动移回目录或后续按需新增）。
- 不改动 CLI `fenix_archive.py` 与 `/fenix-archive` skill 的行为。
- 不改动「删除 Spec」的语义与 `archive/<name>-<Unix秒>` 命名。
- 不新增 STATE.md 字段（不写 archived/archived_at，见决策 D1）。
- 已归档视图不做搜索、统计等增强，仅过滤切换。

## Decisions

### D1: 归档判定 = 活跃目录存在性（唯一事实来源）

`spec_summary()` 增加 `archived` 字段：STATE.md 有条目且 `openspec/changes/<name>/` 目录不存在 → `archived: true`。不检测 archive 下具体路径形态、不写 STATE.md 标志。

- 为什么不用 STATE.md 标志：CLI skill 归档不写 STATE.md，标志会漏标，需要目录检测兜底，两套逻辑并存必然漂移；目录存在性对三条归档路径（界面 API / CLI skill / 手动 mv）天然一致。
- 为什么不匹配 `archive/YYYY-MM-DD-<name>` 具体路径：删除路径命名（`<name>-<Unix秒>`）不同、手动移动命名不可控，活跃目录缺失已足够表达「不在活跃区」。
- 代价：每次列表请求多一次目录 stat（每 SPEC 一次 `Path.is_dir()`，108 个条目量级无感知）。

### D2: 归档 API 复用 fenix_archive.py 的核心逻辑

`data.py::archive_spec(project_root, spec_name)` 内联实现与 `fenix_archive.py::archive_change` 相同的移动逻辑（`shutil.move` → `archive/YYYY-MM-DD-<name>`，目标存在报错）。不 `import .fenix/bin` 脚本（该脚本设计为 CLI、经 `.fenix` 软链接定位项目根），而是把逻辑复制进 data.py 并保持命名规则一致；CLI 脚本保持不变。
终态校验在 API 层做（status ∈ {done, pushed} 才放行），CLI 层不加校验（skill 流程含人工确认，维持现状）。

- 备选：直接 `subprocess` 调 `fenix_archive.py` — 被否决：子进程错误处理与 JSON 解析间接，且 dashboard 与 CLI 共享 `core/` 模块的惯例是函数级复用而非进程调用。

### D3: daemon 调度扫描需跳过「目录已消失」的条目

归档后 STATE.md 条目保留，若调度器/巡检仍按条目派发或读取 `changes/<name>/` 会因目录缺失报错。实现自动归档时需核对现有扫描路径（pm_engine 调度扫描、verify snapshot 等读 changes 目录处），凡按 STATE.md 条目枚举 change 目录的地方对 archived 条目跳过。**此项作为实现期强制检查项列入 tasks**。

### D4: 自动归档 = 主循环独立计时任务，分钟级间隔

`fenixd.py` 主循环新增 `archive_check_ts`，间隔 300s。检查逻辑置于 data.py 或独立小模块：遍历各项目 → `ConfigLoader.get(effective, "archive.auto_threshold", 50)` → 统计终态未归档数量 → 超阈值按 entry `updated` 升序逐个调用 D2 的归档函数直至达标。0 = 禁用。

- 为什么不用事件驱动：状态机转换点多（done、pushed 两处 + 未来扩展），事件埋点易漏；分钟级周期对「归档积压」这类低频治理足够，与恢复复查（60s）模式一致。
- 为什么 300s：归档不敏感于秒级实时，且降低与调度器的资源竞争。

### D5: 配置键 `archive.auto_threshold`，默认 50

顶层新键 `archive`（`auto_threshold` 子键），与 `runs.keep` 平级同模式。ConfigLoader 宽松校验：非负整数，非法值记日志并回落默认 50。设置界面放 MiscSettingsPanel（用户指定「其他」分组），InputNumber min=0，说明文案标注「0 = 禁用；超过阈值时自动归档完成最久的 SPEC」。

- 用户决策：默认 50 开箱即用（而非 0 禁用默认），0 作为显式禁用开关。

### D6: 前端过滤控件用 Radio.Group「未归档/已归档」，置于「全部/仅需求/仅问题」右侧

`list.tsx` 新增 `archivedOnly` state（false 默认），过滤在客户端完成（列表 API 一次返回全部条目 + archived 字段，前端按字段筛选，与现有 status/type 过滤同层）。已归档视图下 `specMenuItems` 收敛：仅保留查看类，移除优先级/冻结/归档项。

- 备选：后端查询参数过滤 — 被否决：列表数据量小（百级），客户端过滤减少 API 变更面，且与现有 status/type 过滤的实现位置一致。

## Risks / Trade-offs

- [归档条目仍留 STATE.md，旧代码路径按条目读 changes 目录可能报错] → D3 强制检查项 + tasks 逐点核对；`spec_summary` 读文档/任务进度的路径需容忍目录缺失（返回空进度而非异常）。
- [自动归档误伤：用户希望保留的终态 SPEC 被归档] → 阈值默认 50 足够宽；归档可逆（目录移回即恢复）；活动事件记录归档动作可追溯。
- [多项目并发检查与调度竞争] → 自动归档检查在主循环串行执行（不另起线程），单项目内顺序 shutil.move，无锁竞争面。
- [YYYY-MM-DD 同日同名冲突（反复归档同名 SPEC 场景极少）] → 沿用 fenix_archive.py「目标存在即报错跳过」，自动归档跳过该条并记日志，不中断。
- [108 个存量终态 SPEC 在上线后首轮检查即触发批量归档] → 这正是功能意图（清空积压），300s 间隔分批（单轮只归档到阈值），动作全部落活动事件可审计。

## Migration Plan

1. 后端先行：data.py（archive_spec、archived 字段）+ server.py 端点 — 对旧前端无影响（新增字段向后兼容）。
2. 前端：菜单项 + 切换控件 + services 函数。
3. 配置 + daemon：config 校验、MiscSettingsPanel、主循环检查任务（默认 50，存量积压首轮自动清理）。
4. 回滚：各步独立可回退；已归档目录移回 `changes/` 即恢复可见，无数据转换。

## Open Questions

- 无（阈值默认值、完成判定、检查时机、STATE.md 处理均已与用户确认：done+pushed 可归档 / 目录存在性为准 / 默认 50 / daemon 周期检查）。
