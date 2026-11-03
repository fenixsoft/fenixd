# 知识消费纪律（index-first 指路）

<!-- knowledge: capability=knowledge-consumption-discipline rev=1
     sources=spec/changes/add-knowledge-consumption-discipline -->

规定 daemon 消费车道与交互会话在动手前先查知识真相源索引的纪律，让蒸馏产物被实际消费而非自产自销；纪律为静态提示词文本，零代码路径。

## 规则

- **消费车道覆盖**：`planner-plan`、`implementer`、`code-fix`、`administrator`、`self-review`、`arbiter` 六个提示词车道各含一个知识纪律段；`agents/` 是框架级文件，纪律行对 daemon 全部项目生效。
- **条件 MUST 语义**：接手排查/立项/实现类任务先读 `spec/knowledge/index.md` 判断相关能力域是硬纪律；命中相关域则 MUST 下钻 `domains/<域>/_domain.md` 与相关能力页后再动手；未命中可跳过，MUST NOT 为走流程而全量阅读（token 纪律，反目标为纪律形式化推高开销）。
- **分车道侧重**：implementer 动手改某模块前先查该模块所在域能力页、MUST NOT 凭记忆臆测既有行为；planner-plan 立项/出题前查重，proposal 引用既有能力防重复立项与脱节场景；code-fix 修复前对齐修复对象所在域的既有规则与历史修复约定；administrator 排查困境先查信号相关域知识、MUST NOT 从零搜索代码库重复考古；self-review 起草回顾条目时对账既有能力（已蒸馏规则不算新发现）；arbiter 仲裁前以已蒸馏规则校准处置面判断。基准文案一致，各车道仅微调一句话，语义不得偏离条件 MUST 框架。
- **存在性条件**：项目尚无 `spec/knowledge/` 目录时静默跳过（无报错、无常驻开销、无新增配置项）；不引入项目级配置门控，靠存在性条件自然分层。
- **交互会话面**：项目 `CLAUDE.md` 含同款 index-first 指路；回填纪律——值得沉淀的排查/立项结论投递 `spec/knowledge/_inbox/`，该目录由 SPEC `add-knowledge-inbox-pipeline` 提供，尚不存在时先不投递、不自行创建。
- **skill 面**：仓内 `skills/fenix-new/SKILL.md` 起草 proposal 前先读 index 识别相关域并下钻能力页，核对既有能力当前规则；`skills/fenix-process/SKILL.md` 分诊涉及具体能力面的 SPEC 时先下钻能力页，对账「当前生效规则」与本 SPEC 实际行为/进度表述，发现规则漂移在「需要关注」中提示蒸馏回填。
- **index 简介质量**：`index.md` 每域简介 2~3 句、覆盖该域主要能力面，须能独立支撑「任务 ↔ 域」判断（仅凭 index 锁定候选域再下钻，无需先开任何 `_domain.md`）；素材取各域 `_domain.md` 既有简介与能力清单，不引入新事实；简介列保持单行单元格且不含裸竖线 `|`（校验器按竖线切列校验结构，竖线/换行确定性触发时间格式违规）。
- **契约页同步**：目录契约页（`knowledge-atlas-directory`）是蒸馏 run 维护 `index.md` 的契约依据；index 形态变化必须同步契约页对应表述并刷新盖戳，否则下次蒸馏会按旧契约把新形态回退。

## 关键行为

- 命中相关域的任务：run 转录先出现读取 `spec/knowledge/index.md` 与相关能力页的调用，实现所引用的能力页规则与当前代码行为一致。
- 无关任务：读完 index 即继续，无域页/能力页阅读、无告警、无阻塞。

## 溯源

- 2026-11-03 add-knowledge-consumption-discipline（spec/changes/add-knowledge-consumption-discipline/） — 新增本能力页：六车道/CLAUDE.md/skill 三面 index-first 消费契约（条件 MUST、存在性条件、`_inbox/` 回填预告）与 index 域级简介增厚质量要求
