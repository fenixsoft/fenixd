# fix-quality-gates-terminal-blindspot

## Why

质量门禁读侧合成（add-quality-gates-visibility + add-impl-selfcheck-model-probe）存在两个终态盲区，已完成 SPEC 的门禁面板误导用户：

1. **ocr 门 merge-back 后恒 pending**：`_lane_fingerprint_ok` 校验产物指纹三元组 `(branch, merge_base, head_commit)`。spec push 后 merge-back 把实现分支合入 main，`git merge-base <branch> main` 必然前移到分支尖自身，与产物记录的评审基线（merge-back 前的 merge-base）必然不等 → 产物被判 stale 不可见 → 已 `completed` 的审查恒显示 pending。实证：`add-code-fix-batch-failure-selfheal`（pushed，产物 status=completed、branch/head 全等、仅 merge_base 失配）门禁显示 pending。这是结构性必现：**任何成功 push 的 spec 该门恒 pending**。指纹校验的初衷是修复轮 head 前移后拒采信陈旧报告，未豁免 merge-back 这一正常生命周期迁移。

2. **full-suite 门终态语义缺失**：该门数据源优先级为框架侧回归产物（带分支指纹）> run 内自查值 > pending。SPEC 终态（pushed/done/verified）后 main 持续前进，回归快照指纹必然陈旧 → 不可见；回落 run 自查键，而 add-impl-selfcheck-model-probe 3.1 后实现者默认不写 full-suite 键 → 恒 pending。终态 SPEC 面板显示「全量回归测试未完成」语义错误（门的历史使命已了结，回归跟踪责任已移交主树）。

两处均为读侧显示缺陷，不涉及任何门禁判定放宽；spec 本身的验证结论（如 15/15 场景全绿）不受影响。

## What Changes

- **读侧 ocr 门指纹校验 merge-back 豁免**：`core/dashboard/data/quality_gates.py` 的 `_lane_fingerprint_ok`——当前指纹的 `merge_base == head_commit`（分支已完整合入主基线，merge-back 已发生的构造性判据）时跳过产物 `merge_base` 比对；`branch` 与 `head_commit` 仍 MUST 全等（修复轮 head 前移仍拒采信，重审语义不变）。
- **full-suite 门终态豁免**：`_full_suite_status`——spec status ∈ {verified, done, pushed} 时直接合成 `skipped`（固定 reason 文案，计入 done），豁免优先级高于框架产物源与 run 自查源；非终态的数据源优先级与逐字节语义不变。
- 纯读侧小改 + 单元测试；无前端改动、无落盘契约变化、无写侧改动。

## Capabilities

### 修改的 Capability

- `quality-gates-progress`：读侧合成规则修订（ocr 门指纹 merge-back 豁免 + full-suite 终态豁免）。非新增能力。

## Impact

- 代码：`core/dashboard/data/quality_gates.py`（单模块，2 个函数小改 + 1 个终态常量）
- 测试：`tests/test_quality_gates_progress.py` 新增豁免/非豁免场景用例
- 不改动：落盘契约（quality-gates.json 键集不变）、ocr 车道写侧（code-review.json 指纹结构不变）、前端 Card 渲染（skipped 已有「不适用」样式）、框架守卫判定
- 已知非目标：历史 spec（ocr 车道上线前）无产物时 code-review 门 pending 的显示不在本变更范围
