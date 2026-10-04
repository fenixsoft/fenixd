# Design: add-knowledge-atlas —— 项目知识真相源机制

## Context

`spec/archive/` 已积累 300 个归档 SPEC。存量归档实测（2026-09-27）：300 个中 262 个自带 `specs/<capability>/spec.md`（`## ADDED Requirements` delta）与 `design.md`（`## Decisions` D1-D6 标准段）、296 个有 `proposal.md`；约 38 个早期 `fix-*` 归档缺 design.md/specs delta——蒸馏提示词须含原料缺失降级分支（见 D2），不得假设原料完备；同一能力被多个 SPEC 先后修改（dashboard-spec-table ×6、scheduled-spec-pickup ×5），证明「当前规则」必须是合并语义的产物而非归档平铺。openspec 的平铺主 spec 方案被否决（不可读且无溯源）；本设计采用「域 → 能力 → 页」分层真相源 + 溯源链接回指归档。

既有机制锚点：
- 归档双路径——手工 `.fenix/bin/fenix_archive.py::archive_change` 与 tracked 侧 `core/dashboard/data/spec_archive.py::archive_spec`（daemon 自动归档 `auto_archive_check` 300s 周期调用）——**均漏斗经过 `core/archive_commit.py::commit_archive_move`**（移动成功后调用，fail-open 哲学已有先例）。
- Dashboard 路由为 Mixin 模式（`core/dashboard/routes/architecture_routes.py` 先例：status/refresh/diagram 三端点）；前端页签在 `pages/projects/list.tsx`（架构页签 `ArchitectureTab` 的 active 门控按需拉取是同构先例）。
- `.fenix/bin/*` 为 gitignored 运行时文件（`.fenix/*` 忽略 + 白名单放行 todo/verify.yaml/config.template.yaml），**不能作为 SPEC 交付物**——手工归档路径的蒸馏挂载必须落在 tracked 侧。

## Goals / Non-Goals

**Goals**
- 真相源目录契约（含机器 marker）落地 `spec/knowledge/`
- 归档触发蒸馏管线：单点挂载、双路径生效、fail-open、确定性收尾校验 + 自动提交
- ADR 索引：跨 SPEC 架构级判据、三段式、supersede 不改写
- 「项目知识」页签（「会话接入」之前，按需加载）
- `knowledge.enabled` 配置 + 设置页

**Non-Goals**
- 存量 300 个归档的批量回填（后续 SPEC `add-knowledge-atlas-maintenance`）
- 周期 audit 淘汰车道（同上）
- Graphify 关系图生成（同上；本 SPEC 只留前端渲染位）
- 校验蒸馏散文的语义质量（校验脚本只对账格式与链接；语义质量靠 prompt 约束与后续 audit，见 Risks）

## Decisions

### D1: 目录契约——HTML 注释 marker 作机器接口，散文作人类接口

`spec/knowledge/domains/<域>/<能力>.md` 单能力单页；marker 用 HTML 注释（`<!-- knowledge: capability=... rev=... sources=... -->`）人读时隐形、脚本可解析——对齐 blueprint-index 的「banner 给人看、marker 给门禁读」分离原则。能力域由蒸馏 agent 自动聚类（用户已定），不预置人工清单；`_domain.md` 与 `index.md` 是导航层，由蒸馏 run 维护。单页 150 行硬顶是防膨胀物理约束，超顶强制拆页或精简（校验脚本拦截，拒绝落盘）。

### D2: 蒸馏 run = 主树直跑的 claude -p 后台任务，机器对账 + 机器提交

蒸馏是 LLM 任务（散文重写无可替代），但 git 操作与格式对账不进 agent：
- daemon 派发 `claude -p` 后台 run（cwd 主树，提示词含目录契约、合并语义 ADDED/MODIFIED/REMOVED、风格禁令——禁历史叙述措辞、ADR 判据），run 直接写 `spec/knowledge/` 草稿；
- run 结束后 daemon 侧执行**确定性校验脚本**（`core/knowledge.py::validate_knowledge`）：marker 可解析、sources 指向的归档目录存在、单页 ≤150 行、index/_domain 链接可解析；违规反馈给 run 修正（≤2 轮），仍违规则放弃本次产出——run 直写主树，放弃时 daemon 侧 MUST `git restore -- spec/knowledge/` 并清理该目录下未跟踪新增（不留半成品）；
- **单飞约束**：同 project 同时至多一个蒸馏 run 在写 `spec/knowledge/`，并发归档事件排队串行或合并为一次批量 run，避免并发写与并发 `git commit` 撞 index.lock；
- **原料缺失降级**：归档无 `design.md` → 跳过 ADR 抽取；无 `specs/` delta → 按 proposal 摘要口径蒸馏能力页或留痕跳过，不判 run 失败（实测 300 存量归档中 38 个早期 `fix-*` 缺 design.md/specs delta）；
- 校验通过后由 daemon 侧自动提交（复用 `archive_commit` 模式的 fail-open 提交）。

与 fast-track 的 worktree-implementer 模式 deliberately 不同：真相源是 spec 元数据层（非产品代码），主树直跑避免 merge-back 复杂度；写路径限定 `spec/knowledge/` 一个目录，爆炸半径可控。提示词按 `agents.md` 文件化惯例落 `core/knowledge_prompts/distill.md`（契约段=动态段，改 prompt 先 merge main 的既有纪律适用）。

### D3: 触发点单点挂载在 commit_archive_move（tracked 共同漏斗）

手工路径（`.fenix/bin/fenix_archive.py`，gitignored 不可交付）与 daemon 路径（`spec_archive.archive_spec`）都已调用 `core/archive_commit.py::commit_archive_move`——在该函数移动成功分支追加 `dispatch_distill(project_root, archived_name)` 即同时覆盖双路径，无需触碰不可交付的运行时脚本。注意漏斗实际有**三个**调用方：手工归档、daemon `archive_spec`/`auto_archive_check`、软删除 `soft_delete_spec`（其删除动作同样是「移入 `spec/archive/<名>-<Unix秒>/` + commit_archive_move」，见 spec_archive.py::soft_delete_spec）——软删除路径触发蒸馏属预期行为：其归档目录同样落 `spec/archive/`，sources 存在性校验天然兼容。直接调用 `commit_archive_move` 的既有单测（tests/test_spec_archive.py）经 dispatch 注入替身隔离，不触发真实派发。fail-open：派发异常只记日志与重试台账，不影响归档返回值。重试台账复用既有 admin_alerts/todo.md 机制（首选取 todo.md 登记，给人看的队列，不进任务门禁）。`knowledge.enabled` 为 false 时 dispatch 直接返回。

### D4: ADR 判据进提示词、supersede 机制进脚本

「跨 SPEC 影响架构走向」是语义判断，归提示词裁定（给正反例：收录「车道隔离必须走 spawn 点注入」级机制选型；拒收单 SPEC 内布局/命名取舍；允许零产出）；supersede 的**机械部分**归脚本：新 ADR 头部 `Superseded by:` 指向存在的条目、旧条目 status 翻转、正文逐字未变（校验脚本 diff 旧正文）。编号 NNN 三位递增由脚本分配（避免 agent 并发撞号）。ADR 不可变性因此可机械保证：accepted 后正文有任何 diff 即违规。

### D5: 后端 Mixin 三端点 + 前端 KnowledgeTab 按需加载

`core/dashboard/routes/knowledge_routes.py`（H13 同款 Mixin，注册进 `server.py`）：
- `GET /api/knowledge/index?project=` → `spec/knowledge/index.md` 内容（含存在性探测：未初始化时返回占位结构）
- `GET /api/knowledge/file?project=&path=domains/<域>/<能力>.md|adr/ADR-NNN-*.md|adr/index.md` → 白名单前缀（`domains/`、`adr/`）内的文件内容，前缀外与 `..` 一律 400（路径穿越拒绝）
- `GET /api/knowledge/graph?project=` → `graph/graph.html` 存在性 + 内容（maintenance SPEC 落地前恒 404，前端显占位）

前端 `KnowledgeTab.tsx`：active 门控按需拉取（对齐 QualityTab/RegressionTab 先例）；Markdown 渲染复用既有 SpecDocModal/QualityTab 的 react-markdown 渲染链路（依赖已含 react-markdown ^10.1.0）；ADR 列表视图带状态标签（accepted 绿/superseded 灰 + 跳转）；graph 区 `<iframe>`/html 注入位 + 占位文案。页签插在「项目架构」与「会话接入」之间（用户指定「会话接入之前」）。

### D6: 配置项 knowledge.enabled + 设置页同步

`knowledge.enabled`（bool 默认 true）入 `core/config.py` 解析与 `config.template.yaml`（tracked）；Dashboard 设置页增控件与说明文案（「新增配置项必须带 Dashboard 界面」铁律）；30s mtime 热更新既有机制自动生效，禁用后归档照旧、蒸馏静默跳过、页签显禁用占位。

## Risks / Trade-offs

- **散文语义质量无法机械校验**：校验脚本拦格式不拦「写得烂」。缓解：提示词给风格正反例；后续 maintenance SPEC 的 audit 车道持续返工。这是接受的边界（blueprint-index 同样诚实声明 digest 属人审内容）。
- **蒸馏 run 与主树并发写**：主树可能堆有未提交决策（混合工作区常态）。蒸馏写路径限定 `spec/knowledge/`，提交用 pathspec 限文件（对齐「提交须 pathspec 限文件」纪律），不碰他物。
- **daemon 旧码陷阱**：管线为 daemon 侧新代码，需 daemon 重启生效（既有后端约定，README/帮助文档注明）。
- **首个蒸馏 run 的冷启动**：真相源为空时首个 run 需建目录骨架 + 自动聚类定域。提示词须含「首跑分支」指引；域命名用业务语言（中文短语 → kebab 目录名映射表由 run 自行产出并写入 README）。

## Migration Plan

- 无数据迁移。`spec/knowledge/` 全新目录，首跑自举。
- 上线后首个归档事件即产出第一批真相源页面（增量起点）；存量回填在后续 SPEC 用批处理车道补齐，两阶段互不阻塞。

## Open Questions

- 蒸馏 run 的 provider/模型走 agents 默认网关即可，还是登记专用角色（agents.models.knowledge-distiller）？（倾向：登记专用角色，复用未登记 agent 无回退的教训——立项即登记，零成本。机制锚点：`core/config.py` KNOWN_AGENT_TYPES + `agents.models.<role>` 校验，向 KNOWN_AGENT_TYPES 新增角色即同步放开 agents.models 与 timeout_overrides 同名键。）
