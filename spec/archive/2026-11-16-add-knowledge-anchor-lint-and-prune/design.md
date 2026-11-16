## Context

知识真相源是全任务 index-first 第一读，但对 agent 定位实现零帮助：能力页只写规则，
实现位置靠试错 grep（2026-11-07 v2 退役排查实测 15 次调用）。同时退役能力堆积：
amis 壳时代 5 个能力页仍带墓碑注记占位、ADR-033/038/039/327/328 五条仍 accepted
（其中 327/328 主体 2026-11-07 已退役）、部分域 index 简介超契约 2~3 句口径。
校验器现状：`core/knowledge.py::validate_knowledge` 已有溯源悬空/ADR 病灶等机械校验，
`_ADR_STATUS_RE`（:179）机械强制 `accepted|superseded` 二值——retired 语义无合法通道。

## Goals

1. agent 定位实现从「试错 grep 5-15 次」降到「读锚点段 0-1 次」。
2. 真相源不再堆积退役能力；退役动作有 runbook 可照单执行。
3. 锚点腐化被机械检查暴露，agent 才敢信任锚点。

## Decisions

- **D1 锚点段只校验段内**：锚点存活检查只扫能力页 `## 代码锚点` 段内的路径 token，
  不做全页启发式——精确、零误报、无排除名单负担；`spec/archive/`、`_inbox/`、
  `node_modules/` 路径跳过（历史/候选区不受锚点纪律约束）。
- **D2 悬空不机械自删、不入 validate_knowledge 硬门**：独立函数
  `check_anchor_references(project_root) -> list` 供 audit 车道消费（病灶⑥），
  报告计数进体检报告「待人工/定向转写」档。理由：锚点修复需语义判断（新位置），
  自删丢信息；不进 validate_knowledge 是防一处陈旧锚点硬阻塞全树折叠门
  （折叠前置校验跑全树，硬门会把内容问题放大成管线阻塞）。
- **D3 退役即删不墓碑**：推翻 v2-shell 五页「保留+退役注记」先例——墓碑页每次
  会话持续支付读取成本，规则已非现行（违背真相源契约「只装现在是什么规则」），
  追溯由 git 历史 + spec/archive + 域表尾一行退役注记承载。
- **D4 ADR `retired` 词汇表扩展**：`_ADR_STATUS_RE` 扩 `(accepted|superseded|retired)`；
  retired 语义=主体已从产品退役且无取代裁定（区别于 superseded 的「被新裁定推翻」）；
  合法形态=头部 `status: retired` + 追加 `Retired: <YYYY-MM-DD> <一句话>` 注记行
  （对齐 superseded 的 `Superseded by:` 行先例），三段正文逐字不可改写同 superseded
  纪律，`adr/index.md` 状态列同步。ADR-037 主体（worktree 测试服务）现役，保持 accepted。
- **D5 提示词面轻量接线**：`agents/knowledge-distill.md` 模板与
  `build_inbox_fold_prompt` 内联段各加一句「新建能力页必带代码锚点段（文件级路径，
  禁行号）」——契约页是规范源，提示词只是执行提醒，不复制契约全文。
- **D6 存量清理一次性做**：5 个 amis 壳页删除、五条 ADR 翻 retired、
  index.md 超标简介收缩到 2~3 句、dashboard-platform 域页落首个「症状速查」范例段。
  清理后 grep 复核无跨页能力名引用残留。
- **D7 零配置键**：锚点检查随 audit 车道既有 `knowledge.audit_enabled` 门控走，
  不新增配置键、不动 config.template。

## Risks

- 锚点腐化速度：文件移动会让锚点变陈旧——由病灶⑥每日体检兜底暴露（这是锚点制度
  成立的前提，不是残留风险）。
- retired 词汇扩展影响面：`_ADR_STATUS_RE` 同时被 ADR 病灶检查与（可能的）晋升/
  蒸馏校验引用，测试须覆盖三值 + retired 缺注记行报违规 + accepted/superseded 既有
  行为不回归。
- 存量清理误删：删除前必须 grep 五页能力名在其余知识页/ADR/提示词的引用并收口，
  防止悬空交叉引用。

## 界面原型

本 SPEC 无界面改动，不涉及原型环。
