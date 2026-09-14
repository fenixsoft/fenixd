## Context

自进化条目存储在 gitignored 运行时文件 `.fenix/evolution/items.jsonl`（一行一条 JSON，`core/evolution.py` 的 `read_items` / `upsert_item` / `delete_item` 经 flock + 原子替换读写）。条目生命周期：分析 run 落地（`ingest_item`，状态 `pending`/`analyzed`/`draft_failed`）→ 人工/自动接受（`accept_item`，状态 `accepted`/`auto_accepted`，草稿目录被删、文档复制到 `spec/changes/<spec_name>/`）或拒绝（`rejected`）。当前**没有任何清理路径**：条目只增不减。

文档读取侧：`core/dashboard/data.py::read_evolution_draft` 只从 `.fenix/evolution/drafts/<item_id>/` 读，条目的 `spec_name` 字段（接受成功后写入）未被任何读取路径消费。证据：本仓库 10 条 `accepted` 条目全部无法在面板查看文档——9 条的文档在 `spec/changes/`，1 条（`evo-worktree-conflict-recovery`）已归档在 `spec/archive/evo-worktree-conflict-recovery-1789359846`。

约束：
- 用户决策：清理**一刀切全状态**（不保护 `pending`/`analyzed` 等未决条目）；阈值**固定常量**（不新增配置键，避免设置页 UI 联动）。
- 既有 `resolve_spec_dir`（SPEC 列表页复用）**明确排除**无日期前缀的 `<name>-<Unix秒>` 软删除命名（有单测 `test_resolve_soft_delete_variant_not_matched` 固定该语义）：其前提是「此类条目已从 STATE.md 移除、dashboard 无入口」。本变更的入口不同——条目记录里的 `spec_name` 是**权威命名**，不依赖 STATE.md，故不复用也不改动该函数。

## Goals / Non-Goals

**Goals**
- 条目列表按「最近 7 天 ∪ 最近 100 条」保留，其余硬删；daemon 周期自动执行。
- 已立项条目的文档可从 SPEC 当前位置（活跃 / 归档）读回，面板不再空态。
- 清理与回退解析都不得破坏既有语义（草稿优先、路径越界拒绝、flock 原子写）。

**Non-Goals**
- 不新增配置键与设置页控件（阈值固定）。
- 不做读取侧过滤（清理是唯一收敛路径；daemon 未运行时列表可能仍显示旧条目）。
- 不改动 `resolve_spec_dir`、不复活软删除命名的匹配。
- 不追踪「被删除条目」对应 SPEC 的文档（条目已不存在，无入口）。

## Decisions

### D1 保留判据 = 并集（最近 7 天 ∪ 最近 100 条），固定常量

删除条件为「不在最近 7 天窗口内」**AND**「不在按创建时间倒序的前 100 名内」——即保留两者并集（数量较多者）。常量 `ITEM_RETENTION_DAYS = 7` / `ITEM_RETENTION_MIN = 100` 定义在 `core/evolution.py`。

排序键 `(created_at or "", id)` 倒序，`id` 作确定性兜底，保证等时条目在多次运行间稳定。

*备选*：配置化阈值——否决，用户明确选择固定常量（且新增配置键按项目约定必须带 Dashboard 界面，扩大范围）。

### D2 清理入口复用 `delete_item`（硬删语义单一来源）

逐条调用既有 `delete_item(item_id, project_root)`：它已实现「记录移出 items.jsonl + 草稿目录删除（含符号链接越界校验）+ todo.md 标记幂等回写」的完整硬删语义，且读-改-写在 flock 内完成。重启一套批量删除逻辑会引入第二份路径安全实现。

规模论证：`delete_item` 每次重写整个文件，逐条调用为 O(n²)；但清理**每 5 分钟**跑一次，稳态 n 收敛在 100~150（阈值上限附近），实际写量约 2 万行，可忽略。

### D3 创建时间缺失/非法 → 保留（fail-open）

`_parse_iso` 解析不出时间时，**不能**把它归为「老条目」删除——否则一次写入缺字段会把新条目误删。判据按「年龄不可知 → 不满足『不在最近 7 天内』」处理，落在保留侧。

### D4 清理触发点：daemon 检查点内、宿主守卫之后、在途判定之前

`_check_evolution_checkpoint`（节拍复用 `admin.interval_minutes`，缺省 5 分钟）在通过 `PROJECT_ROOT == FRAMEWORK_ROOT` 宿主守卫后、`_evolution_in_flight` 判定**之前**执行清理，且清理自身 try/except 包裹（异常仅记日志，不影响后续派发与主循环）——保证分析 run 在途时清理照常发生（spec 场景「清理不因分析 run 在途而跳过」）。

放在宿主守卫之后而非之前：非自托管部署下自进化整套不启用，`PROJECT_ROOT` 是第三方项目根，对其 `.fenix/evolution/` 做删除不符合「整体不启用」的语义。

*备选*：分析 run 落地后清理——否决，会把清理绑死在 run 成功率上（run 失败/长期无就绪项目时永不清理）。

### D5 SPEC 位置解析：`resolve_accepted_spec_dir(project_root, spec_name)`

以条目记录中的 `spec_name` 为**权威输入**（而非从目录名反推 spec）：

1. `spec_name` 不满足 kebab 正则 → 返回 `None`（排除 `..`/`/` 穿越）；
2. `spec/changes/<spec_name>/` 是目录 → 返回（活跃优先）；
3. 否则遍历 `spec/archive/`，目录名归一化后与 `spec_name` **全等**比较，命中多个取 `sorted()[-1]`。

归一化集合 = 对目录名依次剥掉可选的 `^\d{4}-\d{2}-\d{2}-` 日期前缀与可选的 `-\d+$` 数字后缀所得的若干候选形态（含原样），判定 `spec_name ∈ 候选集`。覆盖三类归档命名：`YYYY-MM-DD-<name>`（标准归档）、`YYYY-MM-DD-<name>-<n>`（冲突后缀）、`<name>-<epoch>`（实测的软删除/直接移动形态）。

用**全等**而非前缀匹配：本仓库存在互为前缀的 spec 名（`evo-add-fast-track-scale-precheck` 与 `evo-add-fast-track-scale-precheck-4afdbe`），前缀匹配会把后者的目录误归属给前者（历史踩坑：spec→分支 glob 前缀误归属）。

*备选*：扩展复用 `resolve_spec_dir`——否决，它会打破既有单测固定的「软删除命名不匹配」语义（该语义服务于 STATE.md 无条目的场景，与本处 `spec_name` 权威入口的前提不同）。

### D6 读取回退顺序 + `doc_source` 字段

`read_evolution_draft`：草稿目录内目标文件存在 → 读草稿（既有行为不变，`pending` 条目零影响）；否则若 `rec.spec_name` 可解析出 SPEC 目录 → 按同一 `doc` 映射读 SPEC 文档（`spec` → `specs/<capability>/spec.md`，`capability` 取 `rec.spec.capability`，缺失时回退到唯一的能力目录）。解析后目标仍须落在 SPEC 目录内（防越界）。

`read_evolution_items` 摘要新增 `doc_source`：`"draft"`（草稿目录在）/ `"spec"`（SPEC 位置可解析）/ `null`。前端 `hasDocs = has_draft || doc_source` 决定文档页签渲染，空态文案按来源区分。

## Risks / Trade-offs

- [清理会删除未决条目（`pending`/`draft_failed` 等）] → 用户明确选择「一刀切全状态」；7 天 / 100 条并集对未决条目是很宽的窗口，且清理仅由 daemon 自托管模式下执行。
- [删除后 todo.md 同名记录被重新入库] → 不成立：`ingest_item` 落地时已写 todo 标记，`scan_ready_projects` 经 `strip_processed_entries` 剥离带标记条目；`delete_item` 再写 `deleted` 标记（幂等更新），双保险。
- [非标准归档名（`<name>-<epoch>`）的跟踪] → D5 归一化候选集覆盖；对未命中的仍返回 `null`，前端退化为空态（不报错）。
- [逐条 `delete_item` 的 O(n²) 写放大] → 稳态 n 收敛在阈值附近（D2 论证），且清理频率 5 分钟一次。
- [清理 OSError 单点失败] → 逐条 try/except，失败计数与详情入返回值，不中断其余条目与主循环。

## Migration Plan

- 无数据迁移：清理在首次 daemon 检查点自然生效；既有 35 条（全部创建于 2026-09-13，均在 7 天窗口内）不会被删。
- 回滚：还原 `fenixd.py` 的清理调用点即停止自动清理（清理函数本身为纯读-判-删，无残留状态）。
- 前端需在 `core/dashboard/static/` 重新 `npm run build` 重建 `dist/`（gitignored，不入库）。

## Open Questions

（无——阈值、清理范围、触发点均已由用户确认。）
