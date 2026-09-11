# 设计：fix-verify-verdict-visibility

## Context

add-daily-self-review 验证产生 1 个失败场景（断言选择器 `.ant-collapse-content`
在 antd v6 已改名），裁决链正确归类 test-defect；`parse_bugs` 按
verdict-evidence-taxonomy 设计过滤非 product-bug 分类 → Bug 列表空；但
`list_screenshots` 直列目录 → 失败截图照常显示；前端 detail.tsx 未渲染
classification/status_corrected/assertion_triage → 裁决结论无处可见。
同类出题错误已在 add-daily-self-review、add-v3-spec-detail-page 两个 spec 发生。

数据现状（均已存在，无需新增采集）：
- report.json scenarios 每项含 `classification`、`status_corrected`、
  `evidence`（含 failed_assertions/first_failed_step/screenshots）、
  `assertion_triage`（逐断言分类）。
- 前端 `/api/specs/<name>` 已返回 `scenarios`（含上述字段）与 `bugs`。

## Goals / Non-Goals

**Goals**
- Bug 列表页签呈现被裁决过滤的失败场景摘要（消除三页签矛盾）。
- verifier 出题加选择器实测约束（防类名知识过期复发）。

**Non-Goals**
- 不改裁决语义（enforce_status_mapping、parse_bugs 过滤规则保持不变）。
- 不改「失败截图」页签的目录列举行为（截图是证据，保留全量展示）。
- 不为 test-defect 场景补跑验证（两个相关 spec 均已 pushed，不再验证）。

## Decisions

1. **新增 `filtered_failures` 后端结构，而非前端从 scenarios 现算**。
   理由：与 `bugs` 对称（同一过滤语义的互补面），归一化逻辑（截图 basename、
   evidence 摘要）收敛在 data.py 一处；前端保持薄渲染。备选「前端直接过滤
   scenarios」被否：过滤规则散落两处，且 scenarios 全量传输已存在（不省），
   但规则漂移风险与 parse_bugs 当年的枚举漂移事故同构（见
   fenixd-parse-bugs-status-enum-drift）。
2. **摘要渲染在 Bug 列表页签内（bugs 为空时折叠/列表展示），不新建页签**。
   理由：用户困惑发生地就是 Bug 列表空态；新页签稀释注意力且 Badge 计数
   语义复杂化。有 bugs 时摘要折叠为次级区块，避免双列表混淆。
3. **evidence 摘要取 `evidence.first_failed_step`（人类可读裁决理由），
   缺省回退 failed_assertions 首项 actual**。理由：first_failed_step 是
   裁决 Agent 产出的结论文本，信息密度最高；旧数据无 evidence 时回退
   断言 message，与 parse_bugs 的回退次序一致。
4. **verifier 规则落在 agents/verifier.md 模板步骤 4 之后新增出题约束段**。
   理由：verifier.md 是 verifier agent 提示词唯一模板源（prompt_builder
   动态段+模板双落点中，此约束属静态规则，仅模板落点）；规则写成 MUST
   级并附 antd v6 反例。注意改动前先 merge main（prompt 文件契约段教训：
   fenixd-prompt-files-merge-conflict-rehome）。

## Risks / Trade-offs

- [旧 report.json 无 classification → filtered_failures 与 bugs 双计？]
  → 不会：二者过滤条件互斥（bugs 收录 classification 非 product-bug 之外的
  fail-open 面 + product-bug；filtered_failures 仅收非 product-bug 分类），
  spec 中以 Scenario 固化。
- [evidence 结构变化（无 first_failed_step）] → 多级回退链
  first_failed_step → failed_assertions[0].actual → 空串，缺字段不抛错。
- [verifier 忽略新规则] → 规则置 MANDATORY 段并用反例具象化；验证面
  （spec Scenario）以提示词文本存在性校验兜底。

## Migration Plan

纯增量字段+前端渲染+提示词追加，无迁移。合并后按惯例重启 daemon 与
dashboard（data.py 改动需重启 8787 实例）。
