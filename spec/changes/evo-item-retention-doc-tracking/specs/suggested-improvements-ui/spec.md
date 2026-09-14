# suggested-improvements-ui 增量规格

## MODIFIED Requirements

### Requirement: 查看 SPEC 草稿

「查看 SPEC 草稿」MUST 展示该条目的 SPEC 文档，来源 `GET /api/evolution/draft?item_id=<id>&doc=<proposal|design|tasks|spec>`；`doc` 超出白名单 MUST 返回 400；条目不存在返回 404。

文档来源 MUST 按「草稿优先、SPEC 位置回退」解析：条目草稿目录 `.fenix/evolution/drafts/<id>/` 内存在目标文档时 MUST 读草稿（`pending` 等既有条目行为不变）；草稿缺失但条目记录含 `spec_name` 时，MUST 以 `spec_name` 为权威名解析 SPEC 目录（活跃 `spec/changes/<spec_name>/` 优先，`spec/archive/` 回退），并从该目录读取对应文档——使已被同意立项、草稿已随接受删除的条目仍可查看其文档。`spec` 文档取 SPEC 的 `specs/<capability>/spec.md`（`capability` 取条目记录 `spec.capability`）。解析后的目标路径 MUST 仍位于所解析目录内（越界一律拒绝）。

草稿与 SPEC 位置均无该文档时返回 `found: false` 并由前端显示空态。

#### Scenario: 切换查看四类草稿文档

- **WHEN** 用户对某 `pending` 条目点击「查看 SPEC 草稿」
- **THEN** 可查看 `proposal` / `design` / `tasks` / `spec` 四类文档内容，切换时不报错

#### Scenario: 非法 doc 被拒

- **WHEN** 请求 `doc=readme`
- **THEN** 返回 400，且 MUST NOT 读取草稿目录与 SPEC 目录之外的任何文件

#### Scenario: 草稿已删除但 SPEC 位置存在时回退读取

- **WHEN** 条目已同意立项（`accepted`，暂存草稿已删除），其 `spec_name` 对应目录存在于 `spec/changes/<spec_name>/`
- **THEN** 该条目的 `proposal` / `design` / `tasks` / `spec` 文档返回 `found: true` 与 SPEC 目录中的对应内容，MUST NOT 返回空态

#### Scenario: 归档后仍可跟踪文档位置

- **WHEN** 条目的 SPEC 已从 `spec/changes/` 归档到 `spec/archive/`（含 `YYYY-MM-DD-<name>` / `YYYY-MM-DD-<name>-<n>` / `<name>-<epoch>` 形态）
- **THEN** 该条目仍按 `spec_name` 命中归档目录并返回文档内容，MUST NOT 返回空态

#### Scenario: 草稿与 SPEC 位置均无文档时为空态

- **WHEN** 条目既无草稿目录，`spec_name` 也无法解析出 SPEC 目录
- **THEN** 返回 `found: false`，前端显示空态文案

#### Scenario: SPEC 名互为前缀不误归属

- **WHEN** 归档目录名归一化后与另一条目的 `spec_name` 互为前缀（如 `<name>` 与 `<name>-<hex>`）但并非全等
- **THEN** 该目录 MUST NOT 被解析为当前条目的 SPEC 位置（返回 `found: false`），除非归一化后与当前 `spec_name` 全等

### Requirement: 自进化 API 契约

Dashboard 后端 MUST 提供以下端点（沿用既有 `/api/*` 路由分发与错误语义）：

| 端点 | 方法 | 参数 | 语义 |
|------|------|------|------|
| `/api/evolution/items` | GET | 可选 `project` | 返回全部（或指定项目的）建议改进项摘要列表，按入库时间倒序 |
| `/api/evolution/analysis` | GET | `item_id` | 返回该条目 `analysis_md` 原文 `{found, content}`；条目不存在 404 |
| `/api/evolution/draft` | GET | `item_id`, `doc` | 返回文档 `{found, content}`（草稿优先、SPEC 位置回退）；`doc` 非白名单 400，条目不存在 404，两处均无该文档 200 + `found: false` |
| `/api/evolution/accept` | POST | body `{item_id}` | 执行接受路径，成功返回新 SPEC 名与状态 |
| `/api/evolution/reject` | POST | body `{item_id}` | 执行拒绝路径，成功返回新状态 |
| `/api/evolution/delete` | POST | body `{item_id}` | 删除条目（硬删：记录移出 `items.jsonl` 并清理其草稿目录），不设状态门 |

参数缺失 / 非法 MUST 返回 400 且不触碰任何文件；`item_id` 未知 MUST 返回 404。端点 MUST NOT 接受任意文件路径参数（读取范围固定为由条目 id / `spec_name` 推导出的 `.fenix/evolution/` 与 SPEC 目录路径）。每个条目摘要 MUST 至少含 `id`、`project`、`date_section`、`section`、`title`、三项判定、`status`、`has_draft`、`spec_name`、`created_at`、`decided_at`，并 MUST 含 `doc_source` 字段（取值 `"draft"` / `"spec"` / `null`）以标明该条目文档的可读来源。

前端 MUST 依据 `has_draft || doc_source` 决定「查看」弹窗是否渲染文档页签：二者皆为假（`null`/缺省）时不渲染文档页签，仅展示分析结论。

#### Scenario: 列表端点返回摘要字段

- **WHEN** 请求 `GET /api/evolution/items`
- **THEN** 返回 200，每条含 `id`/`project`/`date_section`/`section`/`title`/判定三项/`status`/`has_draft`/`spec_name`/`doc_source`，且按入库时间倒序

#### Scenario: doc_source 反映文档来源

- **WHEN** 某条目草稿目录存在
- **THEN** 其 `doc_source` 为 `"draft"`；草稿不存在但 `spec_name` 可解析出 SPEC 目录时为 `"spec"`；两者皆无时为 `null`

#### Scenario: 未知条目返回 404

- **WHEN** 请求 `item_id=nonexistent` 的分析或草稿端点
- **THEN** 返回 404 与可读错误，不读取任何文件

#### Scenario: 拒绝任意路径参数

- **WHEN** 请求携带 `path=/etc/passwd` 之类的任意路径参数
- **THEN** 该参数被忽略，读取范围仍限于由 `item_id` / `spec_name` 推导出的路径
