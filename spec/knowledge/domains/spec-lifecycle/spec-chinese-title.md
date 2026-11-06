# SPEC 中文标题（display name）

<!-- knowledge: capability=spec-chinese-title rev=1
     sources=spec/changes/add-spec-chinese-title -->

SPEC 的人类可读展示名：立项双通道生成 5-25 字中文标题存入 `.spec.yaml`，与 kebab-case 英文名构成 name/id 关系，供列表页名称副标题展示与名称搜索命中。

## 规则

- **id/name 语义分离**：SPEC 英文名（kebab-case 目录名）= id，一切输入、寻址、排序、信号文件、STATE 条目、CLI/API 写入路径、fix-* 树构造与列排序以英文名为唯一键；中文标题 = name，纯展示，不进入任何寻址路径或匹配键。中文标题参与匹配的唯一例外：列表名称关键字过滤对标题做包含命中。
- **立项点双通道生成**：中文标题在立项点产生——/fenix-new 通道在 `fenix_spec.py new <name>` 之后、注册之前生成并写入；自进化通道草稿契约带可选 `title_cn` 字段，`materialize_draft` 落盘 `.spec.yaml` 时写为 `title` 行（schema/created/mode 之后）。两条通道均为 LLM 起草环节，生成纪律同源（`agents/evolution.md` 契约与 fenix-new skill 同要求）。
- **code-fix 通道不产生标题**：`core/code_review.py::generate_fix_spec` 为纯程序化模板生成（无 LLM 起草环节），不生成中文标题——此类 SPEC 无 title 属合法形态，走读侧容缺。
- **长度纪律只约束生成侧**：5-25 字是起草通道提示词层面的生成纪律；读侧与 API 不做长度校验，容错透传。
- **evo 容错缺省**：草稿 spec 契约缺 `title_cn` 或形态非法时，落盘不含 title 行、草稿不作废——与读侧缺省语义对齐。
- **`--modify` 更新语义**：经 /fenix-new `--modify` 更新既有 SPEC 时，标题可随需求演变同步更新；标题仍准确时保持不变，不强制改写。
- **存储单源 `.spec.yaml` `title` 字段**：与 `mode` 字段同位同模式（git 交付物、随 change 目录入库与归档迁移，无 STATE.md 运行时写放大）；YAML 书写用 plain scalar，起草纪律禁半角冒号、引号开头等易碎形态。
- **读侧单点 `read_spec_title`**：落 `core/dashboard/data/spec_docs.py`（dashboard 读侧展示字段，与 `resolve_spec_dir` 同居一处复用归档回退语义；不下沉 daemon 派发路径共用的 `spec_mode.py`）。语义对齐 `read_spec_mode`：字段缺失 / 文件缺失 / YAML 解析失败 / 非法 spec 名一律返回 None 不抛异常；签名缓存同款 `(path, mtime_ns, size)` 有界缓存。
- **活跃优先、归档回退**：活跃 SPEC 直读 `spec/changes/<spec>/.spec.yaml`；已迁出 SPEC 经归档目录解析回退读归档目录的 `.spec.yaml`（目录名 = 日期前缀 + spec 名 + 可选冲突后缀，同层多命中取 exact 优先）。
- **归档读取不做 per-spec glob**：归档条目的 title 由调用方每轮单次扫描 `spec/archive/` 建立名称→目录映射后下发（SummaryIndex 重建时建立，剥日期前缀）；活跃条目 stat + 签名缓存直读。低频非索引路径（详情页等）直接复用 `resolve_spec_dir`，不加映射参数（/api/specs 性能治理纪律）。
- **API 透传形状**：`/api/specs` 列表项与 `/api/specs/<spec>` 详情各含 `title` 字段（string | null，缺失为 null 且键不缺位）；增量 patch 随 summary 重建自动携带，无独立通道。
- **缺失容错渲染**：title 为 null/空时列表前端不渲染副标题行（缺失 = 无该行，不渲染「—」占位），其余字段与行为不变——读侧最坏退化即副标题缺席。
- **存量回填幂等**：全量存量（活跃 + 归档）逐目录读取 proposal/design 起草回填；归档缺 `.spec.yaml` 的目录按脚手架约定补写（`schema: spec-driven` + `created` 取归档清单条目日期 + `title`）；已有非空 title 的文件跳过不覆盖、不重复追加 title 行；实现窗口内新建/新归档的缺标题目录由收尾增量回扫兜底纳入。

## 溯源

- 2026-11-06 add-spec-chinese-title（spec/changes/add-spec-chinese-title/） — 新建本页：立项双通道（fenix-new + evo title_cn）生成 5-25 字中文标题、`.spec.yaml` title 单源存储、read_spec_title 读侧单点（活跃优先归档回退 + 签名缓存 + SummaryIndex 归档映射不做 per-spec glob）、/api/specs 与详情透传、存量全量幂等回填；id/name 语义分离定调见 ADR-330
