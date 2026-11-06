## Why

add-spec-chinese-title 落地的中文标题生成纪律是**提示词级**约束（fenix-new skill / evolution 契约），其生效半径受「加载时刻」钳制：Skill 工具内容是会话开局快照，盘上更新不回流已加载会话——实证 2026-11-06 `add-spec-subtitle-and-row-click` 立项时 SKILL.md 纪律已落盘 1.5 小时，立项会话仍按开局旧副本执行、漏写 title。提示词自检防不住此类陈旧副本（自检指令同样来自旧副本），唯一可靠收口是 daemon 侧机械网：不依赖任何会话新鲜度，缺 title 的 SPEC 在晋升门被机械打回。

## What Changes

- **晋升硬门**（新增）：`core/pm_engine/promotion.py` 晋升 lint 族（drafted→ready，与 lint_declared / lint_tasks_parseable 同链）新增 title 存在性检查——`.spec.yaml` 缺非空 `title` 字段即晋升违规，违规消息给处方（含写入示例，指向 add-spec-chinese-title 生成纪律）。
- **豁免口径**：`fix-cr-*` 前缀 SPEC 豁免（code-fix 通道为程序化模板生成，add-spec-chinese-title proposal 已文档化为非目标）；其余通道（fenix-new / evo）与手工创建一律必填。
- **违规可自愈**：立项方（实现分支或交互会话）补写 title 后，30 分钟周期扫描重试晋升即过——与既有声明 lint 违规的恢复路径同型，无新增人工介入面。

**非目标**：读侧长度校验（5-25 字仍是生成纪律，读侧容错不变）；fenix-new/evo 提示词改动（已落地且继续生效，硬门是兜底网不是替代）。

## Capabilities

### New Capabilities

（无）

### Modified Capabilities

- `draft-promotion-gate`（知识页 `spec/knowledge/domains/spec-lifecycle/draft-promotion-gate.md`，活跃能力）：晋升门检查项新增 title 存在性（fix-cr-* 豁免）。

## Impact

- **代码面**：`core/pm_engine/promotion.py`（新增一条 lint 检查，复用 `read_spec_title` 或同源 yaml 读取）+ 单测；无前端、无数据迁移。
- **存量面**：存量 SPEC 已全量回填 title（add-spec-chinese-title 交付），晋升门上线对存量零拦截；实现期新建且漏写 title 的 SPEC 会被打回补写——预期行为。
- **风险面**：硬门楔死风险低（补写一行即解锁、处方明文）；与「门禁平铺事故」教训对齐——违规消息必须带处方，不留零解释 pending。
