# 能力退役 runbook

<!-- knowledge: capability=knowledge-retirement-runbook rev=1
     sources=spec/changes/add-knowledge-anchor-lint-and-prune -->

能力（含其代码）从产品整体删除时的标准操作序列：接到「退役能力 X」任务照单执行，无需会话内重新发明步骤。

## 规则

- 适用前提：能力主体（代码、路由、入口）已确定整体删除且无后继取代裁定；有后继裁定时走 supersede（ADR 只标不改）而非 retired——retired 语义=主体已从产品退役且无取代裁定，区别于 superseded 的「被新裁定推翻」。
- 前置盘点：grep 该能力的 capability 名（页文件名去 `.md`）与相关 ADR 编号在全库（`spec/knowledge/`、`agents/` 提示词、`tests/`、`docs/help/`）的引用并列清单备收口——删除动作会制造悬空交叉引用，先摸清引用面再动手。
- checklist（顺序执行，同一批次提交）：
  1. **代码与路由删除**：删除产品代码（路由/端点/组件/服务），同步清理死代码与仅该能力消费的辅助模块；测试侧删除该能力专属测试，保留语义仍成立的通用测试。
  2. **镜像/同步指令收口**：其余知识页规则段中「镜像 X 两处同改」「与 X 保持同步」类指令，主语被删时同批改写为历史出处口径或移除——现行规则段 MUST NOT 携带指向已删除文件/域的现行口径引用。
  3. **知识页删除**：删除该能力的能力页（直接删不墓碑——墓碑页每次会话持续支付读取成本，历史由 git 历史 + `spec/archive/` 承载）；主从分片页全部分片同删。
  4. **域表收口**：所在域 `_domain.md` 移除表行、刷新盖戳行与该行更新时间；表尾追加一行退役注记（唯一墓碑形态）：`> 退役：<YYYY-MM-DD> <能力名>（原 <页文件名>）已随 <SPEC 名> 删除，历史见 spec/archive/<目录> 或 git 历史`。
  5. **ADR 翻转**：该能力的 accepted ADR 头部翻 `status: retired` 并追加 `Retired: <YYYY-MM-DD> <一句话>` 注记行（置于头部段；三段正文逐字不动——不可变比对只看 `## Context` 之后正文）；`adr/index.md` 状态列同步为 retired。校验器强制 retired 条目带日期锚定注记行，缺失报违规。
  6. **index 计数**：`index.md` 该域行能力数量同步（删页 -1、新页 +1），刷新盖戳行与该行更新时间；简介仍覆盖剩余能力面时不动。
  7. **log 登记**：`log.md` 编年账追加一行登记本次退役批（删了哪些页、翻了哪些 ADR、计数同步），履行退役即删语义的同批 log 义务。
  8. **复核 grep**：重跑前置盘点的 grep，确认全库零悬空引用残留（历史溯源行的纯文本提及不算残留）；其余能力页代码锚点段内指向被删文件的锚点按 `check_anchor_references` 口径会进下一轮体检病灶⑥，同批收口或接受待处置登记。
- 机械校验面：retired ADR 由 `validate_knowledge` 放行（注记行齐备）与拦截（缺注记行）；退役造成的锚点悬空由 audit 病灶⑥暴露（进待人工/定向转写档），不阻塞折叠硬门；世代前缀命名禁令（`v2-`/`v3-` 式）无机械校验，蒸馏车道复核与 spec 评审判。

## 代码锚点

- 单源符号：`core/knowledge.py:_RETIRED_NOTE_RE`
- 守卫测试：`tests/test_knowledge_anchor_check.py`

## 溯源

- 2026-11-08 add-knowledge-anchor-lint-and-prune（spec/changes/add-knowledge-anchor-lint-and-prune/） — 新建本能力页：退役即删不墓碑语义的完整操作序列（前置盘点、八步 checklist、机械校验面边界）
