# Design: add-knowledge-atlas-maintenance —— 存量回填与持续维护

## Context

前置 SPEC `add-knowledge-atlas` 落地了真相源机制（目录契约、`core/knowledge.py` 的 validate_knowledge/dispatch_distill、归档触发蒸馏管线、ADR 索引、KnowledgeTab 渲染位、`knowledge.enabled` 配置）。本 SPEC 处理三个遗留面：存量 300 个归档不回流（蒸馏只挂归档动作）、无持续淘汰纠错、无关系图。

既有机制锚点：
- 批处理先例：code-fix 亲和性分批（文件组不可拆 + 波次自适应 + 断点台账）；其教训直接复用——批次规模上限、failed 不阻塞后续、进度落运行时台账。
- 周期调度先例：自省调度自然日 + 增量窗口（24h 滚动有漂移缺陷已定案）；daemon 主循环 300s 周期检查模式（自动归档 D4 同款）。
- 前端零改动：KnowledgeTab 的 graph 探测接口（`/api/knowledge/graph` 404 占位语义）已就绪，graph.html 一旦落盘自动点亮。
- fail-open 家族：archive_commit、蒸馏派发均已 fail-open；graphify 生成延续同一哲学。

## Goals / Non-Goals

**Goals**
- 300 个存量归档分批回填，产出与增量蒸馏同标准的真相源
- 每日 audit 体检五类病灶，机械自修 + 语义转写分级处置，真相源不膨胀
- 每日 Graphify 生成关系图，fail-open 降级
- 新配置项带设置页

**Non-Goals**
- 修改目录契约/marker 格式（前置 SPEC 定稿）
- KnowledgeTab 前端改动（零改动）
- Graphify 产物的深度定制（用其默认输出；GRAPH_REPORT.md 直接入库不二次加工）

## Decisions

### D1: 回填 = 台账驱动的批处理车道，与增量蒸馏共用提示词与校验器

`core/knowledge_backfill.py` 维护进度台账（`.fenix/knowledge_backfill.jsonl`，每归档一行：name/status/batch/updated_at）。调度分两段：首段「聚类自举 run」（一个 agent run 读全部归档的 specs/ 目录名 + proposal 标题，产出域清单与 `index.md`/`_domain.md` 骨架）；第二段按域分批派发蒸馏 run（复用 `core/knowledge_prompts/distill.md` 契约 + 附加「批量模式」段：一次处理本批全部归档、逐归档应用 ADDED/MODIFIED 语义）。每批落盘前跑 validate_knowledge（同一标准零豁免），通过后 pathspec 限定提交。批规模 ≤20（code-fix 亲和性教训：批次过大重做代价指数化）；failed 批标 failed 登 todo.md，不阻塞后续批。车道幂等：全部条目终态后重入只处理新 pending。

### D2: audit = 确定性扫描器 + 定向转写 run 两级

`core/knowledge_audit.py` 每日跑（挂 daemon 主循环自然日检查，与自动归档同款挂载模式）：第一级纯脚本扫描五类病灶中的机械可判项（悬空链接、行数硬顶、ADR diff/链断裂、格式）→ 可自动修的直修直提交；第二级矛盾/重复检测（同主题词跨页比对，脚本初筛）→ 命中转定向蒸馏 run（`core/knowledge_prompts/audit.md` 提示词：给两处冲突上下文，按增量蒸馏契约重写受影响页）。初筛宁松勿紧（误报进 run 由 LLM 终判，漏报下轮再来）。体检报告落 `.fenix/knowledge_audit_report.md`（运行时），规模趋势超 +10% 显式标「需精简」。

### D3: Graphify 生成 = daemon 后台线程直跑 CLI，产物入库

安装采用 vendored 判定（对齐 archify vendored 教训——运行时安装会超时）：文档声明 graphify 为可选外部依赖（`uv tool install graphifyy` 人工一次性，README 写步骤），daemon 侧 `shutil.which('graphify')` 探测，缺失 fail-open 跳过。每日窗口与 audit 共用计时器（一个自然日检查点先后跑 audit 与 graph，减少唤醒）。生成命令对 `spec/knowledge/` 执行，产物入 `graph/`，pathspec 限定提交。`knowledge.graph_enabled` 门控。图语义通道的 LLM pass 用 graphify 自身配置（其 CLI 独立于 fenixd agent 网关，不横加干预）。

### D4: 配置项 knowledge.audit_enabled / knowledge.graph_enabled

两 bool 默认 true，进 `core/config.py` 解析（非法值回退默认并告警）、`.fenix/config.template.yaml` 登记、设置页控件（新增配置项必须带 Dashboard 界面铁律）。热更新沿用 30s mtime 机制。

## Risks / Trade-offs

- **回填 token 成本**：300 归档 × 批 ≤20 ≈ 15+ 个蒸馏 run。缓解：批处理断点续跑、failed 不重做整批（只重做失败条目）、提示词复用增量契约零额外设计。
- **audit 初筛误报**：脚本初筛松判定会把非矛盾对送进转写 run。缓解：LLM 终判可直接判「无矛盾」零改动收场；误报成本一个 run，可接受。
- **graphify 产物不稳定**：其版本升级可能改 graph.html 结构。缓解：产物整体入库按提交回溯，前端 iframe 内嵌不解析其内部结构（零耦合）。
- **daemon 重启生效**：新增周期挂载点需重启 daemon（既有后端约定）。

## Migration Plan

- 本 SPEC 合并并手工激活后：自动回填车道首跑完成域自举 + 批量回填；期间增量蒸馏（归档触发）照常运行，两者写同一真相源——并发写由 validate_knowledge + pathspec 提交保证原子（页级冲突以先提交者为准，后者 run 读到新版自然叠加，合同语义无脏写窗口）。
- graphify 安装为人工一次性步骤（README 人工步骤节），未安装期间功能降级不阻塞。

## Open Questions

- 回填期间若用户并发归档新 SPEC：增量蒸馏与回填批可能同时改同一能力页。当前以「先提交者胜、后跑者基于新版重写」为契约（蒸馏 run 启动时重读现网真相源）。若实测出现高频率撞车，再升级为页级文件锁（本期不做，避免过度设计）。
