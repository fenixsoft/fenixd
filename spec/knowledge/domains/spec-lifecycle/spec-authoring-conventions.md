<!-- knowledge: capability=spec-authoring-conventions rev=1
     sources=spec/knowledge/_inbox/done/memory-distill-user-rulings.md -->

# SPEC 立项与成文定调

交互会话与 agent 起草立项时的用户定调口径：创意需求的入口路径、SPEC 歧义的解释单源与配置类需求的内容底线。

## 规则

- 立项入口走设计定稿前置：创意/设计类需求先经 brainstorming 产出设计文档并定稿，落 `docs/superpowers/specs/YYYY-MM-DD-<topic>-design.md`；定稿后转 fenix-new 立项交框架实现。设计定稿环节不进 writing-plans 流程——设计文档不是实现计划，二者是先后两段，不由同一载体承担。
- Scenario 优过正文：SPEC 的数值/分支歧义以实现满足 `specs/<capability>/spec.md` 的 Scenario 块为准，验收与全量 verifier 校验场景而非正文措辞；正文与场景冲突时按场景执行。
- 配置项必须带设置界面：凡新增 fenixd 配置项的需求，SPEC 必须同步包含 Dashboard 设置界面的编辑能力，不允许只落 config.yaml 的纯配置交付（配置能力与 UI 能力同步存在）。

## 溯源

- 2026-11-04 memory-distill-user-rulings（spec/knowledge/_inbox/done/memory-distill-user-rulings.md） — 新建本页：折叠三条用户定调（brainstorming 设计定稿→fenix-new 立项流程、Scenario 优过正文、配置项必须同步设置界面）
