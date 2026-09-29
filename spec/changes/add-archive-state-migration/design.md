## Context

`.fenix/STATE.md` 是全框架的单一状态真相源，条目只增不减（fenixd 本机 354 条 / 12,789 行 / ~460KB，增速 ~10 条/天）。三条归档路径（daemon `auto_archive_check`、Dashboard `archive_spec`、`bin/fenix_archive.py`）都只移目录，条目原样保留——`archive_spec` 注释与 `fenix-archive` SKILL.md 均明文「STATE.md 条目保留」。写侧每次状态流转/预算自增都全量重写整文件（`_write_all_locked`：flock 内 serialize + fsync + rename），写放大线性恶化。

关键既有机制约束：

- 「已归档」可见性 = `is_spec_archived`（spec_archive.py:232）：「STATE.md 有条目 且 活跃目录不存在」。条目迁出后该判据失效，必须换双源。
- `/api/specs` 列表数据源 = `parse_state`（活跃全量），前端「已归档」视图（archivedOnly）消费 `archived` 字段。
- evo 撞名检查（evolution.py:1130）= `candidate in state_machine.read_all()`，只看活跃；迁出后不补双源会复发「撞名重复立项」（归档目录 glob 前缀误归属的姊妹问题）。
- `resolve_spec_dir` 已具备归档目录回退（活跃优先、归档按日期前缀+全等优先解析），迁出条目的文档/任务读取不依赖 STATE.md 条目。
- 软删除 `soft_delete_spec`：STATE.md 无条目时返回 `found: False`；迁出后对已归档 SPEC 的软删除需含清单。
- 统计（`project_summary`/`overview`）直接遍历 `parse_state` 结果——活跃口径在迁出后自然达成，无需改统计代码，但数字下降是预期行为（用户已确认）。

## Goals / Non-Goals

**Goals**

- 归档成功即把条目从 STATE.md 迁出至 `.fenix/STATE.archive.md`，STATE.md 收敛为「活跃条目」集合，写放大治理到位。
- 已迁出 SPEC 在「已归档」视图继续可见、可进详情，溯源字段（archived_at/archived_by）可审计。
- 存量已归档未迁出条目自动幂等回填，无需人工迁移脚本。
- 三条归档路径 + 软删除 + evo 撞名检查口径全部收口，无漏改消费方。

**Non-Goals**

- 不新增配置键（复用 `archive.auto_threshold`；回填不受阈值开关约束）。
- 不改 Dashboard 设置页与「已归档」视图前端交互（服务端合并后前端无感知，预计零前端改动；若渲染需透出 archived_by 再最小加列）。
- 不改 STATE.md 文件格式与 `parse_state` 活跃语义（调度、自省、watcher 均保持活跃口径，已归档 SPEC 本就不该被调度/自省计数）。
- 不做清单压缩/分片（清单只追加，终态条目不再变化，增长远慢于原 STATE.md——它不含预算计数器自增重写）。

## Decisions

### D1 清单文件与格式：`.fenix/STATE.archive.md`，同 STATE.md 格式

复用同一套 `### <name>` + `- key: value` 文本格式与解析循环（抽公共解析函数，`parse_state` 与新增 `parse_archived_state` 共用），零新格式学习成本；人可读、可 grep。放在 `.fenix/`（gitignored 运行时目录，与 STATE.md 同级同生命周期）。

### D2 迁出原语：STATE.md 既有 flock 内「先清单后活跃」两步

`StateMachine` 新增 `evict_spec(name, archived_by) -> dict`，在 `.STATE.md.lock` 的 flock 内：

1. `read_all()` 重读校验（条目仍在且为终态；不在则返回 `found: False` 幂等）；
2. 先把条目（+`archived_at`/`archived_by`）以追加模式写入清单（单次 write + fsync）；
3. 再 `_write_all_locked` 重写 STATE.md（不含该条目）。

**顺序理由**：崩溃/异常窗口只允许出现「清单已有 + 活跃仍有」的双源中间态（读侧活跃优先、回填下轮收敛），绝不允许「活跃已删 + 清单没有」的丢条目态。幂等处理：追加前扫描清单，同名条目已存在则以新内容原地覆盖（同格式整体重写清单），不产生重复小节。

清单写入失败（OSError）→ 返回失败、STATE.md 不动（D2 顺序天然保证）；STATE.md 重写失败 → 条目留活跃、清单已有副本（无害中间态，回填收敛）。

### D3 三条路径收口：共用 `archive_spec` 入口 + `bin/fenix_archive.py` 独立接原语

`archive_spec`（Dashboard API 与 `auto_archive_check` 共用，`archived_by` 以新参数传入区分 `ui`/`auto`）在目录移动成功后调 `evict_spec`；迁出失败降级为结果 dict 的 `evict_warning` 字段。`bin/fenix_archive.py` 目录移动成功后直接 import StateMachine 调同一原语（`archived_by=cli`；STATE 无条目时输出说明性字段不报错），与 `archive_commit` 同样的 fail-open 风格。

### D4 读侧双源

- `is_spec_archived`：`活跃目录不存在 AND（活跃 STATE 或 清单 有条目）`。
- `/api/specs`（spec_routes.py `_api_specs`）：`parse_state` ∪ `parse_archived_state`（同名单活跃侧优先），清单条目标 `archived=true` 并透传溯源字段；列表其余摘要组装复用既有 `spec_summary`，文档/进度读取天然走 `resolve_spec_dir` 归档回退。
- evo 撞名：候选名去重集合并入 `parse_archived_state` 键集。
- 统计（`project_summary`/`overview`）零改动：继续只吃 `parse_state`，活跃口径自动达成。

### D5 存量回填：独立函数挂既有低频周期

新增 `backfill_archived_entries(project_root, logger)`：扫描活跃 STATE 中「终态 + 活跃目录不存在」的条目逐个 `evict_spec(name, 'backfill')`，单条失败跳过记日志。调用点挂在 `auto_archive_check` 的同一周期触发处（先回填后阈值归档），但不受 `auto_threshold` 开关约束（阈值 0 仍回填）。非终态 + 目录缺失的异常条目跳过并记日志，留人工排查。

### D6 软删除兼容

`soft_delete_spec` 的 `found` 判定改为「活跃 STATE 或 清单 有条目」；条目仅在清单时，清理动作 = 移除清单小节 + 归档目录移除逻辑照旧；条目双源并存（中间态）时两处都清。清单小节移除与迁出写侧同锁：在 `.STATE.md.lock` 的 flock 内执行，避免与并发迁出/回填的清单写入竞态。

## Risks / Trade-offs

- **双源中间态**（崩溃窗口）：以 D2 顺序 + 读侧活跃优先 + 回填兜底收敛；最坏停留一轮周期（≤300s）。
- **清单整体重写的追加成本**：覆盖式去重需整体重写清单文件；清单条目为终态快照、写入频率 = 归档频率（远低于 STATE.md 流转频率），可接受。
- **统计数字下降**：已由用户确认接受（BREAKING 已在 proposal 标注）；「已归档」视图仍可见全量。
- **回归面**：`test_spec_archive.py` / `test_state_machine.py` 既有用例断言「条目保留」的需随行为更新；dashboard fixture 验证按 `fenixd-dashboard-fixture-verification` 配方做（假项目 + 伪造清单 + watcher 隔离会话截图）。

## Migration Plan

无停机迁移：上线后首个回填周期自动把存量「终态 + 目录已归档」条目迁出（fenixd 约 300+ 条，按 D5 逐条 `evict_spec`：每条一次清单写入 + 一次 STATE.md 全量重写，单轮周期内完成；存量多时首轮耗时上升属一次性成本）。回填幂等，中断重跑安全——已迁出条目自然退出扫描集，中断后下轮续收剩余条目。

## Open Questions

无（阈值复用既有配置；统计口径、迁出语义均已与用户确认）。
