## Why

SPEC A（`add-knowledge-consumption-discipline`）打通消费后，生产侧仍有四个结构性缺口
（总设计：`docs/superpowers/specs/2026-11-03-knowledge-consumption-form-design.md`）：

1. 交互会话产出的排查/立项结论没有仓内回流管道——隐性知识锁死在 Claude Code
   auto-memory（`~/.claude/projects/` 私有目录），dsh 等其他 harness 与 daemon 车道
   均不可见，人类不可见，不进版本库。
2. 四个知识车道 prompt（`distill/audit/backfill/prehistoric`）放在
   `core/knowledge_prompts/`，游离于「`agents/` 是 prompt 唯一真相」体系之外，运作
   形式与其他 13 个车道不一致。
3. 无 `log.md` 编年账——蒸馏/折叠事件不可回溯、不可 grep。
4. `rewrite_source_links_to_archive` 对 `spec/knowledge/` 全量 `*.md` 做归档路径改写，
   未来引入的候选原文与编年账会被静默篡改。

## What Changes

- 新增 `spec/knowledge/_inbox/` 候选区：交互会话投递自由格式 markdown（只求讲清楚
  不求守能力页契约）；显式豁免于 validate/audit 扫描（测试钉死）。
- distill 车道 piggyback 折叠（用户定调 D6，不新增 fold-only 派发形态）：每轮先消化
  `_inbox/` 存量再蒸当轮 SPEC；折叠按能力页契约执行、超 150 行拆页、折叠前跑实时
  `validate_knowledge` 失败不落盘；成功条目移入 `_inbox/done/` 永久保留。
- marker sources 契约扩展：机器校验放行 `spec/knowledge/_inbox/done/` 前缀的
  sources（file 形态），候选原文永久可考（方案 a）。
- 新增 `spec/knowledge/log.md` 编年账：追加式，行前缀
  `## [YYYY-MM-DD HH:MM UTC+8] <操作> | <主题>`（操作 ∈ distill/fold/backfill/lint），
  时间基准随真相源人类可读惯例走本地时区（2026-11-03 裁决）。
- `rewrite_source_links_to_archive` 显式豁免 `log.md` 与 `_inbox/**`（含 `done/`），
  测试钉死。
- audit 周期轮积压提醒：阈值＝积压 ≥10 条或最老条目滞留 ≥7 天，落 `log.md` lint 行 +
  dashboard KnowledgeTab 积压计数；**不走 AdminStore 人工告警**（人工告警降噪偏好），
  随周期轮幂等去重。
- 四个知识车道 prompt 迁入 `agents/`（`knowledge-{distill,audit,backfill,prehistoric}.md`
  平铺），加载点同步改造，`core/knowledge_prompts/` 目录删除、全仓无残留引用。

## Capabilities

### New Capabilities

- `knowledge-inbox-pipeline`: 仓内候选区回填管道——`_inbox` 投递契约与扫描豁免、
  piggyback 折叠、marker sources 扩展、`log.md` 编年账、归档改写豁免、积压提醒、
  知识车道 prompt 归位 `agents/`。

### Modified Capabilities

（无——归档能力 `knowledge-distill-pipeline`/`knowledge-audit` 的既有需求不变，
prompt 存放路径是实现细节（归档 spec 未约束），折叠与提醒是其行为扩展，统一收进
新能力 `knowledge-inbox-pipeline` 描述。）

## Impact

- 代码：`core/knowledge.py`（扫描豁免/marker 校验/归档改写豁免）、
  `core/knowledge_audit.py`（积压提醒/log 行）、知识车道 prompt 加载点（随迁移改造）、
  `core/dashboard/routes/knowledge_routes.py` 与
  `core/dashboard/static/src/pages/projects/components/KnowledgeTab.tsx`（积压计数展示）。
- 提示词：`agents/knowledge-*.md`（新增 4 个）、`core/knowledge_prompts/`（删除 4 个）。
- 内容：`spec/knowledge/_inbox/README.md`（投递契约说明）。
- 行为影响：distill 车道每轮新增 inbox 折叠前置段；audit 轮新增积压检测；
  daemon 交付后需重启才能加载新 prompt 路径（restart_request 交付项）。
- 依赖：depends_on `add-knowledge-consumption-discipline`（SPEC A 的 CLAUDE.md 回填
  预告文案先落位，本 SPEC 落地真实目录与管道）。
