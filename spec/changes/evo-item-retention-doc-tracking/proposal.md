## Why

设置页「自进化」页签的条目列表存在两处长期缺口：

1. **条目无保留策略**：`.fenix/evolution/items.jsonl` 只增不减（每轮自省持续入库），框架没有任何自动清理路径，历史条目永久堆积，列表噪声随运行时长线性增长。
2. **已立项 SPEC 文档失联**：条目被同意立项后，`accept_item` 会删除暂存草稿目录 `.fenix/evolution/drafts/<id>/` 并把文档复制到 `spec/changes/<spec_name>/`（归档后再迁入 `spec/archive/`）。而「查看」弹窗的文档读取（`read_evolution_draft`）只认旧草稿路径，条目记录里明明存着 `spec_name` 却没人用它找回文档——「查看 SPEC 草稿」对全部已立项条目恒为空态（实测 10 条 `accepted` 条目全部命不中，其中 1 条的归档目录名为非标准形态 `<name>-<epoch>`）。

本变更对齐两处：给条目列表加保留策略（自动硬删），并让文档读取能沿 `spec_name` 跟踪到 SPEC 的新位置。

## What Changes

- **新增条目保留策略**：保留「创建时间在最近 7 天内」与「按创建时间倒序最近 100 条」的**并集**（即两者中数量较多者），超出部分连同草稿目录**硬删除**；阈值写死为常量（不做配置项）；由 daemon 自进化检查点周期性执行，不依赖分析 run 是否在途。
- **文档读取支持 SPEC 位置回退**：「查看」弹窗的文档页签在草稿目录缺失但条目记录含 `spec_name` 时，改从 SPEC 当前位置读取（活跃 `spec/changes/<spec_name>/` 优先，归档 `spec/archive/` 回退）。
- **列表摘要新增 `doc_source` 字段**（`draft` / `spec` / `null`），前端据此决定文档页签是否渲染与空态文案。
- **非目标**：不改动既有 `resolve_spec_dir` 的语义（它按设计排除无日期前缀的软删除命名，与我们此处的 `spec_name` 权威跟踪不同源）；不新增配置键与设置页控件；不做读取侧过滤（清理是唯一的收敛路径）。

## Capabilities

### New Capabilities

（无新增能力——两处改动都落在既有能力的需求修订上。）

### Modified Capabilities

- `self-evolution`: 新增「条目保留与自动清理」要求——条目存储从「只增不减」变为「按 7 天 / 100 条并集保留、其余硬删」，并规定清理的触发点、失败隔离与时间戳缺失时的保留语义。
- `suggested-improvements-ui`: 修订「查看 SPEC 草稿」的读取来源（草稿优先、SPEC 位置回退），并在「自进化 API 契约」中补充列表摘要的 `doc_source` 字段与草稿端点的回退语义。

## Impact

- `core/evolution.py`：新增保留常量与 `prune_items`（清理）、新增 `resolve_accepted_spec_dir`（SPEC 位置解析）。
- `fenixd.py`：`_check_evolution_checkpoint` 在宿主守卫后接入周期清理（独立 try/except，不因在途判定跳过）。
- `core/dashboard/data.py`：`read_evolution_draft` 增加 SPEC 位置回退；`read_evolution_items` 增加 `doc_source` 字段。
- `core/dashboard/static/src/services/dashboard.ts`：`EvolutionItem` 接口补 `doc_source`。
- `core/dashboard/static/src/pages/settings/components/SuggestedImprovementsPanel.tsx`：文档页签渲染条件与空态文案改用 `doc_source`。
- 测试：新增 `tests/test_evolution_prune.py`；扩展 `tests/test_dashboard_evolution_api.py`。
- 前端构建产物 `core/dashboard/static/dist/`（gitignored）需重新 `npm run build`，不随仓库交付。
