## Why

SPEC 的唯一人类可读标识当前是 kebab-case 英文名（如 `add-knowledge-inbox-pipeline`），在列表页浏览时辨识成本高：中英文混排的工作语境下，用户需要逐条脑内翻译英文名才能回忆该 SPEC 做什么。为每个 SPEC 生成一个 5-25 字的中文标题（display name），与英文名构成 id/name 关系（英文名 = id，一切输入与寻址不变；中文标题 = name，纯展示），可让列表页一眼可读。立项（/fenix-new）是英文标题（kebab-case 名）的产生点，中文标题在同一点产生成本最低；自进化车道（evolution）是另一条 LLM 起草立项通道，需同步要求以保持全渠道一致。

## What Changes

- **立项生成**（新增）：/fenix-new skill 在生成 kebab-case 名的同一阶段生成 5-25 字中文标题，写入 `spec/changes/<name>/.spec.yaml` 的 `title` 字段（与既有 `mode` 字段写入同模式）。
- **evo 通道同步**（新增）：`core/evolution.py` 草稿契约增加 `title_cn` 字段，`materialize_draft` 写 `.spec.yaml` 时带上 `title` 行；`agents/evolution.md` 起草契约同步要求 5-25 字中文标题。
- **读侧与 API**（新增）：title 读取单点（活跃目录优先、归档目录回退，签名缓存同 `spec_mode` 模式）；`/api/specs` 列表项与 `/api/specs/<spec>` 详情透传 `title` 字段（缺失为 null）。
- **列表 UI**（新增）：v1 列表页名称列、v2 项目详情 SPEC 表格名称列，在英文名下方渲染中文副标题行；缺 title 不渲染（保持单行现状）；v1 名称关键字搜索同时命中 title。
- **存量回填**（新增）：为存量全部 SPEC（活跃 26 + 归档 509，其中 38 个归档目录缺 `.spec.yaml` 按脚手架约定补写）回填中文标题，逐目录读取 proposal/design 起草 5-25 字标题写入各自 `.spec.yaml`。

**非目标**：
- code-fix 通道（`core/code_review.py::generate_fix_spec`）为纯程序化模板生成（无 LLM 起草环节），本轮不加中文标题（模板化标题质量低且 `fix-cr-*` 名语义已自明）；后续需要可另行立项。
- 除两处列表名称列外的名称展示面（详情页标题栏、快速切换下拉、PageTitleBar）不变。
- 英文名（id）的一切消费方不变：目录名、STATE.md、信号文件、CLI/API 写入路径、fix-* 树构造、排序均继续以英文名为准。

## Capabilities

### New Capabilities

- `spec-chinese-title`：SPEC 中文标题（display name）的立项生成（fenix-new + evo 双通道）、存储单源（`.spec.yaml` title 字段）、读侧归档回退与 API 透传。

### Modified Capabilities

- `dashboard-spec-table`（最后形态见 `spec/archive/2026-09-02-add-dashboard-spec-doc-tabs-and-info-clear/specs/dashboard-spec-table/spec.md`，其后历经多轮修订）：名称列在英文名下方增加中文副标题行；名称关键字过滤同时命中中文标题。
- `v2-commercial-ui`（活跃于 `spec/changes/redesign-dashboard-v2-ui/specs/v2-commercial-ui/spec.md`）：项目详情 SPEC 表格名称列在英文名下方增加中文副标题行。

## Impact

- **代码面**：`core/dashboard/data/`（title 读取单点 + summary 透传）、`core/evolution.py`（草稿契约 + 模板）、`agents/evolution.md`（起草契约）、`skills/fenix-new/SKILL.md`（生成纪律）、`core/dashboard/static/src/`（SpecSummary 类型 + 两处列表名称列 + 搜索）及前后端测试。
- **数据面**：存量 535 个 `.spec.yaml` 回填 `title` 字段（497 修改 + 38 补写新建），全部为 git 交付物、随归档目录迁移。
- **性能面**：列表 API 每条目增加一次 `.spec.yaml` 读取——活跃侧经签名缓存摊销；归档侧经 SummaryIndex 每轮单次 `spec/archive/` 目录扫描建立映射，不做 per-spec glob（遵守既有 /api/specs 性能治理纪律）。
- **兼容面**：存量无 title 的 SPEC（含实现期新建）列表渲染零变化（不渲染副标题行），读侧容错缺省 null，零迁移强制。
