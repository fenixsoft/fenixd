## Why

知识真相源是所有任务的 index-first 第一读，但当前形态对 agent 提效不足：能力页只写规则不写代码位置，agent 定位实现要试错式 grep 5-15 次（2026-11-07 v2 退役排查实测）；退役能力的页与 ADR 仍堆在真相源里（amis 壳时代 5 页 + 3 条 accepted ADR），每次会话持续支付读取成本且误导定位。本 SPEC 从「加速 agent 理解与解题」出发，给真相源补「该记的」（代码锚点）、删「不该记的」（退役堆积），并用机械校验防腐。

## What Changes

- 能力页契约新增可选「代码锚点」段：主实现文件 / 单源符号 / 消费方 / 守卫测试，文件级粒度（禁行号）；新增能力页强制带锚点，存量按触达增量补，本 SPEC 先落 3 页范例。
- `validate_knowledge` 新增锚点存活检查（第六类病灶）：只校验「代码锚点」段内路径的盘上存在性，悬空进体检报告待处置，不机械自删（修复需语义判断，走定向转写/人工）。
- 退役语义收紧：能力主体删除时其能力页**直接删除不墓碑**（历史由 git + spec/archive 承载），`_domain.md` 表尾一行退役注记；同批翻转相关 ADR status 为 retired；新能力页禁世代前缀命名（v2-/v3- 之乱定约）。
- 退役 runbook 成页（knowledge-atlas 域）：退役一个能力的完整 checklist（删页/删路由/死代码/镜像指令收口/知识页/ADR/导航计数/log 登记）。
- 存量清理：dashboard-platform 域 5 个 amis 壳退役页删除 + 域表收口 + 域页「症状速查」范例段；ADR-033/038/039 翻 retired（ADR-037 主体仍现役保持 accepted）；index.md 超标域行简介收缩到契约 2~3 句口径。

## Capabilities

### New Capabilities

- `knowledge-anchor-discipline`: 代码锚点段契约与存活检查、退役即删不墓碑语义、退役 runbook、命名与死引用纪律——能力页「写什么/不写什么」的提效纪律全集

### Modified Capabilities

- `knowledge-atlas-directory`: 目录契约增补——能力页可选「代码锚点」段与域页可选「症状速查」段的契约形态；退役语义（删除不墓碑）入目录结构规则；锚点段纳入 marker 之外的机器校验面
- `knowledge-audit`: 体检病灶族新增第六类「锚点悬空」（仅校验代码锚点段、进报告待处置、不机械自删）；病灶计数与报告形态随之扩展

## Impact

- 代码：`core/knowledge.py`（validate_knowledge 增锚点检查）、`tests/test_knowledge_anchor_check.py`（新增测试）
- 真相源内容：`spec/knowledge/` 下约 15 个文件（契约页 2、runbook 新页 1、dashboard-platform 清理 7、ADR 4、index 1、范例锚点页 3）
- 蒸馏/audit 车道：新折叠页强制带锚点（提示词契约面 `build_distill_prompt`/`build_inbox_fold_prompt` 是否需同步措辞由 design 决定）；audit 报告多一类病灶计数
- 无 API/前端/配置键变更
