## Context

总设计文档：`docs/superpowers/specs/2026-11-03-knowledge-consumption-form-design.md`
（本 SPEC = 其中 SPEC A，内容层）。已取证事实：

- `spec/knowledge/` 851 个文件全部 git 跟踪，worktree 车道可直接读取。
- `agents/` 是 prompt 唯一真相（`prompt_builder.agent_prompt_path` +
  独立构建车道 `_load_agent_template` 双路径加载），纪律行写进 `.md` 即全车道生效，
  零新代码路径。
- 三跳下钻链已存在：`spec/knowledge/index.md`（44 行，29 域）→
  `domains/<域>/_domain.md`（能力清单 + 一行简介）→ 能力页（≤150 行，marker 机器接口）。
- 现状 `index.md` 域级简介过薄（如「缺陷修复」仅一句话），agent 判断「任务涉及哪个域」
  信息量不足。

## Goals / Non-Goals

**Goals:**

- daemon 消费车道与交互会话（Claude Code）都有 index-first 指路，接任务先查知识索引。
- `index.md` 简介增厚到可独立支撑「任务 ↔ 域」判断。
- 零代码改动，纯提示词/文档内容交付。

**Non-Goals:**

- 不做派发时动态知识注入（用户定调：知识量太大，注入不可行）。
- 不迁移 auto-memory（由 SPEC B 候选区管道承担隐性知识回填）。
- 不引入项目级配置键（fenixd 不做项目级特殊处理）。
- 不改 `index.md` 的结构（域行/能力数量列保持），只增厚简介列。

## Decisions

- **D1 静态纪律行（用户定调）**：`agents/*.md` 静态文本承担消费契约，不用注入。
  备选「prompt_builder 按需注入」被否：851 页知识按任务挑选注入需要映射机制且每次
  派发都有 token 开销，静态纪律 + agent 自判下钻深浅更便宜且足够。
- **力度 = 条件 MUST**：读 index 是硬纪律（44 行成本低、全任务一致），下钻以「命中
  相关域」为条件——未命中可跳过，禁止为走流程全量阅读（反目标：token 开销失控）。
- **作用域 = 全局 + 存在性条件**：`agents/` 是框架级文件，纪律行对 daemon 全部项目
  生效；文案写明「项目尚无 `spec/knowledge/` 时静默跳过」。备选「按项目门控」被否：
  需新配置键（须配 Dashboard 界面）且与「fenixd 不做项目级特殊处理」相抵。
- **拟覆盖车道**：`planner-plan`（立项前查相关域避免重复立项）、`implementer`
  （实现前查能力页拿当前规则）、`code-fix`（修复前查车道既有规则防重复踩坑）、
  `administrator`（排查告警先查域知识）、`self-review`（自省起草 todo 时对账已有
  能力）、`arbiter`（仲裁前查相关域规则）。builder 实现时可按「该车道是否做需要
  背景知识的判断」增删，但增删必须在收工报告里列明理由。
- **分车道措辞**：基准文案一致，按车道职责微调一句话（如 implementer 强调
  「动手前查该模块能力页的当前规则」），语义不得偏离条件 MUST 框架。

## Risks / Trade-offs

- [纪律行走形式化：agent 为 compliance 全量阅读知识页] → 文案显式写「未命中可跳过，
  不得为走流程而全量阅读」；index 保持 44 行精瘦。
- [CLAUDE.md 指路引用 `_inbox/` 但目录尚不存在（B 未落地）] → 文案标注该目录由后续
  SPEC 提供；存在性条件语义同样适用于投递纪律（目录不存在则不投递）。
- [index 简介增厚后文件变长（29 域 × 2~3 句）] → 仍约 80~100 行，远低于
  LLMWiki 单文件索引的合理规模；增厚素材取自 `_domain.md` 既有简介，不引入新事实。
- [skill 文件与 `~/.claude/skills` symlink 双实体不同步] → 只改仓内
  `skills/<name>/SKILL.md` 实体（symlink 反查已确认实体在仓内）。

## Migration Plan

纯内容层改动，随 SPEC 合并自然生效；无需迁移与回滚预案（revert 合并提交即回滚）。
daemon 侧无需重启（prompt 每次派发现读；dashboard 旧标签页不受影响）。
