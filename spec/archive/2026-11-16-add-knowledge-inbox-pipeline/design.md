## Context

总设计文档：`docs/superpowers/specs/2026-11-03-knowledge-consumption-form-design.md`
（本 SPEC = 其中 SPEC B，daemon 代码层）。构建者检查已证实的底盘事实：

- `spec/knowledge/` 851 文件全部 git 跟踪；distill 车道主树直跑，折叠可直接看到
  交互会话投递的 `_inbox/`，无 worktree 时滞。
- `validate_knowledge` / knowledge_audit 的扫描范围仅覆盖 `index.md` + `domains/`
  （`adr/` 仅部分检查），`_inbox/` 天然在体外——但必须补显式排除 + 测试钉死，
  防未来扫描范围变更时误伤。
- `rewrite_source_links_to_archive`（`core/knowledge.py:670`）当前对
  `spec/knowledge/` 下全部 `*.md` 改写 `spec/changes/<名>` → `spec/archive/<date-名>`。
- distill 铁律「sources 路径逐一真实存在」是机器检查项；现行 sources 仅接受
  `spec/changes/<SPEC名>` 与 `spec/archive/<date-名>` 两态目录形态（origin 分支校验），
  无 file 形态。
- distill 触发点：SPEC push 终态；队列台账单写者见 ADR-234
  （`backfill-distill-queue-ledger-registration-single-writer`）。

## Goals / Non-Goals

**Goals:**

- 交互会话结论有仓内回流管道：投递（自由格式）→ daemon 折叠（契约执行收敛一处）。
- 知识车道 prompt 归位 `agents/` 统一管理；补 `log.md` 编年账；候选原文与编年账免于
  归档路径静默改写。
- 积压可见性：dashboard 计数 + log 行，不发人工告警。

**Non-Goals:**

- 不做 fold-only 独立派发形态（用户定调 D6：piggyback-only，安静周滞留为设计内行为）。
- 不做存量 memory 自动迁移（用户定调 D5：管道落地后由交互会话渐进预筛投递，进度挂
  `todo.txt` 台账，不入本 SPEC 验收）。
- 不改 knowledge_audit 既有 lint 规则语义（只加积压提醒与 `_inbox` 豁免）。
- 不改 distill 的 SPEC 主输入源与既有触发点。

## Decisions

- **折叠触发 = piggyback-only（D6，用户定调）**：distill 每轮入口先消化 `_inbox/`
  存量，再处理当轮 SPEC 蒸馏；`_inbox` 非空不构成独立派发条件。备选「fold-only
  独立 run 形态」被否：要动派发语义且新增 run 形态，回归面大；安静周滞留以 audit
  提醒兜底可见性。
- **marker sources 扩展 = 方案 (a)**：折叠成功后条目移 `spec/knowledge/_inbox/done/`
  永久保留，能力页 marker sources 允许指向 `_inbox/done/<文件名>`（file 形态，
  机器校验对该前缀放行且校验文件存在）。备选「免 sources 白名单」被否：溯源机器
  不可校验，候选原文不可考。
- **归档改写豁免**：`rewrite_source_links_to_archive` 显式排除 `log.md` 与
  `_inbox/**`（含 `done/`）——「候选原文永久可考」要求逐字节冻结；接受原文中指向
  已消失 `spec/changes/` 路径的历史形态文本（静默改写才是真违背承诺）。
- **提醒面（2026-11-03 裁决）**：不走 AdminStore 人工告警（人工告警降噪偏好），
  落 `log.md` lint 行 + dashboard KnowledgeTab 积压计数；阈值＝积压 ≥10 条或最老
  条目滞留 ≥7 天（条目 mtime 计滞留），随 audit 周期轮幂等去重（同轮不重复落行）。
- **时间基准（2026-11-03 裁决）**：`log.md` 行前缀随真相源人类可读惯例走本地时区
  `UTC+8` 显式标注（同能力页盖戳形态）；运行时链路仍全链 UTC 不变。
- **prompt 迁移形态**：`core/knowledge_prompts/{distill,audit,backfill,prehistoric}.md`
  → `agents/knowledge-{distill,audit,backfill,prehistoric}.md` 平铺（与既有
  `agents/*.md` 命名一致，加载器无需子目录支持）；知识车道加载点从
  `core/knowledge_prompts/` 路径改为 `agents/` 路径；迁移后旧目录删除、全仓 grep
  无残留。备选「`agents/knowledge/` 子目录」被否：平铺改动面最小。

## Risks / Trade-offs

- [折叠失败条目滞留 `_inbox/` 原地] → 滞留条目保留原地（不丢弃），下轮重试；
  audit 提醒阈值对滞留条目生效；README 写明失败语义。
- [折叠时能力页超 150 行硬顶] → distill 铁律既有拆页机制（主从分片互链）适用，
  Scenario 覆盖。
- [piggyback 折叠拉长 distill 轮时长] → 折叠段在蒸馏段之前执行，单轮 inbox 存量
  通常少量（交互会话渐进投递）；`_inbox` 大批量积压时折叠按条目顺序消化、单轮
  不设上限但每条独立提交可中断。
- [distill 与 audit 并发追加 `log.md`] → 追加走文件锁或复用队列单写者纪律
  （ADR-234 同源），builder 实现时定，测试覆盖并发追加不丢行。
- [审计误报 `_inbox` 契约违规] → 显式豁免 + 测试钉死（扫描范围断言）。
- [daemon 交付后旧进程仍从旧路径加载 prompt] → 交付物含 `restart_request`
  （根路径 JSON：reason/origin/date）并冒烟预演；实际重启由 supervisor 消费。

## Migration Plan

1. SPEC 合并后 supervisor 重启 daemon（经 restart_request 信号），新进程从 `agents/`
   加载知识车道 prompt。
2. `_inbox/` 随本 SPEC 入库（含 README），交互会话即可开始投递。
3. 存量 memory 消化为管道外渐进活动（D5）：交互会话按价值预筛分批投递，进度挂
   `todo.txt`，不设机械终态。
4. 回滚：revert 合并提交 + `core/knowledge_prompts/` 目录随 revert 恢复，
   `_inbox/` 已投递条目人工抢救（文件仍在主树，无数据丢失面）。
