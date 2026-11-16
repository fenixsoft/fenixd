# Design: add-spec-chinese-title

## Context

SPEC 名（kebab-case）是全框架唯一寻址键：目录名、STATE.md、信号文件、fix-* 树、排序全部以它为键；列表页直接渲染英文名，中文工作语境下辨识成本高。立项（/fenix-new）与自进化（evolution）是两条 LLM 起草通道；code-fix（`code_review.py::generate_fix_spec`）为纯程序化通道。存量清单：活跃 `spec/changes/` 27 目录（含本 SPEC 自身；2 个 pushed 未归档且缺 `.spec.yaml`）+ 归档 `spec/archive/` 509 目录（38 缺 `.spec.yaml`），合计 536。

既有可复用基建：
- `.spec.yaml` 字段读取先例：`core/spec_mode.py::read_spec_mode`（签名缓存 `(path, mtime_ns, size)`，读侧全容错）。
- 归档目录解析单点：`core/dashboard/data/spec_docs.py::resolve_spec_dir`（活跃优先、归档日期前缀模式匹配、exact 优先）。
- SummaryIndex 预扫下发先例：`_runs_by_spec_sigs` 每轮单次扫描 runs 目录后传入 `spec_summary`（D2 常数化 glob）。

## Goals

1. 中文标题在立项点产生（fenix-new + evo 双通道），存 `.spec.yaml` `title` 字段，随 change 目录入库与归档迁移。
2. 两处列表名称列（v1 `list.tsx`、v2 `projectDetail.tsx`）英文名下方渲染副标题；缺失零影响。
3. 存量 535 目录全量回填，幂等可续做。

## Decisions

- **D1 存储单源 `.spec.yaml` `title` 字段**：与 `mode` 同位（git 交付物、随归档迁移、无 STATE.md 运行时写放大）。id/name 关系定调：英文名 = id（一切输入与寻址），中文标题 = name（纯展示，仅名称搜索命中这一处匹配例外）。YAML 书写用 plain scalar，起草纪律禁半角冒号 / 引号开头等易碎形态。
- **D2 读侧单点 `read_spec_title`**：落 `core/dashboard/data/spec_docs.py`（title 是 dashboard 读侧展示字段，与 `resolve_spec_dir` 同居一处即可复用归档回退语义，不必下沉到 daemon 派发路径共用的 `spec_mode.py`）。语义对齐 `read_spec_mode`：字段缺失 / 文件缺失 / 解析失败 / 非法 spec 名 → None，不抛异常；签名缓存同款 `(path, mtime_ns, size)` 有界缓存。
- **D3 归档读取性能**：`spec_summary` 的归档条目 title 读取不逐 spec glob——SummaryIndex 每轮重建时单次 `os.scandir(spec/archive/)` 建立名称→目录映射（剥日期前缀，同层多命中取 exact 优先 + `sorted()[-1]`，语义对齐 `resolve_spec_dir`）下发；活跃条目直读 `spec/changes/<spec>/.spec.yaml`（stat + 缓存命中零 glob）。非索引路径（详情页等）直接复用 `resolve_spec_dir`（低频调用，不值得加映射参数）。
- **D4 API 形状**：`spec_summary` 与 `spec_detail` 各透传 `"title": str | None`；前端 `SpecSummary` 加 `title?: string | null`。增量 patch（SSE watcher）随 summary 重建自动携带，无独立通道。
- **D5 UI 副标题形态**：v1 名称列主行（既有链接/字号/色不动）下方一行次级文本（12px、tertiary 色、单行省略），随树形缩进；移动端卡片名称区同规则。v2 用 `V2_TEXT_TERTIARY` 同级 token。两处缺失均不渲染副标题行（v2「缺口字段不伪装」惯例的自然延伸：缺失 = 无该行，而非「—」占位）。搜索：v1 关键字过滤在英文名包含匹配外 OR 命中 title（大小写不敏感）；排序键仍为英文名。
- **D6 生成通道**：fenix-new §2 增补「同阶段生成 5-25 字中文标题」+ `.spec.yaml` title 写入脚本示例（与 §3.1.1 mode 写入同模式），`--modify` 语义=可更新不强制；`evolution.py` 草稿契约加可选 `title_cn`，`SPEC_YAML_TEMPLATE` 带 title 占位（缺失时该行省略、草稿不作废——容错缺省对齐读侧）；`agents/evolution.md` spec 契约节与格式合规清单同步。code-fix 通道非目标（proposal 已声明）。
- **D7 回填策略**：全量 536 目录（496 modify + 40 new：活跃 2 + 归档 38 缺 `.spec.yaml` 按脚手架补写，`created` 取 STATE/归档清单条目日期；本 SPEC 自身 `.spec.yaml` 含于活跃 modify，由活跃批一并回填，保证任务 4.6 全量自检可达）。分批任务（活跃批 + 归档三批）保证 run 预算耗尽后可续做；每批幂等（已有非空 title 跳过）。清单冻结于立项时刻，实现期漂移由盘点任务修正 Deliverables 段 + 收尾增量回扫兜底。归档标题起草只读 proposal/design 头部（Why 段优先），控制每条目读取成本。

## Risks

- **实现窗口漂移**（活跃→归档迁移 / 新建 spec 无标题）：缓解 = 任务 4.1 盘点修正 + 任务 4.6 增量回扫；残余缺口列表不渲染副标题、零破坏。
- **run 预算**（535 目录逐个起草）：缓解 = 分批任务跨 run 续做（勾选状态持久）；每条目只读文档头部。
- **标题质量**（归档 spec 上下文少 / 4 目录无 proposal）：缓解 = Why 段优先、design/tasks 兜底、纯名称语义起草兜底；5-25 字纪律统一收口。
- **YAML 易碎形态**：缓解 = 起草纪律禁特殊字符；读侧容错（解析失败 → None → 不渲染）保证最坏情况仅副标题缺席。
