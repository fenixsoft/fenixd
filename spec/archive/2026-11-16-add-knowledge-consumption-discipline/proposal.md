## Why

知识真相源 `spec/knowledge/`（851 个 md）自 10-03 运转以来消费为零：`agents/` 全部 13 个
车道提示词没有任何指路文字，`prompt_builder` 无知识注入，交互会话的 `CLAUDE.md` 与
fenix skill 也不指路——蒸馏产物唯一读者是 dashboard 人类视角和知识车道自身（自产自销
闭环）。与此同时所有车道 agent 立项/实现/排查都从零搜索代码库，重复消耗大量 token。
本次取证（见 `docs/superpowers/specs/2026-11-03-knowledge-consumption-form-design.md`）
确认三跳下钻链（index → 域导航页 → 能力页）结构上已存在，缺的只是让 agent 走这条路的
纪律行本身。

## What Changes

- `agents/` 六个消费车道提示词（`planner-plan`、`implementer`、`code-fix`、
  `administrator`、`self-review`、`arbiter`）各增加知识纪律段：接任务先读
  `spec/knowledge/index.md`，命中相关域则 MUST 下钻域导航页与能力页；文案带存在性
  条件（项目无 `spec/knowledge/` 时静默跳过），分车道措辞微调。
- 项目 `CLAUDE.md` 增加同款消费指路 + 「值得沉淀的结论投递 `spec/knowledge/_inbox/`」
  回填纪律预告（目录由依赖 SPEC 创建，文案先行不碍事）。
- 仓内 `skills/fenix-new/SKILL.md` 与 `skills/fenix-process/SKILL.md` 增加立项/查进度
  前先查相关知识域的指路。
- `spec/knowledge/index.md` 域级简介增厚：每域简介从一句话扩为能独立支撑
  「任务 ↔ 域」判断的形态（素材取各域 `_domain.md` 能力清单），盖戳时间刷新。
- 纪律行为静态文本，零 daemon 代码改动；`agents/` 是框架级文件，纪律行对全部项目生效，
  靠存在性条件自然分层。

## Capabilities

### New Capabilities

- `knowledge-consumption-discipline`: 知识消费纪律——车道提示词/CLAUDE.md/skill 三面的
  index-first 指路契约、条件 MUST 力度、存在性条件语义、index 域级简介质量要求。

### Modified Capabilities

（无——归档能力 `knowledge-atlas-directory`/`knowledge-distill-pipeline` 等的需求均不变，
index 简介增厚属内容更新非需求变更。）

## Impact

- 受影响文件：`agents/{planner-plan,implementer,code-fix,administrator,self-review,arbiter}.md`、
  `CLAUDE.md`、`skills/fenix-new/SKILL.md`、`skills/fenix-process/SKILL.md`、
  `spec/knowledge/index.md`；全部为内容层修改，无 Python/TS 代码改动。
- 行为影响：daemon 全部项目的上述车道 prompt 变长（每车道约 +5~8 行）；token 开销
  上界受控（index 44 行 + 按需下钻）。
- 依赖关系：本 SPEC 是 `add-knowledge-inbox-pipeline`（SPEC B）的前置——B 的
  CLAUDE.md 回填纪律文案与本 SPEC 的指路文案同段落位。
